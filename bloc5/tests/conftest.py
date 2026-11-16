"""Préparation des tests : un petit jeu de données synthétique, de même forme que l'export du Bloc 1.

Les tests n'utilisent jamais les vraies données (elles ne quittent pas le poste) : ils peuvent
donc tourner partout, y compris dans l'intégration continue. Tous les fichiers produits pendant
les tests sont écrits dans un dossier temporaire.
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

DOSSIER_TEST = tempfile.mkdtemp(prefix="bloc5_tests_")
os.environ["BLOC5_TRAVAIL"] = DOSSIER_TEST
os.environ["BLOC5_DONNEES"] = os.path.join(DOSSIER_TEST, "variables_clients_test.csv")
os.environ["BLOC5_ITERATIONS"] = "3"          # recherche d'hyperparamètres réduite pour aller vite
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def jeu_synthetique(nb_clients=600, graine=0):
    """Clients suivis sur 11 mois ; la résiliation dépend de l'usage et des réclamations."""
    rng = np.random.default_rng(graine)
    lignes = []
    offres = [("ESS", 9.99), ("CONF", 14.99), ("PREM", 19.99)]
    for date in pd.date_range("2025-11-01", "2026-09-01", freq="MS"):
        for i in range(nb_clients):
            code, prix = offres[i % 3]
            s60 = int(rng.poisson(10))
            s30 = int(rng.poisson(10 if rng.random() > 0.15 else 3))
            sup, rec = int(rng.poisson(0.3)), int(rng.poisson(0.1))
            score = -4.0 + 2.5 * (s30 < 4) + 1.2 * sup + 1.8 * rec
            lignes.append({
                "client_pseudo": f"c{i:04d}", "date_reference": date, "plan_code": code, "prix_mensuel": prix,
                "anciennete_jours": int(rng.integers(1, 900)), "sessions_30j": s30, "sessions_30_60j": s60,
                "evolution_sessions": None if s60 == 0 else round((s30 - s60) / s60, 2),
                "supports_30j": sup, "reclamations_30j": rec,
                "jours_depuis_derniere_session": None if s30 + s60 == 0 else int(rng.integers(1, 30)),
                "code_departement": ["44", "35", "49"][i % 3], "taille_commune": ["petite", "moyenne", "grande"][i % 3],
                "resiliation_30j": int(rng.random() < 1 / (1 + np.exp(-score))),
                "calcule_le": "2026-10-01", "run_id": 1,
            })
    return pd.DataFrame(lignes)


jeu_synthetique().to_csv(os.environ["BLOC5_DONNEES"], index=False)
