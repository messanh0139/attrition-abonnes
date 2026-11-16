# Bloc 5 – Concevoir et déployer un modèle de prédiction de l'attrition

Modèle de prédiction de la résiliation des abonnés à trente jours, de l'analyse exploratoire jusqu'à la mise en production sur Google Cloud.

Ce projet répond au Bloc 5 de la certification *Expert en science des données* (RNCP39586). Il s'appuie sur la table d'analyse construite au [Bloc 1](../bloc1/README.md) : une ligne par client et par date de référence, pseudonymisée, avec ses variables d'usage et d'assistance. L'objectif est double : identifier chaque mois les abonnés les plus susceptibles de partir, pour que le service client puisse les contacter en priorité, et maintenir ce modèle fiable dans le temps.

---

## Démarche

```
Analyse exploratoire ─▶ Variables ─▶ Sélection ─▶ Entraînement ─▶ Optimisation ─▶ Registre
                                                                                     │
       Surveillance ◀── Prédictions historisées ◀── API de prédiction ◀── Mise en production
            │
            └──▶ Réentraînement mensuel, publié seulement s'il n'est pas moins bon
```

Trois choix structurent le projet :

- **un découpage dans le temps** : le modèle apprend sur le passé (novembre 2025 à mai 2026), il est réglé sur juin et juillet, puis évalué une seule fois sur août et septembre. Un découpage au hasard l'aurait évalué sur des mois qu'il avait déjà vus ;
- **une mesure adaptée aux classes rares** : les résiliations ne représentent qu'environ 3 % des lignes. Les modèles sont donc comparés sur l'AUC PR, qui pénalise directement les clients contactés inutilement, plutôt que sur l'exactitude ;
- **une mise en production prudente** : chaque modèle est versionné, contrôlé, puis comparé au modèle en production avant de le remplacer.

## Organisation du dossier

| Élément | Rôle |
| --- | --- |
| `analyse_exploratoire.ipynb` | Analyse exploratoire : qualité, cible, variables, corrélations, stabilité dans le temps |
| `config.py`, `stockage.py` | Paramètres communs ; lecture et écriture locales ou dans Cloud Storage |
| `donnees.py` | Chargement de l'export du Bloc 1, contrôles et découpage dans le temps |
| `variables.py` | Construction des variables dérivées et préparation des données |
| `selection.py` | Sélection des variables par quatre méthodes complémentaires |
| `evaluation.py` | Mesures de performance adaptées aux classes déséquilibrées |
| `entrainement.py` | Comparaison de cinq modèles avec leurs réglages par défaut |
| `optimisation.py` | Recherche des hyperparamètres, mesure du gain, choix du seuil, évaluation finale |
| `registre.py` | Registre des modèles versionnés |
| `verifier_modele.py`, `publier_modele.py` | Contrôle de qualité, comparaison et mise en production |
| `api.py` | API de prédiction (FastAPI), avec historisation des prédictions |
| `dashboard.py` | Tableau de bord Streamlit : prédiction, modèle, surveillance, prédictions servies |
| `surveillance.py` | Dérive des données et performance du modèle mois par mois |
| `reentrainement.py` | Cycle de vie mensuel : collecte des retours, surveillance, réentraînement |
| `Dockerfile` | Image unique pour l'API, le tableau de bord et le cycle mensuel |
| `gcp/` | Scripts de mise en place sur Google Cloud |
| `tests/` | Tests automatisés, dont le parcours cloud avec un stockage simulé |

---

## Installation

Depuis la racine du dépôt, avec l'environnement Python déjà créé pour le Bloc 1 :

```powershell
.venv\Scripts\Activate.ps1
pip install -r bloc5\requirements.txt
cd bloc5
Copy-Item env.ps1.exemple env.ps1      # puis adapter les valeurs
```

Le Bloc 5 lit le dernier export de la table d'analyse, produit au Bloc 1 par `python exporter_gold.py`, dans le dossier `bloc1/exports/`.

## Entraîner le modèle

```powershell
python donnees.py            # contrôle et découpage des données
python selection.py          # sélection des variables
python entrainement.py       # comparaison des modèles
python optimisation.py       # optimisation, évaluation sur le test, enregistrement
python publier_modele.py     # contrôle de qualité et mise en production
```

