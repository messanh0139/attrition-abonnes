"""Paramètres communs. Les secrets viennent de variables d'environnement, jamais du code."""
import os
ICI = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(ICI, "certs", "ca.crt").replace("\\", "/")  # « / » : lisible par libpq sous Windows
# Connexion chiffrée et certificat du serveur vérifié (verify-full) ; mot de passe : variable PGPASSWORD
PG_DSN = os.getenv("PG_DSN", f"host=127.0.0.1 port=5433 dbname=attrition user=r_etl sslmode=verify-full sslrootcert={CA_CERT}")
CATALOGUE_URL = os.getenv("CATALOGUE_URL", "http://127.0.0.1:8001")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://127.0.0.1:9000")
S3_CA = os.getenv("S3_CA", CA_CERT)
S3_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET = os.getenv("S3_SECRET_KEY", "")
S3_BUCKET = os.getenv("S3_BUCKET", "bronze")
BRONZE_DIR = os.path.join(os.path.dirname(__file__), "donnees", "bronze")
GRAINE = 42
