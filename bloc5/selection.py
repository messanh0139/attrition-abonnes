"""Sélection des variables, réalisée uniquement sur la période d'apprentissage.

Quatre approches complémentaires :
  1. un filtre statistique : la variable se distingue-t-elle entre clients partis et restés ?
     (test de Mann-Whitney pour les variables numériques, test du khi² pour les catégorielles) ;
  2. une recherche de redondance : deux variables portant la même information ;
  3. une méthode incorporée : régression logistique pénalisée L1, qui annule les coefficients
     des variables inutiles ;
  4. une élimination récursive (RFE) : on retire une à une les variables les moins utiles au
     modèle, ce qui donne un rang à chacune (1 = conservée jusqu'au bout).
Résultats : resultats/selection_variables.csv et resultats/variables_retenues.json
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, mannwhitneyu
from sklearn.feature_selection import RFE, mutual_info_classif
from sklearn.linear_model import LogisticRegression

import stockage
from config import CIBLE, DOSSIER_RESULTATS, GRAINE
from donnees import charger, decouper, garder_cible_connue
from variables import BINAIRES, CATEGORIELLES, NUMERIQUES, construire, noms_sortie, preparation

SEUIL_P = 0.05          # seuil de significativité des tests
SEUIL_CORRELATION = 0.95
SEUIL_COEF_L1 = 0.01    # en dessous, le coefficient est considéré comme négligeable


def filtre_statistique(df):
    """p-valeur et information mutuelle de chaque variable candidate."""
    y = df[CIBLE]
    lignes = []
    for v in NUMERIQUES + BINAIRES:
        valeurs = df[v]
        partis, restes = valeurs[y == 1].dropna(), valeurs[y == 0].dropna()
        p = mannwhitneyu(partis, restes).pvalue
        lignes.append({"variable": v, "type": "numérique" if v in NUMERIQUES else "binaire", "test": "Mann-Whitney",
                       "p_valeur": p, "moyenne_partis": partis.mean(), "moyenne_restes": restes.mean()})
    for v in CATEGORIELLES:
        p = chi2_contingency(pd.crosstab(df[v].fillna("inconnu"), y))[1]
        lignes.append({"variable": v, "type": "catégorielle", "test": "khi²", "p_valeur": p})
    resultat = pd.DataFrame(lignes)

    # Information mutuelle : mesure toute forme de lien avec la cible, même non linéaire
    x = df[NUMERIQUES + BINAIRES].fillna(df[NUMERIQUES + BINAIRES].median())
    for v in CATEGORIELLES:
        x[v] = df[v].fillna("inconnu").astype("category").cat.codes
    discretes = [c in BINAIRES or c in CATEGORIELLES for c in x.columns]
    im = mutual_info_classif(x, df[CIBLE], discrete_features=discretes, random_state=GRAINE)
    resultat["information_mutuelle"] = resultat["variable"].map(dict(zip(x.columns, im)))
    return resultat


def redondances(df, info_mutuelle):
    """Variables qui répètent une autre variable : on garde celle qui porte le plus d'information."""
    ecartees = {}
    correl = df[NUMERIQUES].corr(method="spearman").abs()
    for i, a in enumerate(NUMERIQUES):
        for b in NUMERIQUES[i + 1:]:
            if correl.loc[a, b] > SEUIL_CORRELATION and a not in ecartees and b not in ecartees:
                faible, forte = sorted((a, b), key=lambda v: info_mutuelle[v])
                ecartees[faible] = f"redondante avec {forte} (corrélation {correl.loc[a, b]:.2f})"
    # Une catégorie qui détermine entièrement une variable numérique est redondante avec elle
    for cat in CATEGORIELLES:
        for num in NUMERIQUES:
            if num not in ecartees and df.groupby(cat)[num].nunique().max() == 1 and df[num].nunique() == df[cat].nunique():
                ecartees[cat] = f"redondante avec {num} (une valeur de {num} par modalité)"
    return ecartees


