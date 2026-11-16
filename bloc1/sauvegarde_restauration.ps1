# Sauvegarde chiffrée, restauration sur une base distincte, puis comparaison du contenu ligne par ligne.
# Usage : .\sauvegarde_restauration.ps1
# Résultats : sauvegardes\*.dump.chiffre, journaux\restauration.csv, journaux\comparaison_restauration.csv
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8
. .\env.ps1
function Q($base, $sql) { (docker compose exec -T postgres psql -U postgres -d $base -tA -c $sql | Out-String).Trim() }

$horodatage = Get-Date -Format "yyyyMMdd_HHmm"
New-Item -ItemType Directory -Force sauvegardes, journaux | Out-Null

Write-Host "1. Sauvegarde de la base"
docker compose exec -T postgres pg_dump -U postgres -Fc -d attrition -f /tmp/attrition.dump
docker compose cp postgres:/tmp/attrition.dump "sauvegardes/attrition_$horodatage.dump" | Out-Null

Write-Host "2. Chiffrement de la sauvegarde"
python chiffrer_sauvegarde.py "sauvegardes/attrition_$horodatage.dump"

Write-Host "3. Restauration sur une base distincte"
docker compose exec -T postgres dropdb -U postgres --if-exists attrition_restau
docker compose exec -T postgres createdb -U postgres attrition_restau
docker compose exec -T postgres pg_restore -U postgres -d attrition_restau /tmp/attrition.dump
docker compose exec -T postgres rm -f /tmp/attrition.dump

Write-Host "4. Comparaison des volumes"
$tables = "silver.clients", "silver.abonnements", "silver.evenements", "silver.offres", "gold.variables_clients"
$lignes = foreach ($t in $tables) {
    $a = Q attrition "SELECT count(*) FROM $t"
    $b = Q attrition_restau "SELECT count(*) FROM $t"
    [pscustomobject]@{ Controle = "Lignes $t"; Origine = $a; Restauree = $b; Identique = $(if ($a -eq $b) { "OUI" } else { "NON" }) }
}
$lignes | Format-Table -AutoSize
$lignes | Export-Csv -Path journaux\restauration.csv -NoTypeInformation -Encoding UTF8

Write-Host "5. Comparaison du contenu, ligne par ligne"
python comparer_restauration.py
