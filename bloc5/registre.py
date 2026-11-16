"""Registre des modèles : chaque modèle entraîné est enregistré dans sa propre version.

Organisation :
  modeles/v001/modele.joblib   le pipeline complet (préparation et modèle), sérialisé
  modeles/v001/fiche.json      la fiche du modèle : données, variables, réglages, performances
  modeles/production.json      la version actuellement servie par l'API
Une version enregistrée n'est jamais modifiée : on peut toujours revenir à une version antérieure.

Sur GCP, le registre de référence est dans le seau Cloud Storage (modeles/) : le dossier local
n'en est qu'une copie, mise à jour avant chaque lecture et publiée après chaque écriture.
"""
import json
import os
import platform
from datetime import datetime

import joblib
import sklearn

import stockage
from config import DOSSIER_MODELES

FICHIER_PRODUCTION = os.path.join(DOSSIER_MODELES, "production.json")


def synchroniser():
    """Copie locale du registre partagé (sans effet en mode local)."""
    if stockage.en_ligne():
        stockage.telecharger_dossier("modeles/", DOSSIER_MODELES)


def versions():
    synchroniser()
    if not os.path.isdir(DOSSIER_MODELES):
        return []
    return sorted(d for d in os.listdir(DOSSIER_MODELES) if d.startswith("v") and d[1:].isdigit())


def enregistrer(pipeline, fiche):
    """Crée une nouvelle version et renvoie son nom (v001, v002, ...)."""
    numero = len(versions()) + 1
    version = f"v{numero:03d}"
    dossier = os.path.join(DOSSIER_MODELES, version)
    os.makedirs(dossier)
    joblib.dump(pipeline, os.path.join(dossier, "modele.joblib"))
    fiche = {"version": version, "cree_le": datetime.now().isoformat(timespec="seconds"),
             "environnement": {"python": platform.python_version(), "scikit_learn": sklearn.__version__},
             **fiche}
    with open(os.path.join(dossier, "fiche.json"), "w", encoding="utf-8") as f:
        json.dump(fiche, f, ensure_ascii=False, indent=2, default=str)
    if stockage.en_ligne():
        stockage.envoyer_dossier(dossier, f"modeles/{version}")
    return version


def fiche(version):
    with open(os.path.join(DOSSIER_MODELES, version, "fiche.json"), encoding="utf-8") as f:
        return json.load(f)


def version_production():
    synchroniser()
    if not os.path.exists(FICHIER_PRODUCTION):
        return None
    with open(FICHIER_PRODUCTION, encoding="utf-8") as f:
        return json.load(f)["version"]


def promouvoir(version, motif):
    """Désigne la version servie par l'API, en gardant une trace de la décision."""
    historique = []
    synchroniser()
    if os.path.exists(FICHIER_PRODUCTION):
        with open(FICHIER_PRODUCTION, encoding="utf-8") as f:
            historique = json.load(f).get("historique", [])
    historique.append({"version": version, "le": datetime.now().isoformat(timespec="seconds"), "motif": motif})
    with open(FICHIER_PRODUCTION, "w", encoding="utf-8") as f:
        json.dump({"version": version, "historique": historique}, f, ensure_ascii=False, indent=2)
    if stockage.en_ligne():
        stockage.envoyer(FICHIER_PRODUCTION, "modeles/production.json")


def charger(version=None):
    """Charge une version donnée, ou la version de production par défaut."""
    version = version or version_production()
    if version is None:
        raise FileNotFoundError("Aucun modèle en production : lancer d'abord optimisation.py")
    return joblib.load(os.path.join(DOSSIER_MODELES, version, "modele.joblib")), fiche(version)
