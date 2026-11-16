"""Recette des droits par rôle et des contraintes d'intégrité.

Les connexions passent par le port publié de PostgreSQL, comme celles d'une application réelle :
l'authentification par mot de passe s'applique donc à chaque essai.
Usage : python tests_securite.py      Résultat : tableau à l'écran + journaux/recette_securite.csv
"""
import csv
import os

import psycopg2

from config import CA_CERT

HOTE = os.getenv("PG_HOTE", "127.0.0.1")
PORT = os.getenv("PG_PORT", "5433")
MDP = {"r_etl": "etl-demo", "r_analyste": "ana-demo", "r_ingestion": "ing-demo"}

ESSAIS = [
    ("Analyste : écriture dans silver", "r_analyste", None,
     "INSERT INTO silver.offres VALUES ('TEST','Test',1,'x',now())", "refus"),
    ("Analyste : lecture des événements", "r_analyste", None, "SELECT count(*) FROM silver.evenements", "refus"),
    ("Analyste : lecture de la couche gold", "r_analyste", None, "SELECT count(*) FROM gold.variables_clients", "autorisé"),
    ("Analyste : lecture des pseudonymes", "r_analyste", None, "SELECT count(*) FROM silver.pseudonymes", "refus"),
    ("Ingestion : lecture de silver", "r_ingestion", None, "SELECT count(*) FROM silver.clients", "refus"),
    ("ETL : suppression d'un événement", "r_etl", None, "DELETE FROM silver.evenements WHERE event_id='E00000001'", "refus"),
    ("Contrainte : prix négatif", "r_etl", None, "INSERT INTO silver.offres VALUES ('NEG','Neg',-5,'x',now())", "refus"),
    ("Contrainte : fin avant début", "r_etl", None,
     "INSERT INTO silver.abonnements (client_id,plan_code,debut,fin) VALUES ('C00001','ESS','2026-05-01','2026-04-01')", "refus"),
    ("Contrainte : client inexistant", "r_etl", None,
     "INSERT INTO silver.evenements VALUES ('EX1','C99999','session',now(),gen_random_uuid())", "refus"),
    ("Contrainte : type d'événement inconnu", "r_etl", None,
     "INSERT INTO silver.evenements VALUES ('EX2','C00001','sesion',now(),gen_random_uuid())", "refus"),
    ("Contrainte : doublon client-date gold", "r_etl", None,
     "INSERT INTO gold.variables_clients SELECT * FROM gold.variables_clients LIMIT 1", "refus"),
    ("Connexion : mauvais mot de passe", "r_etl", "faux", "SELECT 1", "refus"),
    ("Connexion sans chiffrement TLS", "r_etl", None, "SELECT 1", "refus", "disable"),
    ("Connexion chiffrée : protocole utilisé", "r_etl", None, "SELECT version FROM pg_stat_ssl WHERE pid = pg_backend_pid()", "autorisé"),
]


def essai(role, mdp, sql, sslmode="verify-full"):
    """Retourne (refusé, réponse). Aucun essai ne modifie la base : tout est annulé."""
    try:
        cx = psycopg2.connect(host=HOTE, port=PORT, dbname="attrition", user=role,
                              password=mdp or MDP[role], connect_timeout=5,
                              sslmode=sslmode, sslrootcert=CA_CERT)
    except psycopg2.OperationalError as exc:
        return True, str(exc).strip().splitlines()[-1]
    try:
        with cx.cursor() as cur:
            cur.execute(sql)
            reponse = str(cur.fetchone()[0]) if cur.description else "exécuté"
        return False, reponse
    except psycopg2.Error as exc:
        return True, exc.pgerror.strip().splitlines()[0] if exc.pgerror else str(exc)
    finally:
        cx.rollback()
        cx.close()


def main():
    lignes = []
    for titre, role, mdp, sql, attendu, *mode in ESSAIS:
        refuse, reponse = essai(role, mdp, sql, *(mode or ["verify-full"]))
        if "Connection refused" in reponse or "server running" in reponse or "timeout expired" in reponse:
            # Serveur injoignable : l'essai n'a pas pu avoir lieu, ce n'est pas un refus conforme
            lignes.append({"Essai": titre, "Attendu": attendu, "Conforme": "NON", "Reponse": "Serveur injoignable : essai impossible"})
            continue
        conforme = refuse if attendu == "refus" else not refuse
        lignes.append({"Essai": titre, "Attendu": attendu, "Conforme": "OUI" if conforme else "NON",
                       "Reponse": reponse[:90]})
    largeur = max(len(l["Essai"]) for l in lignes)
    for l in lignes:
        print(f"{l['Essai']:<{largeur}}  {l['Attendu']:<8}  {l['Conforme']:<3}  {l['Reponse']}")
    os.makedirs("journaux", exist_ok=True)
    with open("journaux/recette_securite.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0]), delimiter=";")
        w.writeheader()
        w.writerows(lignes)
    ko = sum(l["Conforme"] == "NON" for l in lignes)
    print(f"\n{len(lignes)} essais, {ko} non conforme(s).")


if __name__ == "__main__":
    main()
