-- Rôles applicatifs selon le principe du moindre privilège.
-- Les mots de passe sont fournis par variables d'environnement au déploiement (\set via psql -v).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'r_ingestion') THEN CREATE ROLE r_ingestion LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'r_etl')       THEN CREATE ROLE r_etl LOGIN;       END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'r_analyste')  THEN CREATE ROLE r_analyste LOGIN;  END IF;
END $$;

REVOKE ALL ON SCHEMA bronze, silver, gold, meta FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Ingestion : écrit uniquement en bronze et dans le journal des rejets
GRANT USAGE ON SCHEMA bronze, meta TO r_ingestion;
GRANT INSERT ON bronze.reception, meta.rejets TO r_ingestion;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA bronze, meta TO r_ingestion;

-- ETL : lit bronze, alimente silver et gold, journalise
GRANT USAGE ON SCHEMA bronze, silver, gold, meta TO r_etl;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA bronze TO r_etl;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA bronze TO r_etl;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA silver, gold, meta TO r_etl;
GRANT DELETE ON gold.variables_clients TO r_etl;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA silver, meta TO r_etl;

-- Analyste : lecture seule de la couche gold, pseudonymisée
GRANT USAGE ON SCHEMA gold TO r_analyste;
GRANT SELECT ON gold.variables_clients TO r_analyste;
