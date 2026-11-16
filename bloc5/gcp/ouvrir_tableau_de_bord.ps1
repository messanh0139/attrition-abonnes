# Ouvre le tableau de bord, qui n'est pas public : la connexion passe par votre compte Google (IAM).
# Usage : .\ouvrir_tableau_de_bord.ps1 -Projet mon-projet-gcp     puis ouvrir http://localhost:8501
param([Parameter(Mandatory)] [string]$Projet, [string]$Region = "europe-west9")
gcloud run services proxy tableau-de-bord --project=$Projet --region=$Region --port=8501
