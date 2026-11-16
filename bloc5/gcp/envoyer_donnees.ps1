# Collecte de nouvelles données : dépose le dernier export du Bloc 1 dans le seau Cloud Storage.
# Le cycle mensuel (job cycle-modele) l'utilise ensuite pour surveiller et réentraîner le modèle.
# Usage : .\envoyer_donnees.ps1 -Projet mon-projet-gcp
param([Parameter(Mandatory)] [string]$Projet)
$ErrorActionPreference = "Stop"
$export = Get-ChildItem "$PSScriptRoot\..\..\bloc1\exports\variables_clients_*.csv" | Sort-Object Name | Select-Object -Last 1
if (-not $export) { throw "Aucun export : lancer d'abord bloc1\exporter_gold.py" }
gcloud storage cp $export.FullName "gs://$Projet-attrition/donnees/$($export.Name)"
gcloud storage ls "gs://$Projet-attrition/donnees/"
