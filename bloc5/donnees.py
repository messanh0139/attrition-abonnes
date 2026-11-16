"""Chargement, contrôle et découpage temporel de la table d'analyse."""
import pandas as pd

from config import CIBLE, FIN_APPRENTISSAGE, FIN_VALIDATION, fichier_donnees

COLONNES_ATTENDUES = [
    "client_pseudo", "date_reference", "plan_code", "prix_mensuel", "anciennete_jours",
    "sessions_30j", "sessions_30_60j", "evolution_sessions", "supports_30j", "reclamations_30j",
    "jours_depuis_derniere_session", "code_departement", "taille_commune", CIBLE,
]


def charger(chemin=None):
    """Lit l'export du Bloc 1 et vérifie qu'il a la forme attendue."""
    chemin = chemin or fichier_donnees()
    df = pd.read_csv(chemin, parse_dates=["date_reference"], dtype={"code_departement": str})
    manquantes = [c for c in COLONNES_ATTENDUES if c not in df.columns]
    if manquantes:
        raise ValueError(f"Colonnes absentes de l'export : {manquantes}")
    # Une ligne par client et par date : c'était déjà garanti par la clé primaire en base,
    # mais on le revérifie car le fichier a pu être modifié depuis l'export.
    if df.duplicated(["client_pseudo", "date_reference"]).any():
        raise ValueError("Doublons client et date dans l'export")
    return df


def garder_cible_connue(df):
    """Écarte les lignes dont la cible est indéterminée (période suivante non couverte)."""
    return df[df[CIBLE].notna()].copy()


def decouper(df):
    """Découpage dans le temps : apprentissage, validation, test.

    Un découpage au hasard mélangerait des mois passés et futurs : le modèle serait évalué
    sur une période qu'il a déjà vue, ce qui surestimerait ses performances.
    """
    apprentissage = df[df["date_reference"] <= FIN_APPRENTISSAGE]
    validation = df[(df["date_reference"] > FIN_APPRENTISSAGE) & (df["date_reference"] <= FIN_VALIDATION)]
    test = df[df["date_reference"] > FIN_VALIDATION]
    return apprentissage, validation, test


def resumer(nom, df):
    taux = df[CIBLE].mean() * 100
    print(f"{nom:<14} {len(df):>6} lignes, {df['date_reference'].nunique():>2} mois, "
          f"{int(df[CIBLE].sum()):>4} résiliations ({taux:.2f} %)")


if __name__ == "__main__":
    donnees = garder_cible_connue(charger())
    for nom, partie in zip(("Apprentissage", "Validation", "Test"), decouper(donnees)):
        resumer(nom, partie)
