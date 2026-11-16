# Planifie le cycle de vie du modèle sur GCP : le job cycle-modele est lancé le 2 de chaque mois à 04:00.
# À lancer une fois, après le premier déploiement par la chaîne CI/CD (le job doit exister).
# Usage : .\planifier_cycle_gcp.ps1 -Projet mon-projet-gcp
param([Parameter(Mandatory)] [string]$Projet, [string]$Region = "europe-west9")
$ErrorActionPreference = "Stop"
$compte = "sa-planif@$Projet.iam.gserviceaccount.com"
# Le compte de Cloud Scheduler n'a que le droit de lancer ce job
gcloud run jobs add-iam-policy-binding cycle-modele --region=$Region --member="serviceAccount:$compte" --role=roles/run.invoker
gcloud scheduler jobs create http cycle-mensuel --location=$Region --schedule="0 4 2 * *" --time-zone="Europe/Paris" `
    --uri="https://run.googleapis.com/v2/projects/$Projet/locations/$Region/jobs/cycle-modele:run" `
    --http-method=POST --oauth-service-account-email=$compte
gcloud scheduler jobs describe cycle-mensuel --location=$Region --format="value(schedule, state)"
