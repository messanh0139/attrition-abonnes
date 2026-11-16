"""Tests automatisés du Bloc 5 : données, variables, modèles, registre, API et surveillance.

Lancement : python -m pytest -q
"""
import os

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from config import CIBLE


@pytest.fixture
def modele_en_production():
    """Garantit qu'un modèle est en production, même si le test est lancé seul."""
    import optimisation
    import registre
    import selection
    if registre.version_production() is None:
        selection.main()
        optimisation.main()
    return registre.version_production()


def test_decoupage_temporel_sans_chevauchement():
    from donnees import charger, decouper
    a, v, t = decouper(charger())
    assert a["date_reference"].max() < v["date_reference"].min()
    assert v["date_reference"].max() < t["date_reference"].min()
    assert len(a) + len(v) + len(t) == len(charger())


def test_variables_sans_valeur_infinie_ni_usage_de_la_cible():
    from donnees import charger
    from variables import BINAIRES, NUMERIQUES, construire
    df = charger().head(500)
    avec_cible = construire(df)
    sans_cible = construire(df.drop(columns=[CIBLE]))
    colonnes = NUMERIQUES + BINAIRES
    # Les variables construites ne dépendent pas de la cible : pas de fuite d'information
    pd.testing.assert_frame_equal(avec_cible[colonnes], sans_cible[colonnes])
    assert not np.isinf(avec_cible[colonnes].to_numpy(dtype=float)).any()
    assert avec_cible["jours_depuis_derniere_session"].notna().all()


def test_mesures_sur_cas_connus():
    from evaluation import mesures
    y = np.array([0, 0, 0, 1, 1])
    assert mesures(y, np.array([0.1, 0.2, 0.3, 0.8, 0.9]))["auc_roc"] == 1.0     # classement parfait
    assert mesures(y, np.full(5, 0.4))["auc_roc"] == 0.5                         # aucun pouvoir de classement


def test_selection_ecarte_les_variables_redondantes():
    import json
    import selection
    from config import DOSSIER_RESULTATS
    selection.main()
    choix = json.load(open(os.path.join(DOSSIER_RESULTATS, "variables_retenues.json"), encoding="utf-8"))
    retenues = choix["numeriques"] + choix["binaires"] + choix["categorielles"]
    # anciennete_jours et anciennete_mois portent la même information : une seule est gardée
    assert not {"anciennete_jours", "anciennete_mois"} <= set(retenues)
    assert "plan_code" not in retenues or "prix_mensuel" not in retenues


def test_optimisation_enregistre_un_modele_en_production():
    import optimisation
    import registre
    optimisation.main()
    modele, fiche = registre.charger()
    assert fiche["version"] == registre.version_production()
    assert 0.5 < fiche["mesures_test"]["auc_roc"] <= 1.0
    assert hasattr(modele, "predict_proba")


def test_controle_qualite_accepte_le_modele(modele_en_production):
    import verifier_modele
    verifier_modele.main()          # lève SystemExit si le modèle est refusé


def test_controle_qualite_refuse_un_mauvais_modele(modele_en_production):
    import registre
    import verifier_modele
    from sklearn.dummy import DummyClassifier
    production = registre.version_production()
    modele, fiche = registre.charger()
    # Modèle sans pouvoir prédictif : il doit être refusé par le contrôle de qualité
    naif = DummyClassifier(strategy="prior").fit(np.zeros((10, 1)), [0] * 9 + [1])
    mauvais = registre.enregistrer(naif, {**{k: v for k, v in fiche.items() if k not in ("version", "cree_le", "environnement")},
                                          "mesures_test": {**fiche["mesures_test"], "auc_roc": 0.5, "auc_pr": 0.05}})
    registre.promouvoir(mauvais, "test du contrôle de qualité")
    try:
        with pytest.raises(SystemExit):
            verifier_modele.main()
    finally:
        registre.promouvoir(production, "retour à la version de production après le test")


CLIENT = {"client_pseudo": "c0001", "date_reference": "2026-09-01", "prix_mensuel": 9.99, "anciennete_jours": 400,
          "sessions_30j": 2, "sessions_30_60j": 9, "evolution_sessions": -0.78, "supports_30j": 1,
          "reclamations_30j": 1, "jours_depuis_derniere_session": 20, "code_departement": "44",
          "taille_commune": "grande"}


def test_api_predit_et_historise(modele_en_production):
    import api
    from config import DOSSIER_JOURNAUX
    with TestClient(api.app) as client:
        assert client.get("/sante").json()["statut"] == "ok"
        reponse = client.post("/predire", json={"clients": [CLIENT]})
        assert reponse.status_code == 200
        p = reponse.json()["predictions"][0]["probabilite"]
        assert 0 <= p <= 1
    assert os.path.exists(os.path.join(DOSSIER_JOURNAUX, "predictions.csv"))


def test_api_refuse_les_donnees_invalides(modele_en_production):
    import api
    with TestClient(api.app) as client:
        assert client.post("/predire", json={"clients": [{**CLIENT, "sessions_30j": -1}]}).status_code == 422
        assert client.post("/predire", json={"clients": [{**CLIENT, "taille_commune": "enorme"}]}).status_code == 422


def test_api_exige_la_cle_si_elle_est_definie(modele_en_production, monkeypatch):
    import api
    monkeypatch.setenv("BLOC5_CLE_API", "secret-de-test")
    with TestClient(api.app) as client:
        assert client.post("/predire", json={"clients": [CLIENT]}).status_code == 401
        ok = client.post("/predire", json={"clients": [CLIENT]}, headers={"X-Cle-API": "secret-de-test"})
        assert ok.status_code == 200


def test_psi_detecte_une_derive():
    from surveillance import profil, psi
    rng = np.random.default_rng(1)
    reference = pd.Series(rng.normal(10, 2, 5000))
    assert psi(profil(reference), pd.Series(rng.normal(10, 2, 5000))) < 0.1      # même distribution
    assert psi(profil(reference), pd.Series(rng.normal(14, 2, 5000))) > 0.2      # distribution décalée


def test_cycle_conserve_le_modele_sans_nouvelle_donnee(modele_en_production, monkeypatch):
    import json
    import reentrainement
    import registre
    from config import DOSSIER_RESULTATS
    # On vérifie la règle de décision : sans alerte et sans nouveau mois étiqueté, rien ne change
    monkeypatch.setattr(reentrainement, "surveiller", lambda df: (pd.DataFrame(), [], modele_en_production))
    reentrainement.main()
    assert registre.version_production() == modele_en_production
    bilan = json.load(open(os.path.join(DOSSIER_RESULTATS, "cycle.json"), encoding="utf-8"))
    assert bilan["decision"].startswith("modèle conservé")


def test_cycle_force_compare_puis_decide(modele_en_production):
    import json
    import reentrainement
    import registre
    from config import DOSSIER_RESULTATS
    reentrainement.main(forcer=True)
    bilan = json.load(open(os.path.join(DOSSIER_RESULTATS, "cycle.json"), encoding="utf-8"))
    # Le candidat est toujours comparé au modèle en production sur le même mois de contrôle
    assert "auc_pr_candidat" in bilan["comparaison"] and "auc_pr_production" in bilan["comparaison"]
    comp = bilan["comparaison"]
    if comp["auc_pr_candidat"] >= comp["auc_pr_production"] - reentrainement.MARGE:
        assert registre.version_production() != modele_en_production      # candidat publié
    else:
        assert registre.version_production() == modele_en_production      # modèle actuel conservé
