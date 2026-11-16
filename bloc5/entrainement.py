"""Entraînement et comparaison de plusieurs familles de modèles.

Chaque modèle est appris sur la période d'apprentissage puis évalué sur la période de
validation, avec les variables retenues par selection.py. Une référence naïve (qui prédit
toujours le taux moyen) sert de point de comparaison : un modèle utile doit faire nettement mieux.
Résultat : resultats/comparaison_modeles.csv
"""
import json
import os
import time

import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

import stockage
from config import CIBLE, DOSSIER_RESULTATS, GRAINE
from donnees import charger, decouper, garder_cible_connue
from evaluation import mesures
from variables import construire, preparation


def variables_retenues():
    with open(os.path.join(DOSSIER_RESULTATS, "variables_retenues.json"), encoding="utf-8") as f:
        return json.load(f)


def modeles_candidats():
    """Cinq familles, de la plus simple à la plus flexible, avec leurs réglages par défaut.

    class_weight="balanced" (ou scale_pos_weight pour XGBoost) donne plus de poids aux résiliations,
    rares, pendant l'apprentissage.
    """
    return {
        "reference_naive": DummyClassifier(strategy="prior"),
        "regression_logistique": LogisticRegression(class_weight="balanced", max_iter=2000, random_state=GRAINE),
        "foret_aleatoire": RandomForestClassifier(n_estimators=300, min_samples_leaf=20, class_weight="balanced_subsample",
                                                  n_jobs=-1, random_state=GRAINE),
        "gradient_boosting": HistGradientBoostingClassifier(learning_rate=0.05, max_iter=300, class_weight="balanced",
                                                            random_state=GRAINE),
        "xgboost": XGBClassifier(n_estimators=300, learning_rate=0.05, max_depth=4, scale_pos_weight=29,
                                 eval_metric="aucpr", random_state=GRAINE, n_jobs=-1),
    }


def pipeline(modele, choix):
    """Préparation et modèle dans un même objet : la même transformation s'applique en production."""
    return Pipeline([("preparation", preparation(choix["numeriques"], choix["binaires"], choix["categorielles"])),
                     ("modele", modele)])


def main():
    choix = variables_retenues()
    colonnes = choix["numeriques"] + choix["binaires"] + choix["categorielles"]
    apprentissage, validation, _ = [construire(p) for p in decouper(garder_cible_connue(charger()))]

    lignes = []
    for nom, modele in modeles_candidats().items():
        debut = time.time()
        pipe = pipeline(modele, choix).fit(apprentissage[colonnes], apprentissage[CIBLE])
        duree = time.time() - debut
        proba = pipe.predict_proba(validation[colonnes])[:, 1]
        lignes.append({"modele": nom, **mesures(validation[CIBLE], proba), "duree_s": duree})

    tableau = pd.DataFrame(lignes).sort_values("auc_pr", ascending=False)
    os.makedirs(DOSSIER_RESULTATS, exist_ok=True)
    tableau.round(4).to_csv(os.path.join(DOSSIER_RESULTATS, "comparaison_modeles.csv"), index=False, encoding="utf-8")
    print("Comparaison sur la période de validation (juin et juillet 2026) :\n")
    print(tableau.round(3).to_string(index=False))
    stockage.publier_resultats()


if __name__ == "__main__":
    main()
