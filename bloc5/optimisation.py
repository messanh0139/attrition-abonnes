"""Optimisation des hyperparamètres, choix du modèle final, évaluation sur le test et enregistrement.

Étapes :
  1. recherche des meilleurs réglages pour la régression logistique et le gradient boosting,
     avec une validation croisée qui respecte l'ordre du temps (on valide toujours sur un mois
     postérieur aux mois d'apprentissage) ;
  2. comparaison des modèles optimisés sur la période de validation et choix du meilleur ;
  3. choix du seuil de décision sur la validation ;
  4. réapprentissage sur apprentissage + validation, puis évaluation unique sur le test ;
  5. enregistrement dans le registre ; mise en production directe seulement s'il n'existe encore
     aucun modèle en production (sinon, publier_modele.py décide après contrôle et comparaison).
Résultats : resultats/optimisation.csv, resultats/evaluation_test.csv, resultats/importance_variables.csv
"""
import os

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RandomizedSearchCV
from xgboost import XGBClassifier

import registre
import stockage
from config import CIBLE, DOSSIER_RESULTATS, GRAINE, ITERATIONS_RECHERCHE, fichier_donnees
from donnees import charger, decouper, garder_cible_connue
from entrainement import pipeline, variables_retenues
from evaluation import meilleur_seuil, mesures
from surveillance import profil
from variables import construire

ESPACES = {
    "regression_logistique": (
        LogisticRegression(max_iter=3000, solver="liblinear", random_state=GRAINE),
        {"modele__C": [0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0],
         "modele__penalty": ["l1", "l2"],
         "modele__class_weight": [None, "balanced"]}),
    "gradient_boosting": (
        HistGradientBoostingClassifier(random_state=GRAINE),
        {"modele__learning_rate": [0.02, 0.05, 0.1],
         "modele__max_depth": [2, 3, 4, None],
         "modele__min_samples_leaf": [20, 50, 100, 200],
         "modele__l2_regularization": [0.0, 1.0, 10.0],
         "modele__max_iter": [100, 200, 400],
         "modele__class_weight": [None, "balanced"]}),
    "xgboost": (
        XGBClassifier(eval_metric="aucpr", random_state=GRAINE, n_jobs=-1),
        {"modele__n_estimators": [100, 200, 400],
         "modele__learning_rate": [0.02, 0.05, 0.1],
         "modele__max_depth": [2, 3, 4, 6],
         "modele__min_child_weight": [1, 5, 20],
         "modele__subsample": [0.7, 0.9, 1.0],
         "modele__reg_lambda": [1.0, 5.0, 20.0],
         "modele__scale_pos_weight": [1, 10, 29]}),
}


def decoupes_temporelles(dates):
    """Validation croisée glissante : apprendre sur les mois 1 à k, valider sur le mois k+1."""
    mois = sorted(dates.unique())
    for k in range(4, len(mois)):                       # au moins 4 mois d'historique pour apprendre
        yield np.where(dates < mois[k])[0], np.where(dates == mois[k])[0]


