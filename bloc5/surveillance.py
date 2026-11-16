"""Surveillance du modèle en production.

Deux questions, posées à chaque nouvel export du Bloc 1 :
  1. Les données ont-elles changé ? (dérive des variables, mesurée par l'indice PSI)
  2. Le modèle reste-t-il performant ? (AUC calculée mois par mois, dès que la résiliation
     des clients est connue, c'est-à-dire trente jours après la date de référence)
Une alerte est écrite dans journaux/alertes_modele.log si un seuil est dépassé.
Résultat : resultats/surveillance.csv
Usage : python surveillance.py
"""
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

import registre
import stockage
from config import BAISSE_AUC_ALERTE, CIBLE, DOSSIER_JOURNAUX, DOSSIER_RESULTATS, SEUIL_PSI_ALERTE
from donnees import charger
from evaluation import mesures
from variables import construire


def profil(serie, nb_classes=10):
    """Résumé d'une distribution : bornes des déciles et part des valeurs dans chaque classe."""
    bornes = np.unique(np.quantile(serie.dropna(), np.linspace(0, 1, nb_classes + 1)))
    bornes[0], bornes[-1] = -np.inf, np.inf
    parts = pd.cut(serie.dropna(), bornes, include_lowest=True).value_counts(normalize=True, sort=False)
    return {"bornes": bornes.tolist(), "parts": parts.tolist()}


def psi(profil_reference, serie):
    """Population Stability Index : 0 si la distribution est identique, au-delà de 0,2 changement net."""
    bornes = np.array(profil_reference["bornes"])
    attendues = np.array(profil_reference["parts"])
    observees = pd.cut(serie.dropna(), bornes, include_lowest=True).value_counts(normalize=True, sort=False).to_numpy()
    attendues, observees = np.clip(attendues, 1e-4, None), np.clip(observees, 1e-4, None)
    return float(np.sum((observees - attendues) * np.log(observees / attendues)))


def alerter(message):
    """Trace l'alerte localement et l'écrit en JSON sur la sortie standard.

    Sur Cloud Run, Cloud Logging lit cette ligne comme un journal structuré de gravité WARNING :
    une métrique basée sur les journaux (type = alerte_modele) déclenche alors l'alerte de Cloud Monitoring.
    """
    os.makedirs(DOSSIER_JOURNAUX, exist_ok=True)
    with open(os.path.join(DOSSIER_JOURNAUX, "alertes_modele.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} ALERTE {message}\n")
    print(json.dumps({"severity": "WARNING", "type": "alerte_modele", "message": message}, ensure_ascii=False))


def surveiller(df, version=None):
    """Contrôle chaque mois postérieur à l'apprentissage du modèle. Renvoie le tableau et la liste des alertes."""
    modele, fiche = registre.charger(version)
    v = fiche["variables"]
    colonnes = v["numeriques"] + v["binaires"] + v["categorielles"]
    fin_apprentissage = pd.Timestamp(fiche["donnees"]["periode_apprentissage"][1])
    reference_auc = fiche["mesures_validation"]["auc_roc"]

    df = construire(df)
    lignes, alertes = [], []
    for mois, partie in df[df["date_reference"] > fin_apprentissage].groupby("date_reference"):
        ligne = {"mois": mois.date(), "lignes": len(partie)}
        derives = {c: psi(fiche["reference"][c], partie[c]) for c in v["numeriques"]}
        ligne["psi_max"] = max(derives.values())
        ligne["variable_psi_max"] = max(derives, key=derives.get)
        if ligne["psi_max"] > SEUIL_PSI_ALERTE:
            alertes.append(f"{mois.date()} dérive de {ligne['variable_psi_max']} (PSI {ligne['psi_max']:.2f})")

        connues = partie[partie[CIBLE].notna()]
        if len(connues) and connues[CIBLE].nunique() == 2:
            m = mesures(connues[CIBLE], modele.predict_proba(connues[colonnes])[:, 1])
            ligne.update({"auc_roc": m["auc_roc"], "auc_pr": m["auc_pr"], "rappel_top10": m["rappel_top10"]})
            if m["auc_roc"] < reference_auc - BAISSE_AUC_ALERTE:
                alertes.append(f"{mois.date()} baisse de performance (AUC {m['auc_roc']:.3f} "
                               f"contre {reference_auc:.3f} en validation)")
        lignes.append(ligne)
    return pd.DataFrame(lignes), alertes, fiche["version"]


def main():
    tableau, alertes, version = surveiller(charger())
    os.makedirs(DOSSIER_RESULTATS, exist_ok=True)
    tableau.round(4).to_csv(os.path.join(DOSSIER_RESULTATS, "surveillance.csv"), index=False, encoding="utf-8")
    stockage.publier_resultats()
    print(f"Surveillance du modèle {version} sur les mois postérieurs à son apprentissage :\n")
    print(tableau.round(3).to_string(index=False) if len(tableau) else "Aucun mois postérieur à l'apprentissage.")
    for a in alertes:
        alerter(a)
    if not alertes:
        print(f"\nAucune alerte : PSI inférieur à {SEUIL_PSI_ALERTE} et AUC stable.")


if __name__ == "__main__":
    main()
