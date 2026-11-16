"""Contrôle de qualité du modèle en production, utilisé avant tout déploiement (intégration continue).

Le déploiement est bloqué (code de sortie 1) si :
  - le modèle de production ne se charge pas ou ne produit pas de probabilités valides ;
  - ses performances sur le test sont sous les seuils minimaux fixés ci-dessous.
Usage : python verifier_modele.py [version]     (par défaut, la version en production)
"""
import sys

import pandas as pd

import registre

AUC_ROC_MIN = 0.75          # en dessous, le classement des clients n'est pas assez fiable
GAIN_AUC_PR_MIN = 4.0       # l'AUC PR doit valoir au moins 4 fois le taux de résiliation (gain sur le hasard)

EXEMPLE = {"client_pseudo": "controle", "date_reference": pd.Timestamp("2026-03-01"), "plan_code": "ESS",
           "prix_mensuel": 9.99, "anciennete_jours": 736, "sessions_30j": 1, "sessions_30_60j": 8,
           "evolution_sessions": -0.88, "supports_30j": 0, "reclamations_30j": 0,
           "jours_depuis_derniere_session": 22, "code_departement": "44", "taille_commune": "grande"}


def main(version=None):
    """Lève SystemExit(1) si le modèle est refusé."""
    from variables import construire
    erreurs = []
    try:
        modele, fiche = registre.charger(version)
    except Exception as e:                      # le modèle doit au minimum se charger
        print(f"ÉCHEC : modèle de production introuvable ou illisible ({e})")
        sys.exit(1)

    v = fiche["variables"]
    proba = modele.predict_proba(construire(pd.DataFrame([EXEMPLE]))[v["numeriques"] + v["binaires"] + v["categorielles"]])[:, 1]
    if not (0 <= proba[0] <= 1):
        erreurs.append(f"probabilité hors de [0, 1] : {proba[0]}")

    m = fiche["mesures_test"]
    if m["auc_roc"] < AUC_ROC_MIN:
        erreurs.append(f"AUC ROC {m['auc_roc']:.3f} inférieure à {AUC_ROC_MIN}")
    taux_base = fiche["donnees"].get("taux_resiliation_test")
    if taux_base and m["auc_pr"] < GAIN_AUC_PR_MIN * taux_base:
        erreurs.append(f"AUC PR {m['auc_pr']:.3f} inférieure à {GAIN_AUC_PR_MIN} fois le taux de base ({taux_base:.3f})")

    print(f"Modèle {fiche['version']} ({fiche['famille']}) : AUC ROC {m['auc_roc']:.3f}, AUC PR {m['auc_pr']:.3f}")
    if erreurs:
        for e in erreurs:
            print("ÉCHEC :", e)
        sys.exit(1)
    print("Contrôle réussi : le modèle peut être déployé.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
