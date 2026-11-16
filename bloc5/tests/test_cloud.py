"""Tests du fonctionnement sur GCP, avec un seau simulé par un dossier (BLOC5_BUCKET=fichier://...).

Ils vérifient, sans compte Google Cloud, le même code que celui exécuté sur Cloud Run :
données lues dans le seau, registre partagé, historisation des prédictions, mise en production
décidée par publier_modele.py et tableau de bord.
"""
import os
import shutil
import tempfile

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import registre
import stockage
from config import DOSSIER_MODELES


@pytest.fixture
def seau(monkeypatch):
    dossier = tempfile.mkdtemp(prefix="seau_")
    monkeypatch.setenv("BLOC5_BUCKET", f"fichier://{dossier}")
    yield dossier
    shutil.rmtree(dossier, ignore_errors=True)


@pytest.fixture
def registre_isole(monkeypatch):
    """Registre local vide, propre au test, pour ne pas mélanger avec les autres tests."""
    dossier = tempfile.mkdtemp(prefix="registre_")
    monkeypatch.setattr(registre, "DOSSIER_MODELES", dossier)
    monkeypatch.setattr(registre, "FICHIER_PRODUCTION", os.path.join(dossier, "production.json"))
    return dossier


@pytest.fixture
def modele_de_reference():
    """Un modèle entraîné sur le jeu synthétique, réutilisé par les tests de ce fichier."""
    import optimisation
    import selection
    if registre.version_production() is None:
        selection.main()
        optimisation.main()
    return registre.charger()


def test_seau_lecture_ecriture(seau):
    stockage.ecrire_texte("resultats/essai.txt", "bonjour")
    assert stockage.existe("resultats/essai.txt")
    assert stockage.lire_texte("resultats/essai.txt") == "bonjour"
    assert stockage.lister("resultats/") == ["resultats/essai.txt"]


def test_donnees_lues_dans_le_seau(seau, monkeypatch):
    import config
    source = os.environ["BLOC5_DONNEES"]
    stockage.envoyer(source, "donnees/variables_clients_2026-10-30.csv")
    monkeypatch.delenv("BLOC5_DONNEES")
    chemin = config.fichier_donnees()
    assert chemin.endswith("variables_clients_2026-10-30.csv") and os.path.exists(chemin)
    assert len(pd.read_csv(chemin)) == len(pd.read_csv(source))


def test_registre_partage_dans_le_seau(modele_de_reference, seau, registre_isole):
    modele, fiche = modele_de_reference
    contenu = {k: v for k, v in fiche.items() if k not in ("version", "cree_le", "environnement")}
    version = registre.enregistrer(modele, contenu)
    registre.promouvoir(version, "test du registre partagé")
    assert stockage.existe(f"modeles/{version}/modele.joblib")
    assert stockage.existe("modeles/production.json")
    # Une autre machine, avec un registre local vide, retrouve la même version en production
    shutil.rmtree(registre_isole)
    assert registre.version_production() == version
    assert registre.charger()[1]["version"] == version


def test_api_historise_dans_le_seau(modele_de_reference, seau):
    import api
    import reentrainement
    stockage.envoyer_dossier(DOSSIER_MODELES, "modeles")
    client = {"client_pseudo": "c0001", "date_reference": "2026-09-01", "prix_mensuel": 9.99, "anciennete_jours": 400,
              "sessions_30j": 2, "sessions_30_60j": 9, "evolution_sessions": -0.78, "supports_30j": 1,
              "reclamations_30j": 1, "jours_depuis_derniere_session": 20, "code_departement": "44",
              "taille_commune": "grande"}
    with TestClient(api.app) as c:
        assert c.post("/predire", json={"clients": [client, {**client, "client_pseudo": "c0002"}]}).status_code == 200
    assert len(stockage.lister("predictions/")) == 1
    historique = reentrainement.predictions_historisees()
    assert list(historique["client_pseudo"]) == ["c0001", "c0002"]


def test_publication_selon_la_performance(modele_de_reference, registre_isole):
    import publier_modele
    modele, fiche = modele_de_reference
    contenu = {k: v for k, v in fiche.items() if k not in ("version", "cree_le", "environnement")}
    actuelle = registre.enregistrer(modele, contenu)
    registre.promouvoir(actuelle, "version de départ")
    # Nouvelle version nettement moins bonne : la version actuelle est conservée
    moins_bonne = registre.enregistrer(modele, {**contenu, "mesures_test": {**contenu["mesures_test"],
                                                                          "auc_pr": contenu["mesures_test"]["auc_pr"] - 0.05}})
    publier_modele.main()
    assert registre.version_production() == actuelle
    # Nouvelle version au moins aussi bonne : elle est mise en production
    meilleure = registre.enregistrer(modele, {**contenu, "mesures_test": {**contenu["mesures_test"],
                                                                        "auc_pr": contenu["mesures_test"]["auc_pr"] + 0.01}})
    publier_modele.main()
    assert registre.version_production() == meilleure != moins_bonne


def test_tableau_de_bord(modele_de_reference):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "dashboard.py"), default_timeout=60).run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Prédire", "Modèle en production", "Surveillance", "Prédictions servies"]
    app.button[0].click().run()                      # formulaire de prédiction, calcul local
    assert not app.exception
    assert app.metric[0].label == "Probabilité de résiliation à 30 jours"
