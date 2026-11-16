"""Construction des variables et préparation des données pour les modèles.

Toutes les nouvelles variables sont calculées à partir des colonnes d'une même ligne, donc
uniquement avec des informations connues à la date de référence : aucune fuite d'information
venant du futur.
"""
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Valeur utilisée quand aucune session n'a eu lieu sur 60 jours : on ne sait pas depuis
# combien de temps le client est inactif, mais c'est au moins 61 jours.
JOURS_SANS_SESSION_MAX = 61


def construire(df):
    """Ajoute les variables dérivées. Renvoie une copie, le tableau d'origine n'est pas modifié."""
    x = df.copy()

    # Indicateurs d'absence : la valeur manquante a elle-même un sens métier.
    x["sans_session_60j"] = x["jours_depuis_derniere_session"].isna().astype(int)
    x["sans_historique_30_60j"] = x["evolution_sessions"].isna().astype(int)
    x["jours_depuis_derniere_session"] = x["jours_depuis_derniere_session"].fillna(JOURS_SANS_SESSION_MAX)

    # Rapports et seuils simples, faciles à expliquer au service client
    x["anciennete_mois"] = x["anciennete_jours"] / 30.0
    x["supports_par_session"] = x["supports_30j"] / (x["sessions_30j"] + 1)
    x["a_reclame_30j"] = (x["reclamations_30j"] > 0).astype(int)
    x["inactif_14j"] = (x["jours_depuis_derniere_session"] >= 14).astype(int)
    x["baisse_sessions"] = x["sessions_30_60j"] - x["sessions_30j"]
    return x


# Variables candidates, avant sélection (voir selection.py)
NUMERIQUES = [
    "prix_mensuel", "anciennete_jours", "anciennete_mois", "sessions_30j", "sessions_30_60j",
    "evolution_sessions", "baisse_sessions", "supports_30j", "reclamations_30j",
    "supports_par_session", "jours_depuis_derniere_session",
]
BINAIRES = ["sans_session_60j", "sans_historique_30_60j", "a_reclame_30j", "inactif_14j"]
CATEGORIELLES = ["plan_code", "taille_commune", "code_departement"]


def preparation(numeriques, binaires, categorielles):
    """Pipeline de préparation, ajusté sur l'apprentissage seulement puis appliqué tel quel.

    - numériques : valeurs manquantes remplacées par la médiane, puis mise à l'échelle ;
    - binaires : laissées telles quelles (0 ou 1) ;
    - catégorielles : encodage « une colonne par modalité », une modalité inconnue est ignorée.
    """
    blocs = []
    if numeriques:
        blocs.append(("num", Pipeline([("manquants", SimpleImputer(strategy="median")),
                                       ("echelle", StandardScaler())]), numeriques))
    if binaires:
        blocs.append(("bin", "passthrough", binaires))
    if categorielles:
        blocs.append(("cat", Pipeline([("manquants", SimpleImputer(strategy="most_frequent")),
                                       ("encodage", OneHotEncoder(handle_unknown="ignore"))]), categorielles))
    return ColumnTransformer(blocs)


def noms_sortie(prep):
    """Noms lisibles des colonnes après préparation (utiles pour lire les importances)."""
    return [n.split("__", 1)[1] for n in prep.get_feature_names_out()]


def sans_infini(x):
    """Sécurité : aucune valeur infinie ne doit atteindre les modèles."""
    return x.replace([np.inf, -np.inf], np.nan)
