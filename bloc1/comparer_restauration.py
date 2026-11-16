"""Compare le contenu de la base d'origine et de la base restaurée, ligne par ligne.

Chaque table est lue dans les deux bases, triée sur sa clé primaire, puis les lignes sont comparées
une à une, toutes colonnes confondues. Le résultat indique, pour chaque table, le nombre de lignes
lues et le nombre de lignes différentes ou manquantes.
Usage : python comparer_restauration.py      Résultat : tableau à l'écran + journaux/comparaison_restauration.csv
"""
import csv
import itertools
import os

import psycopg2

from config import PG_DSN

TABLES = [
    ("silver.communes", "code_insee"),
    ("silver.offres", "plan_code"),
    ("silver.clients", "client_id"),
    ("silver.abonnements", "abonnement_id"),
    ("silver.evenements", "event_id"),
    ("silver.pseudonymes", "client_id"),
    ("gold.variables_clients", "client_pseudo, date_reference"),
]


def lignes(cx, table, cle):
    cur = cx.cursor(name=f"lecture_{table.replace('.', '_')}")   # lecture progressive, sans tout charger
    cur.itersize = 20000
    cur.execute(f"SELECT * FROM {table} ORDER BY {cle}")
    yield from cur
    cur.close()


def main():
    origine = psycopg2.connect(PG_DSN)
    restauree = psycopg2.connect(PG_DSN, dbname="attrition_restau")
    resultats = []
    for table, cle in TABLES:
        lues = differentes = 0
        for a, b in itertools.zip_longest(lignes(origine, table, cle), lignes(restauree, table, cle)):
            lues += 1
            differentes += a != b
        resultats.append({"Table": table, "Lignes comparées": lues, "Lignes différentes": differentes,
                          "Contenu identique": "OUI" if differentes == 0 else "NON"})
    for r in resultats:
        print(f"{r['Table']:<26} {r['Lignes comparées']:>8} lignes   {r['Lignes différentes']} différente(s)   {r['Contenu identique']}")
    os.makedirs("journaux", exist_ok=True)
    with open("journaux/comparaison_restauration.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(resultats[0]), delimiter=";")
        w.writeheader(); w.writerows(resultats)
    total = sum(r["Lignes comparées"] for r in resultats)
    ecarts = sum(r["Lignes différentes"] for r in resultats)
    print(f"\n{total} lignes comparées, {ecarts} différence(s).")


if __name__ == "__main__":
    main()
