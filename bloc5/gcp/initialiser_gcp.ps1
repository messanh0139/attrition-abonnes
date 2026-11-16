# Mise en place du projet Google Cloud pour le Bloc 5 (à lancer une seule fois).
# Usage : .\initialiser_gcp.ps1 -Projet mon-projet-gcp -DepotGitHub compte/nom-du-depot -Email moi@exemple.fr
# Prérequis : gcloud installé, « gcloud auth login » effectué, facturation activée sur le projet.
param(
    [Parameter(Mandatory)] [string]$Projet,
    [Parameter(Mandatory)] [string]$DepotGitHub,
    [string]$Email = "",
    [string]$Region = "europe-west9"        # Paris : données hébergées dans l'Union européenne
)
$ErrorActionPreference = "Stop"
$Seau = "$Projet-attrition"
function Compte($nom) { "sa-$nom@$Projet.iam.gserviceaccount.com" }

Write-Host "1. Projet et services"
gcloud config set project $Projet
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com `
    secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com `
    monitoring.googleapis.com logging.googleapis.com storage.googleapis.com

Write-Host "2. Seau Cloud Storage privé et versionné (données, registre des modèles, prédictions)"
gcloud storage buckets create "gs://$Seau" --location=$Region --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://$Seau" --versioning

Write-Host "3. Dépôt d'images Artifact Registry"
gcloud artifacts repositories create attrition --repository-format=docker --location=$Region `
    --description="Images du modèle d'attrition"

Write-Host "4. Comptes de service, chacun avec les seuls droits nécessaires"
foreach ($nom in "api", "cycle", "tableau", "planif", "deploiement") {
    gcloud iam service-accounts create "sa-$nom" --display-name="Attrition - $nom"
}
# API : lit le registre, écrit les prédictions. Tableau de bord : lecture seule. Cycle et chaîne CI/CD : gestion du seau.
gcloud storage buckets add-iam-policy-binding "gs://$Seau" --member="serviceAccount:$(Compte api)" --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding "gs://$Seau" --member="serviceAccount:$(Compte api)" --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding "gs://$Seau" --member="serviceAccount:$(Compte tableau)" --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding "gs://$Seau" --member="serviceAccount:$(Compte cycle)" --role=roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding "gs://$Seau" --member="serviceAccount:$(Compte deploiement)" --role=roles/storage.objectAdmin
foreach ($role in "roles/run.admin", "roles/artifactregistry.writer", "roles/iam.serviceAccountUser", "roles/secretmanager.viewer") {
    gcloud projects add-iam-policy-binding $Projet --member="serviceAccount:$(Compte deploiement)" --role=$role --condition=None
}

Write-Host "5. Clé de l'API dans Secret Manager (jamais dans le code ni dans le dépôt)"
$fichier = New-TemporaryFile
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ }) | Set-Content -NoNewline $fichier
gcloud secrets create cle-api --replication-policy=user-managed --locations=$Region --data-file=$fichier
Remove-Item $fichier
foreach ($nom in "api", "tableau") {
    gcloud secrets add-iam-policy-binding cle-api --member="serviceAccount:$(Compte $nom)" --role=roles/secretmanager.secretAccessor
}

Write-Host "6. Fédération d'identité : GitHub Actions déploie sans clé stockée dans le dépôt"
$numero = gcloud projects describe $Projet --format="value(projectNumber)"
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github --location=global --workload-identity-pool=github `
    --issuer-uri="https://token.actions.githubusercontent.com" `
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" `
    --attribute-condition="assertion.repository=='$DepotGitHub'"
gcloud iam service-accounts add-iam-policy-binding (Compte deploiement) --role=roles/iam.workloadIdentityUser `
    --member="principalSet://iam.googleapis.com/projects/$numero/locations/global/workloadIdentityPools/github/attribute.repository/$DepotGitHub"

Write-Host "7. Supervision : métrique sur les alertes du modèle et politique d'alerte"
gcloud logging metrics create alertes-modele --description="Alertes de dérive ou de performance du modèle" `
    --log-filter=jsonPayload.type=alerte_modele
if ($Email) {
    $canal = gcloud beta monitoring channels create --display-name="Alertes attrition" --type=email `
        --channel-labels=email_address=$Email --format="value(name)"
    $politique = (Get-Content "$PSScriptRoot\politique_alerte.json" -Raw) -replace "__CANAL__", $canal
    $chemin = New-TemporaryFile
    Set-Content $chemin $politique -Encoding utf8
    gcloud alpha monitoring policies create --policy-from-file=$chemin
    Remove-Item $chemin
}

Write-Host ""
Write-Host "Terminé. À déclarer dans le dépôt GitHub (Settings > Secrets and variables > Actions) :"
Write-Host "  variable GCP_PROJET              = $Projet"
Write-Host "  variable GCP_REGION              = $Region"
Write-Host "  variable GCP_SEAU                = $Seau"
Write-Host "  secret   GCP_FOURNISSEUR_WIF     = projects/$numero/locations/global/workloadIdentityPools/github/providers/github"
Write-Host "  secret   GCP_COMPTE_DEPLOIEMENT  = $(Compte deploiement)"