def methode_integree(df, numeriques, binaires, categorielles):
    """Régression logistique L1 : renvoie, par variable d'origine, le plus grand coefficient en valeur absolue."""
    prep = preparation(numeriques, binaires, categorielles)
    x = prep.fit_transform(df)
    modele = LogisticRegression(penalty="l1", solver="liblinear", C=0.05, class_weight="balanced",
                                random_state=GRAINE).fit(x, df[CIBLE])
    coefficients = pd.Series(np.abs(modele.coef_[0]), index=noms_sortie(prep))
    par_variable = {}
    for nom, valeur in coefficients.items():
        origine = next(v for v in numeriques + binaires + categorielles if nom == v or nom.startswith(v + "_"))
        par_variable[origine] = max(par_variable.get(origine, 0), valeur)
    return par_variable


def elimination_recursive(df, numeriques, binaires, categorielles, a_garder):
    """Élimination récursive avec une régression logistique : rang de chaque variable d'origine.

    Le rang d'une variable catégorielle est celui de sa meilleure modalité.
    """
    prep = preparation(numeriques, binaires, categorielles)
    x = prep.fit_transform(df)
    rfe = RFE(LogisticRegression(class_weight="balanced", max_iter=2000, random_state=GRAINE),
              n_features_to_select=a_garder, step=1).fit(x, df[CIBLE])
    rangs = {}
    for nom, rang in zip(noms_sortie(prep), rfe.ranking_):
        origine = next(v for v in numeriques + binaires + categorielles if nom == v or nom.startswith(v + "_"))
        rangs[origine] = min(rangs.get(origine, 99), int(rang))
    return rangs


def main():
    apprentissage = construire(decouper(garder_cible_connue(charger()))[0])
    tableau = filtre_statistique(apprentissage)
    info = dict(zip(tableau["variable"], tableau["information_mutuelle"]))
    ecartees = redondances(apprentissage, info)

    restantes = [v for v in tableau["variable"] if v not in ecartees]
    coef = methode_integree(apprentissage, [v for v in NUMERIQUES if v in restantes],
                            [v for v in BINAIRES if v in restantes], [v for v in CATEGORIELLES if v in restantes])
    tableau["coefficient_L1"] = tableau["variable"].map(coef)
    rangs = elimination_recursive(apprentissage, [v for v in NUMERIQUES if v in restantes],
                                  [v for v in BINAIRES if v in restantes], [v for v in CATEGORIELLES if v in restantes],
                                  a_garder=10)
    tableau["rang_RFE"] = tableau["variable"].map(rangs)

    # Règle de décision : on garde une variable non redondante si elle est significative
    # ou si la régression L1 lui laisse un coefficient non négligeable.
    def decision(ligne):
        if ligne["variable"] in ecartees:
            return "écartée", ecartees[ligne["variable"]]
        significative = ligne["p_valeur"] < SEUIL_P
        utile_l1 = (ligne["coefficient_L1"] or 0) > SEUIL_COEF_L1
        if significative or utile_l1:
            raisons = (["significative"] if significative else []) + (["coefficient L1 non négligeable"] if utile_l1 else [])
            return "retenue", " et ".join(raisons)
        return "écartée", "non significative et coefficient L1 négligeable"

    tableau[["decision", "motif"]] = tableau.apply(lambda l: pd.Series(decision(l)), axis=1)
    os.makedirs(DOSSIER_RESULTATS, exist_ok=True)
    tableau.round(5).to_csv(os.path.join(DOSSIER_RESULTATS, "selection_variables.csv"), index=False, encoding="utf-8")

    retenues = tableau[tableau["decision"] == "retenue"]["variable"].tolist()
    choix = {"numeriques": [v for v in NUMERIQUES if v in retenues],
             "binaires": [v for v in BINAIRES if v in retenues],
             "categorielles": [v for v in CATEGORIELLES if v in retenues]}
    with open(os.path.join(DOSSIER_RESULTATS, "variables_retenues.json"), "w", encoding="utf-8") as f:
        json.dump(choix, f, ensure_ascii=False, indent=2)

    pd.set_option("display.width", 160)
    print(tableau[["variable", "test", "p_valeur", "information_mutuelle", "coefficient_L1", "rang_RFE", "decision", "motif"]]
          .round(4).to_string(index=False))
    print(f"\n{len(retenues)} variables retenues sur {len(tableau)}.")
    stockage.publier_resultats()


if __name__ == "__main__":
    main()
