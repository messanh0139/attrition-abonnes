# Planifie le cycle du modèle le 2 de chaque mois à 04:00, après l'actualisation nocturne du Bloc 1.
#   .\planifier_cycle.ps1             création de la tâche
#   .\planifier_cycle.ps1 -Supprimer  suppression
param([switch]$Supprimer)
$tache = "AttritionCycleModele"
if ($Supprimer) { schtasks /Delete /TN $tache /F; return }
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " + (Join-Path $PSScriptRoot "lancer_cycle.ps1")
schtasks /Create /F /TN $tache /SC MONTHLY /D 2 /ST 04:00 /TR $action
schtasks /Query /TN $tache
