# Création ou suppression de la tâche planifiée.
#   .\planifier.ps1 -Recette     une exécution par minute (essai de quelques minutes)
#   .\planifier.ps1 -Horaire     une exécution par heure (essai sur plusieurs jours)
#   .\planifier.ps1              production : chaque nuit à 02:00
#   .\planifier.ps1 -Supprimer   suppression de la tâche
# Le chemin du projet ne doit pas contenir d'espace.
param([switch]$Recette, [switch]$Horaire, [switch]$Supprimer)
$tache = "AttritionETL"
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " + (Join-Path $PSScriptRoot "lancer_tache.ps1")
if ($Supprimer) { schtasks /Delete /TN $tache /F; return }
if ($Recette)     { schtasks /Create /F /TN $tache /SC MINUTE /MO 1 /TR $action }
elseif ($Horaire) { schtasks /Create /F /TN $tache /SC HOURLY /MO 1 /TR $action }
else              { schtasks /Create /F /TN $tache /SC DAILY /ST 02:00 /TR $action }
schtasks /Query /TN $tache
