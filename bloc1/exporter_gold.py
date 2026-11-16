"""Export de la table d'analyse (couche gold) vers un fichier CSV daté.

C'est le point de passage entre le Bloc 1 et le Bloc 5 : le fichier produit sert de jeu
de données figé pour l'entraînement des modèles.
Lecture seule avec le rôle r_analyste, connexion chiffrée par TLS.
Usage : python exporter_gold.py      Résultat : exports/variables_clients_AAAA-MM-JJ.csv
"""
import getpass
import os
from datetime import date

import pandas as pd
import psycopg2

from config import CA_CERT

mot_de_passe = os.getenv("PGPASSWORD_ANALYSTE") or getpass.getpass("Mot de passe du rôle r_analyste : ")
cx = psycopg2.connect(host="127.0.0.1", port=int(os.getenv("PG_PORT", "5433")), dbname="attrition",
                      user="r_analyste", password=mot_de_passe, sslmode="verify-full", sslrootcert=CA_CERT)
df = pd.read_sql("SELECT * FROM gold.variables_clients ORDER BY date_reference, client_pseudo", cx)
cx.close()

os.makedirs("exports", exist_ok=True)
chemin = f"exports/variables_clients_{date.today().isoformat()}.csv"
df.to_csv(chemin, index=False, encoding="utf-8")

print(f"Fichier : {chemin}")
print(f"Lignes : {len(df)} | colonnes : {df.shape[1]}")
print(f"Période : du {df['date_reference'].min()} au {df['date_reference'].max()}")
print(df["resiliation_30j"].value_counts(dropna=False).to_string())
