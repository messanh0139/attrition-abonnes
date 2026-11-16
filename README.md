# Projet attrition – KODJO Messanh Yaovi

Projet de certification « Expert en science des données » (RNCP39586), Nantes Ynov Campus.

| Dossier | Contenu |
| --- | --- |
| `bloc1/` | Collecte, transformation et sécurisation des données : chaîne ETL vers PostgreSQL et MinIO, table d'analyse `gold.variables_clients` |
| `bloc5/` | Modèle de prédiction de l'attrition et mise en production sur Google Cloud : sélection des variables, entraînement, API, tableau de bord Streamlit, CI/CD, surveillance et réentraînement |
| `.github/workflows/` | CI/CD du Bloc 5 : tests, entraînement, évaluation et déploiement sur Cloud Run |

Le passage d'un bloc à l'autre se fait par `bloc1/exporter_gold.py`, qui exporte la table
d'analyse (lecture seule, rôle analyste, connexion chiffrée) dans un fichier CSV daté.

Les secrets, certificats, données et sauvegardes ne sont jamais versionnés (voir `.gitignore`).
