# Bilan des exécutions déclenchées par l'ordonnanceur, jour par jour.
# Usage : .\bilan_planification.ps1      Résultat : tableau à l'écran + journaux\bilan_planification.csv
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$sql = @'
SELECT to_char(lance_le AT TIME ZONE 'Europe/Paris', 'YYYY-MM-DD') AS jour,
       count(*) AS executions,
       count(*) FILTER (WHERE statut = 'succes') AS reussies,
       count(*) FILTER (WHERE statut = 'echec') AS echecs,
       to_char(min(lance_le AT TIME ZONE 'Europe/Paris'), 'HH24:MI') AS premiere,
       to_char(max(lance_le AT TIME ZONE 'Europe/Paris'), 'HH24:MI') AS derniere,
       max((volumes->'gold'->>'lignes_gold')::int) AS lignes_gold
FROM meta.etl_runs WHERE declencheur = 'planificateur'
GROUP BY 1 ORDER BY 1
'@
New-Item -ItemType Directory -Force journaux | Out-Null
docker compose exec -T postgres psql -U postgres -d attrition -P pager=off -c $sql
docker compose exec -T postgres psql -U postgres -d attrition -A -F ";" -c $sql | Out-File -Encoding utf8 journaux\bilan_planification.csv
