# Point d'entrée appelé par le Planificateur de tâches Windows. Les secrets sont lus dans env.ps1.
Set-Location $PSScriptRoot
. .\env.ps1

# Services Docker démarrés en mode développement (après un redémarrage du poste, ils peuvent être arrêtés)
docker compose --profile minio --profile acces up -d *> $null
Start-Sleep -Seconds 10

# Environnement Python du projet : à la racine (Projet_Attrition_KODJO\.venv), sinon dans bloc1\.venv
$python = @("..\.venv\Scripts\python.exe", ".\.venv\Scripts\python.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    Add-Content journaux\planificateur.log "$(Get-Date -Format s) ÉCHEC environnement Python introuvable"
    exit 1
}

# Le crawler lit le catalogue local : on le démarre s'il ne répond pas (exécutions sur plusieurs jours)
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:8001/ | Out-Null }
catch {
    Start-Process $python -ArgumentList "-m", "http.server", "8001", "--bind", "127.0.0.1" `
        -WorkingDirectory "$PSScriptRoot\site_catalogue" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

& $python orchestrer.py --declencheur planificateur --sans-api-geo *>> journaux\planificateur.log
