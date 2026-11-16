# Cycle mensuel du modèle : nouvel export du Bloc 1, puis surveillance et réentraînement éventuel.
# Lancé par la tâche planifiée (planifier_cycle.ps1). Le mot de passe du rôle analyste est lu
# dans env.ps1 (variable PGPASSWORD_ANALYSTE), jamais écrit dans ce script.
Set-Location $PSScriptRoot
. .\env.ps1
Set-Location ..\bloc1
python exporter_gold.py
Set-Location ..\bloc5
python reentrainement.py
# Si l'API tourne, elle recharge la version de production (éventuellement nouvelle)
try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/recharger -Headers @{ "X-Cle-API" = $env:BLOC5_CLE_API } | Out-Null } catch { }
