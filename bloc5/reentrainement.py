"""Cycle de vie automatisé du modèle : collecte, surveillance, réentraînement, mise en production.

À lancer après chaque export du Bloc 1 (par exemple chaque mois, par le même ordonnanceur) :
  1. collecte : rapproche les prédictions servies par l'API de la résiliation réellement observée ;
  2. surveillance : dérive des variables et performance mois par mois (surveillance.py) ;
  3. décision : réentraîner si une alerte est levée ou si de nouveaux mois étiquetés sont disponibles ;
  4. réentraînement d'un modèle candidat avec la même famille et les mêmes réglages, sur une période
     plus longue, puis comparaison avec le modèle en production sur le dernier mois connu ;
  5. mise en production du candidat seulement s'il n'est pas moins bon (marge de 0,01 d'AUC PR).
Résultat : resultats/cycle.json et journaux/cycle.log
Usage : python reentrainement.py [--forcer]
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
from sklearn.base import clone

import registre
import stockage
from config import CIBLE, DOSSIER_JOURNAUX, DOSSIER_RESULTATS, fichier_donnees
from donnees import charger, garder_cible_connue
from evaluation import mesures
from surveillance import alerter, profil, surveiller
from variables import construire

MARGE = 0.01


def journal(message):
    os.makedirs(DOSSIER_JOURNAUX, exist_ok=True)
    with open(os.path.join(DOSSIER_JOURNAUX, "cycle.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    print(message)


def predictions_historisees():
    """Toutes les prédictions servies par l'API : fichiers du seau sur GCP, fichier local sinon."""
    if stockage.en_ligne():
        fichiers = stockage.lister("predictions/")
        if not fichiers:
            return None
        dossier = os.path.join(DOSSIER_JOURNAUX, "predictions_seau")
        parties = []
        for chemin in fichiers:
            local = os.path.join(dossier, chemin.replace("/", "_"))
            stockage.telecharger(chemin, local)
            parties.append(pd.read_csv(local, parse_dates=["date_reference"]))
        return pd.concat(parties, ignore_index=True)
    chemin = os.path.join(DOSSIER_JOURNAUX, "predictions.csv")
    return pd.read_csv(chemin, parse_dates=["date_reference"]) if os.path.exists(chemin) else None


def collecter_retours(df):
    """Compare les prédictions historisées par l'API avec la résiliation observée depuis."""
    servies = predictions_historisees()
    if servies is None:
        return {"predictions_historisees": 0}
    reel = df[["client_pseudo", "date_reference", CIBLE]].dropna()
    rapprochees = servies.merge(reel, on=["client_pseudo", "date_reference"], how="inner")
    retour = {"predictions_historisees": len(servies), "predictions_avec_resultat": len(rapprochees)}
    if len(rapprochees) and rapprochees[CIBLE].nunique() == 2:
        retour["auc_roc_predictions_servies"] = mesures(rapprochees[CIBLE], rapprochees["probabilite"])["auc_roc"]
    return retour


def main(forcer=False):
    df = charger()
    production, fiche = registre.charger()
    connues = garder_cible_connue(df)
    fin_vue = pd.Timestamp(fiche["donnees"]["periode_test"][1])          # dernier mois déjà vu par le modèle
    nouveaux_mois = sorted(connues.loc[connues["date_reference"] > fin_vue, "date_reference"].unique())

    bilan = {"date": datetime.now().isoformat(timespec="seconds"), "donnees": os.path.basename(fichier_donnees()),
             "version_production": fiche["version"], "retours": collecter_retours(df),
             "nouveaux_mois_etiquetes": [str(pd.Timestamp(m).date()) for m in nouveaux_mois]}
    suivi, alertes, _ = surveiller(df)
    bilan["alertes"] = alertes
    # Le tableau de surveillance est publié pour le tableau de bord
    os.makedirs(DOSSIER_RESULTATS, exist_ok=True)
    suivi.round(4).to_csv(os.path.join(DOSSIER_RESULTATS, "surveillance.csv"), index=False, encoding="utf-8")
    for a in alertes:
        alerter(a)

    if not (alertes or nouveaux_mois or forcer):
        bilan["decision"] = "modèle conservé : aucune alerte et aucun nouveau mois étiqueté"
        journal(bilan["decision"])
    else:
        # Candidat : mêmes préparation et réglages, appris sur tous les mois sauf le dernier connu,
        # qui sert à comparer équitablement le candidat et le modèle en production.
        donnees = construire(connues)
        dernier = donnees["date_reference"].max()
        v = fiche["variables"]
        colonnes = v["numeriques"] + v["binaires"] + v["categorielles"]
        avant, controle = donnees[donnees["date_reference"] < dernier], donnees[donnees["date_reference"] == dernier]

        candidat = clone(production).fit(avant[colonnes], avant[CIBLE])
        m_candidat = mesures(controle[CIBLE], candidat.predict_proba(controle[colonnes])[:, 1], fiche["seuil"])
        m_production = mesures(controle[CIBLE], production.predict_proba(controle[colonnes])[:, 1], fiche["seuil"])
        bilan["comparaison"] = {"mois_de_controle": str(dernier.date()),
                                "auc_pr_candidat": m_candidat["auc_pr"], "auc_pr_production": m_production["auc_pr"]}

        if m_candidat["auc_pr"] >= m_production["auc_pr"] - MARGE:
            # Le candidat est au moins aussi bon : on l'apprend sur tous les mois connus et on le publie
            final = clone(production).fit(donnees[colonnes], donnees[CIBLE])
            version = registre.enregistrer(final, {
                **{k: fiche[k] for k in ("famille", "reglages", "variables", "seuil")},
                "donnees": {"fichier": os.path.basename(fichier_donnees()), "lignes_apprentissage": int(len(donnees)),
                            "lignes_test": int(len(controle)), "taux_resiliation_test": float(controle[CIBLE].mean()),
                            "periode_apprentissage": [str(donnees["date_reference"].min().date()), str(dernier.date())],
                            "periode_test": [str(controle["date_reference"].min().date()), str(dernier.date())]},
                "mesures_validation": fiche["mesures_validation"], "mesures_test": m_candidat,
                "reference": {c: profil(donnees[c]) for c in v["numeriques"]},
                "remplace": fiche["version"]})
            registre.promouvoir(version, f"réentraînement : AUC PR {m_candidat['auc_pr']:.3f} contre "
                                         f"{m_production['auc_pr']:.3f} pour {fiche['version']} sur {dernier.date()}")
            bilan["decision"] = f"nouvelle version {version} mise en production"
        else:
            bilan["decision"] = f"candidat moins bon : {fiche['version']} conservée"
        journal(f"{bilan['decision']} ({bilan['comparaison']})")

    os.makedirs(DOSSIER_RESULTATS, exist_ok=True)
    with open(os.path.join(DOSSIER_RESULTATS, "cycle.json"), "w", encoding="utf-8") as f:
        json.dump(bilan, f, ensure_ascii=False, indent=2, default=str)
    stockage.publier_resultats()


if __name__ == "__main__":
    main(forcer="--forcer" in sys.argv)
