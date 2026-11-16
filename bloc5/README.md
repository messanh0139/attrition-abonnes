# Bloc 5 – Concevoir et déployer un modèle de prédiction de l'attrition

Ce bloc exploite la table d'analyse du Bloc 1 (`gold.variables_clients`) pour prédire si un abonné
va résilier dans les trente jours, puis met ce modèle en production sur **Google Cloud** : API de
prédiction, tableau de bord Streamlit, chaîne CI/CD, surveillance et réentraînement automatisé.

## Organisation

| Fichier | Rôle |
| --- | --- |
| `analyse_exploratoire.ipynb` | Analyse exploratoire : qualité, cible, variables, corrélations, stabilité |
| `config.py`, `stockage.py` | Paramètres ; stockage local ou Cloud Storage selon `BLOC5_BUCKET` |
| `donnees.py` | Chargement, contrôles, découpage apprentissage / validation / test dans le temps |
| `variables.py` | Variables dérivées et pipeline de préparation |
| `selection.py` | Sélection : tests statistiques, redondances, régression L1, élimination récursive |
| `evaluation.py` | Mesures adaptées aux classes déséquilibrées |
| `entrainement.py` | Comparaison de cinq modèles (dont XGBoost) avec leurs réglages par défaut |
| `optimisation.py` | Hyperparamètres, gain de performance, seuil, test final, enregistrement |
| `registre.py` | Registre des modèles versionnés, partagé dans Cloud Storage |
| `verifier_modele.py`, `publier_modele.py` | Contrôle de qualité, comparaison et mise en production |
| `api.py` | API de prédiction (FastAPI), historisation des prédictions |
| `dashboard.py` | Tableau de bord Streamlit : prédiction, modèle, surveillance, prédictions servies |
| `surveillance.py` | Dérive des données (PSI) et performance mensuelle, alertes |
| `reentrainement.py` | Cycle de vie : retours, surveillance, réentraînement, promotion |
| `Dockerfile` | Image unique : API, tableau de bord et job mensuel sur Cloud Run |
| `gcp/` | Mise en place du projet Google Cloud, envoi des données, planification, accès au tableau de bord |
| `tests/` | 19 tests automatisés, dont 6 sur le parcours cloud avec un seau simulé |

## Exécution sur le poste

```powershell
cd bloc5
pip install -r requirements.txt
python selection.py ; python entrainement.py ; python optimisation.py
python verifier_modele.py
python -m pytest -q
uvicorn api:app --port 8080          # API, documentation sur http://127.0.0.1:8080/docs
streamlit run dashboard.py           # tableau de bord sur http://localhost:8501
python surveillance.py ; python reentrainement.py
```

## Déploiement sur Google Cloud

| Besoin | Service Google Cloud |
| --- | --- |
| Données, registre des modèles, prédictions, résultats | Cloud Storage (seau privé et versionné, région Paris) |
| Images | Artifact Registry |
| API de prédiction | Cloud Run, service `api-attrition` (clé d'API dans Secret Manager) |
| Tableau de bord | Cloud Run, service privé `tableau-de-bord` |
| Cycle de vie mensuel | Cloud Run, job `cycle-modele`, déclenché par Cloud Scheduler |
| CI/CD | GitHub Actions, fédération d'identité (aucune clé dans le dépôt) |
| Supervision | Cloud Logging et Cloud Monitoring (alertes par courriel) |

Mise en place, une seule fois :
```powershell
cd bloc5\gcp
.\initialiser_gcp.ps1 -Projet mon-projet -DepotGitHub compte/depot -Email moi@exemple.fr
.\envoyer_donnees.ps1 -Projet mon-projet
```
Déclarer ensuite dans GitHub les variables et secrets affichés par le script, puis pousser le code
sur la branche `main` : la chaîne CI/CD entraîne, évalue et déploie. Après le premier déploiement :
```powershell
.\planifier_cycle_gcp.ps1 -Projet mon-projet
.\ouvrir_tableau_de_bord.ps1 -Projet mon-projet      # puis http://localhost:8501
```

## Correspondance avec le référentiel

| Compétence | Réalisation |
| --- | --- |
| C5.2.1 Variables | `variables.py`, analyse exploratoire |
| C5.2.2 Sélection | `selection.py` : test statistique, redondance, méthode incorporée L1, élimination récursive |
| C5.2.3 Entraînement | `entrainement.py` : scikit-learn et XGBoost, comparés à une référence naïve |
| C5.2.4 Optimisation | `optimisation.py` : hyperparamètres, validation croisée temporelle, gain mesuré |
| C5.3.1 Sauvegarde | `registre.py` (joblib, versions, fiche), image Docker dans Artifact Registry |
| C5.3.2 CI/CD | `.github/workflows/ci.yml` : tests, enregistrement, évaluation, déploiement sur Cloud Run |
| C5.3.3 Supervision | `surveillance.py`, Cloud Monitoring, tableau de bord |
| C5.3.4 Automatisation | Historisation des prédictions, collecte des données, réentraînement mensuel |
