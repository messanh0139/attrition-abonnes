#!/bin/bash
# Recette des contraintes d'intégrité et des droits par rôle. Chaque test DOIT échouer côté base.
H="-h 127.0.0.1 -d attrition -v ON_ERROR_STOP=0 -q"
essai(){ echo "== $1"; PGPASSWORD=$2 psql $H -U $3 -c "$4" 2>&1 | grep -E "ERROR|FATAL|^ *[0-9]" | head -1; }
essai "Analyste : écriture dans silver"            ana-demo r_analyste "INSERT INTO silver.offres VALUES ('TEST','Test',1,'x',now())"
essai "Analyste : lecture des événements détaillés" ana-demo r_analyste "SELECT count(*) FROM silver.evenements"
essai "Analyste : lecture de la couche gold"        ana-demo r_analyste "SELECT count(*) FROM gold.variables_clients"
essai "Ingestion : lecture de silver"               ing-demo r_ingestion "SELECT count(*) FROM silver.clients"
essai "ETL : suppression d'un événement source"     etl-demo r_etl "DELETE FROM silver.evenements WHERE event_id='E00000001'"
essai "Contrainte : prix négatif"                   etl-demo r_etl "INSERT INTO silver.offres VALUES ('NEG','Neg',-5,'x',now())"
essai "Contrainte : fin avant début"                etl-demo r_etl "INSERT INTO silver.abonnements (client_id,plan_code,debut,fin) VALUES ('C00001','ESS','2026-05-01','2026-04-01')"
essai "Contrainte : client inexistant"              etl-demo r_etl "INSERT INTO silver.evenements VALUES ('EX1','C99999','session',now(),gen_random_uuid())"
essai "Contrainte : type d'événement inconnu"       etl-demo r_etl "INSERT INTO silver.evenements VALUES ('EX2','C00001','sesion',now(),gen_random_uuid())"
essai "Contrainte : doublon client-date en gold"    etl-demo r_etl "INSERT INTO gold.variables_clients SELECT * FROM gold.variables_clients LIMIT 1"
essai "Mauvais mot de passe"                         faux r_etl "SELECT 1"