def main():
    choix = variables_retenues()
    colonnes = choix["numeriques"] + choix["binaires"] + choix["categorielles"]
    apprentissage, validation, test = [construire(p).reset_index(drop=True) for p in decouper(garder_cible_connue(charger()))]
    xa, ya = apprentissage[colonnes], apprentissage[CIBLE]
    xv, yv = validation[colonnes], validation[CIBLE]

    # 1 et 2. Recherche des réglages puis comparaison sur la validation
    lignes, meilleurs = [], {}
    for nom, (modele, espace) in ESPACES.items():
        recherche = RandomizedSearchCV(pipeline(modele, choix), espace, n_iter=ITERATIONS_RECHERCHE, scoring="average_precision",
                                       cv=list(decoupes_temporelles(apprentissage["date_reference"])),
                                       random_state=GRAINE, n_jobs=-1)
        recherche.fit(xa, ya)
        proba_v = recherche.best_estimator_.predict_proba(xv)[:, 1]
        meilleurs[nom] = recherche
        lignes.append({"modele": nom, "auc_pr_validation_croisee": recherche.best_score_,
                       **{f"{k}_validation": v for k, v in mesures(yv, proba_v).items()},
                       "reglages": {k.replace("modele__", ""): v for k, v in recherche.best_params_.items()}})
    tableau = pd.DataFrame(lignes).sort_values("auc_pr_validation", ascending=False)
    # Gain apporté par l'optimisation : comparaison avec les mêmes familles réglées par défaut
    chemin_defaut = os.path.join(DOSSIER_RESULTATS, "comparaison_modeles.csv")
    if os.path.exists(chemin_defaut):
        defaut = pd.read_csv(chemin_defaut).set_index("modele")["auc_pr"]
        tableau["auc_pr_reglages_par_defaut"] = tableau["modele"].map(defaut)
        tableau["gain_auc_pr"] = tableau["auc_pr_validation"] - tableau["auc_pr_reglages_par_defaut"]
    os.makedirs(DOSSIER_RESULTATS, exist_ok=True)
    tableau.round(4).to_csv(os.path.join(DOSSIER_RESULTATS, "optimisation.csv"), index=False, encoding="utf-8")
    colonnes_affichees = [c for c in ("modele", "auc_pr_validation_croisee", "auc_roc_validation", "auc_pr_validation",
                                      "auc_pr_reglages_par_defaut", "gain_auc_pr") if c in tableau.columns]
    print(tableau[colonnes_affichees].round(3).to_string(index=False))

    retenu = tableau.iloc[0]["modele"]
    recherche = meilleurs[retenu]
    print(f"\nModèle retenu : {retenu}, réglages {tableau.iloc[0]['reglages']}")

    # 3. Seuil choisi sur la validation, avec le modèle appris sur l'apprentissage seul
    proba_v = recherche.best_estimator_.predict_proba(xv)[:, 1]
    seuil = meilleur_seuil(yv, proba_v)
    mesures_validation = mesures(yv, proba_v, seuil)

    # 4. Réapprentissage sur toutes les données disponibles avant le test, puis évaluation unique
    final = clone(recherche.best_estimator_).fit(pd.concat([xa, xv]), pd.concat([ya, yv]))
    proba_t = final.predict_proba(test[colonnes])[:, 1]
    mesures_test = mesures(test[CIBLE], proba_t, seuil)
    pd.DataFrame([{"periode": "validation", **mesures_validation}, {"periode": "test", **mesures_test}]) \
        .round(4).to_csv(os.path.join(DOSSIER_RESULTATS, "evaluation_test.csv"), index=False, encoding="utf-8")
    print("\nValidation :", {k: round(v, 3) for k, v in mesures_validation.items()})
    print("Test       :", {k: round(v, 3) for k, v in mesures_test.items()})

    # Importance des variables par permutation, mesurée sur le test : quelles informations le modèle utilise-t-il ?
    importance = permutation_importance(final, test[colonnes], test[CIBLE], scoring="average_precision",
                                        n_repeats=5, random_state=GRAINE, n_jobs=-1)
    pd.DataFrame({"variable": colonnes, "importance": importance.importances_mean, "ecart_type": importance.importances_std}) \
        .sort_values("importance", ascending=False).round(4) \
        .to_csv(os.path.join(DOSSIER_RESULTATS, "importance_variables.csv"), index=False, encoding="utf-8")

    # 5. Enregistrement et mise en production
    donnees_info = {"fichier": os.path.basename(fichier_donnees()),
                    "lignes_apprentissage": int(len(xa) + len(xv)), "lignes_test": int(len(test)),
                    "taux_resiliation_test": float(test[CIBLE].mean()),
                    "periode_apprentissage": [str(apprentissage["date_reference"].min().date()), str(validation["date_reference"].max().date())],
                    "periode_test": [str(test["date_reference"].min().date()), str(test["date_reference"].max().date())]}
    version = registre.enregistrer(final, {
        "famille": retenu, "reglages": {k: (v if v is None or isinstance(v, str) else float(v)) for k, v in tableau.iloc[0]["reglages"].items()}, "variables": choix, "seuil": seuil,
        "donnees": donnees_info, "mesures_validation": mesures_validation, "mesures_test": mesures_test,
        # Distribution de référence des variables, utilisée par surveillance.py pour détecter une dérive
        "reference": {c: profil(pd.concat([xa, xv])[c]) for c in choix["numeriques"]},
    })
    stockage.publier_resultats()
    if registre.version_production() is None:
        registre.promouvoir(version, f"premier modèle : {retenu}, AUC PR test {mesures_test['auc_pr']:.3f}")
        print(f"\nModèle enregistré et mis en production : {version}")
    else:
        print(f"\nModèle enregistré : {version} (mise en production décidée par publier_modele.py)")


if __name__ == "__main__":
    main()