Chaque étape écrit ses résultats dans le dossier `resultats/` (sélection, comparaison, optimisation, évaluation, importance des variables). Les modèles sont enregistrés dans `modeles/`, une version par dossier (`v001`, `v002`…), avec une fiche décrivant les données, les variables, les réglages et les performances.

## Utiliser le modèle

**L'API de prédiction** :

```powershell
uvicorn api:app --port 8090
```

Sa documentation interactive est disponible sur `http://127.0.0.1:8090/docs`. Le point d'accès `POST /predire` renvoie, pour chaque client, une probabilité de résiliation et un niveau de risque. Chaque prédiction est historisée, pour être comparée plus tard au comportement réel du client.

**Le tableau de bord** :

```powershell
streamlit run dashboard.py
```

Il est disponible sur `http://localhost:8501`, et présente quatre onglets : un formulaire de prédiction, la fiche du modèle en production, la surveillance mois par mois, et l'historique des prédictions servies.

## Surveiller et réentraîner

```powershell
python surveillance.py       # dérive des données (PSI) et performance mensuelle
python reentrainement.py     # cycle de vie complet
```

Le cycle de vie rapproche les prédictions servies de la résiliation observée, contrôle la dérive des données et la performance, puis réentraîne le modèle si une alerte est levée ou si de nouveaux mois sont disponibles. Un nouveau modèle n'est mis en production que s'il n'est pas moins bon que le modèle actuel, à 0,01 d'AUC PR près.

## Tests

```powershell
python -m pytest -q
```

Les 19 tests utilisent un jeu de données synthétique, sans les vraies données. Ils vérifient le découpage dans le temps, l'absence de fuite d'information, l'entraînement, le registre, l'API, le tableau de bord, la détection de dérive et le cycle de vie. Six d'entre eux reproduisent le fonctionnement sur Google Cloud, avec un stockage simulé par un dossier local.

---

## Déploiement sur Google Cloud

Le déploiement est automatisé par la chaîne CI/CD (`.github/workflows/ci.yml`), à chaque modification du dossier `bloc5` :

1. **tests** : les tests automatisés ;
2. **modèle** : entraînement sur les données du stockage, enregistrement dans le registre, contrôle de qualité et mise en production si le modèle n'est pas moins bon ;
3. **déploiement** : publication de l'image dans Artifact Registry, puis déploiement sur Cloud Run de l'API, du tableau de bord et du cycle mensuel.

| Besoin | Service Google Cloud |
| --- | --- |
| Données, registre des modèles, prédictions | Cloud Storage (région Paris, stockage privé et versionné) |
| Images Docker | Artifact Registry |
| API de prédiction | Cloud Run (clé d'accès dans Secret Manager) |
| Tableau de bord | Cloud Run, accès réservé aux comptes autorisés |
| Cycle de vie mensuel | Cloud Run Job, déclenché par Cloud Scheduler |
| Alertes | Cloud Logging et Cloud Monitoring |

La chaîne s'authentifie auprès de Google Cloud par fédération d'identité : aucune clé n'est stockée dans le dépôt. Les étapes « modèle » et « déploiement » ne s'exécutent que lorsque le projet Google Cloud est configuré.

Mise en place, une seule fois :

```powershell
cd gcp
.\initialiser_gcp.ps1 -Projet mon-projet -DepotGitHub compte/depot -Email moi@exemple.fr
.\envoyer_donnees.ps1 -Projet mon-projet
```

Le script affiche ensuite les variables et secrets à déclarer dans GitHub. Après le premier déploiement :

```powershell
.\planifier_cycle_gcp.ps1 -Projet mon-projet      # cycle mensuel
.\ouvrir_tableau_de_bord.ps1 -Projet mon-projet   # accès au tableau de bord
```

---

## Résultats

Le modèle retenu est une **régression logistique** : elle obtient la meilleure AUC PR sur la période de validation, elle est la plus stable, et elle reste interprétable.

| Indicateur | Validation (juin–juillet 2026) | Test (août–septembre 2026) |
| --- | --- | --- |
| AUC ROC | 0,817 | 0,814 |
| AUC PR (hasard : environ 0,03) | 0,246 | 0,280 |
| Départs captés en contactant 10 % des clients | 45 % | 52 % |

En pratique, en contactant les 10 % d'abonnés jugés les plus à risque, le service client toucherait plus de la moitié des futurs départs, contre 10 % en choisissant au hasard. Sur les mois suivant l'apprentissage, la surveillance ne relève aucune dérive des données, et la performance reste stable.
