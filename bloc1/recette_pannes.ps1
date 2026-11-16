# Recette de reprise : source indisponible, échec en cours de transaction, puis reprise.
# Prérequis : env.ps1 renseigné, conteneurs démarrés, catalogue servi sur le port 8001.
# Usage : .\recette_pannes.ps1     Résultat : tableau à l'écran + journaux\recette_pannes.csv
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8
. .\env.ps1
function Q($sql) { (docker compose exec -T postgres psql -U postgres -d attrition -tA -c $sql | Out-String).Trim() }
function Etat { [pscustomobject]@{ bronze = Q "SELECT count(*) FROM bronze.reception"; gold = Q "SELECT count(*) FROM gold.variables_clients"; run_gold = Q "SELECT max(run_id) FROM gold.variables_clients" } }
function Lancer { $j = python orchestrer.py --declencheur manuel --sans-api-geo | Out-String; $j | ConvertFrom-Json }

try { Invoke-WebRequest http://127.0.0.1:8001/ -UseBasicParsing -TimeoutSec 5 | Out-Null }
catch { Write-Host "Le catalogue n'est pas servi sur le port 8001 : lancer d'abord le serveur (voir README)."; exit 1 }

$res = @()
# Panne 1 : source du catalogue injoignable
$avant = Etat
$ancienneUrl = $env:CATALOGUE_URL
$env:CATALOGUE_URL = "http://127.0.0.1:8999"
$r = Lancer
$env:CATALOGUE_URL = $ancienneUrl
$apres = Etat
$res += [pscustomobject]@{ Essai = "Source du catalogue injoignable"; Run = $r.run_id; Statut = $r.statut; "Gold inchangée" = $(if ($apres.run_gold -eq $avant.run_gold -and $apres.gold -eq $avant.gold) { "OUI" } else { "NON" }); "Bronze inchangé" = $(if ($apres.bronze -eq $avant.bronze) { "OUI" } else { "NON" }) }

# Panne 2 : échec en cours de transaction (droit d'écriture sur gold retiré au rôle ETL)
$avant = Etat
Q "REVOKE INSERT ON gold.variables_clients FROM r_etl" | Out-Null
$r = Lancer
Q "GRANT INSERT ON gold.variables_clients TO r_etl" | Out-Null
$apres = Etat
$res += [pscustomobject]@{ Essai = "Échec après écriture bronze et silver"; Run = $r.run_id; Statut = $r.statut; "Gold inchangée" = $(if ($apres.run_gold -eq $avant.run_gold -and $apres.gold -eq $avant.gold) { "OUI" } else { "NON" }); "Bronze inchangé" = $(if ($apres.bronze -eq $avant.bronze) { "OUI" } else { "NON" }) }

# Reprise
$r = Lancer
$apres = Etat
$res += [pscustomobject]@{ Essai = "Reprise après rétablissement"; Run = $r.run_id; Statut = $r.statut; "Gold inchangée" = "$($apres.gold) lignes, doublons : $($r.volumes.qualite.doublons_gold)"; "Bronze inchangé" = "-" }

$res | Format-Table -AutoSize -Wrap
New-Item -ItemType Directory -Force journaux | Out-Null
$res | Export-Csv -Path journaux\recette_pannes.csv -NoTypeInformation -Encoding UTF8
Write-Host "Alertes écrites :"; Get-Content journaux\alertes.log -Tail 2
