"""Processus ETL : bronze (fichiers bruts) -> silver (relationnel validé) -> gold (variables).

Chaque étape est rejouable : un fichier déjà intégré n'est pas relu, les tables silver
sont alimentées en ON CONFLICT DO NOTHING, la couche gold est réécrite par date de référence.
"""
import glob
import json
import os
import uuid
from datetime import date, datetime

import pandas as pd
from psycopg2.extras import Json, execute_values

from config import BRONZE_DIR

TYPES_AUTORISES = {"session", "support", "reclamation", "resiliation"}


# ---------------------------------------------------------------- EXTRACTION
def extraire_bronze(cur, run_id):
    """Copie en base chaque fichier brut non encore ingéré. Retourne le nombre de lignes."""
    fichiers = sorted(glob.glob(f"{BRONZE_DIR}/*.jsonl") + glob.glob(f"{BRONZE_DIR}/evenements/*.jsonl")
                      + glob.glob(f"{BRONZE_DIR}/catalogue_*.json") + glob.glob(f"{BRONZE_DIR}/api_geo_*.json"))
    total, nouveaux = 0, 0
    for chemin in fichiers:
        nom = os.path.relpath(chemin, BRONZE_DIR).replace(os.sep, "/")  # séparateur Windows normalisé
        taille = os.path.getsize(chemin)
        cur.execute("SELECT taille FROM meta.fichiers_ingeres WHERE fichier = %s", (nom,))
        deja = cur.fetchone()
        if deja and deja[0] == taille:      # fichier déjà intégré : il n'est pas relu
            continue
        source = ("evenements" if nom.startswith("evenements/") else
                  "catalogue" if nom.startswith("catalogue_") else
                  "api_geo" if nom.startswith("api_geo_") else nom.split(".")[0])
        lot = str(uuid.uuid4())
        with open(chemin, encoding="utf-8") as f:
            lignes = [json.loads(l) for l in f] if chemin.endswith(".jsonl") else [json.load(f)]
        execute_values(cur, "INSERT INTO bronze.reception (source, fichier, lot_id, contenu) VALUES %s",
                       [(source, nom, lot, Json(x)) for x in lignes], page_size=5000)
        cur.execute("""INSERT INTO meta.fichiers_ingeres (fichier, taille, lot_id, lignes, run_id)
                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT (fichier) DO UPDATE
                       SET taille = EXCLUDED.taille, lot_id = EXCLUDED.lot_id, lignes = EXCLUDED.lignes,
                           run_id = EXCLUDED.run_id, ingere_le = now()""",
                    (nom, taille, lot, len(lignes), run_id))
        total += len(lignes)
        nouveaux += 1
    return {"fichiers_nouveaux": nouveaux, "lignes_bronze": total}


def lire_bronze(cur, source):
    cur.execute("""SELECT DISTINCT ON (contenu) contenu, lot_id FROM bronze.reception
                   WHERE source = %s""", (source,))
    return cur.fetchall()


# ------------------------------------------------------------- TRANSFORMATION
def rejeter(cur, run_id, source, lignes):
    if lignes:
        execute_values(cur, "INSERT INTO meta.rejets (run_id, source, motif, contenu) VALUES %s",
                       [(run_id, source, motif, Json(c)) for motif, c in lignes])


def normaliser_communes(series):
    """Formatage : espaces superflus retirés, casse harmonisée sur la graphie la plus fréquente."""
    propre = series.str.split().str.join(" ")
    cle = propre.str.casefold()
    canon = propre.groupby(cle).agg(lambda s: s[s != s.str.upper()].mode().iat[0]
                                    if (s != s.str.upper()).any() else s.mode().iat[0])
    return cle.map(canon)


def charger_silver(cur, run_id):
    vol = {}
    # Offres : le lot de catalogue le plus récent
    cur.execute("""SELECT contenu FROM bronze.reception WHERE source = 'catalogue'
                   ORDER BY recu_le DESC, reception_id DESC LIMIT 1""")
    lot = cur.fetchone()[0]
    ok = [o for o in lot["offres"] if o["prix_mensuel"] is not None]
    rejeter(cur, run_id, "catalogue", [("prix illisible", o) for o in lot["offres"] if o["prix_mensuel"] is None])
    execute_values(cur, """INSERT INTO silver.offres (plan_code, nom, prix_mensuel, url_source, collecte_le)
                           VALUES %s ON CONFLICT (plan_code) DO UPDATE SET prix_mensuel = EXCLUDED.prix_mensuel,
                           nom = EXCLUDED.nom, collecte_le = EXCLUDED.collecte_le""",
                   [(o["plan_code"], o["nom"], o["prix_mensuel"], o["url_source"], lot["collecte_le"]) for o in ok])
    vol["offres"] = len(ok)

    # Communes (API Géo) si une réponse a été collectée
    cur.execute("""SELECT contenu FROM bronze.reception WHERE source = 'api_geo'
                   ORDER BY recu_le DESC LIMIT 1""")
    geo = cur.fetchone()
    correspondance = {}
    if geo:
        for nom_saisi, rep in geo[0]["reponses"].items():
            if rep:
                c = rep[0]
                cur.execute("""INSERT INTO silver.communes VALUES (%s,%s,%s,%s,%s)
                               ON CONFLICT (code_insee) DO UPDATE SET population = EXCLUDED.population,
                               collecte_le = EXCLUDED.collecte_le""",
                            (c["code"], c["nom"], c["codeDepartement"], c.get("population"),
                             geo[0]["collecte_le"]))
                correspondance[nom_saisi] = c["code"]

    # Clients
    df = pd.DataFrame([r[0] for r in lire_bronze(cur, "clients")])
    df["commune_norm"] = normaliser_communes(df["commune_declaree"])
    vol["communes_corrigees"] = int((df["commune_norm"] != df["commune_declaree"]).sum())
    df["code_insee"] = df["commune_norm"].map(correspondance)
    execute_values(cur, """INSERT INTO silver.clients VALUES %s ON CONFLICT (client_id) DO UPDATE
                           SET code_insee = EXCLUDED.code_insee, commune_norm = EXCLUDED.commune_norm""",
                   [(r.client_id, r.created_at, r.commune_norm,
                     None if pd.isna(r.code_insee) else r.code_insee, r.consentement)
                    for r in df.itertuples()], page_size=5000)
    vol["clients"] = len(df)
    clients_connus = set(df["client_id"])

    # Abonnements : règle de chronologie
    ab = pd.DataFrame([r[0] for r in lire_bronze(cur, "abonnements")])
    incoherents = ab[ab["fin"].notna() & (ab["fin"] < ab["debut"])]
    rejeter(cur, run_id, "abonnements", [("fin antérieure au début", r) for r in incoherents.to_dict("records")])
    ab = ab.drop(incoherents.index)
    execute_values(cur, """INSERT INTO silver.abonnements (client_id, plan_code, debut, fin) VALUES %s
                           ON CONFLICT (client_id, debut) DO UPDATE SET fin = EXCLUDED.fin""",
                   [(r.client_id, r.plan_code, r.debut, r.fin if isinstance(r.fin, str) else None)
                    for r in ab.itertuples()], page_size=5000)
    vol["abonnements"], vol["abonnements_rejetes"] = len(ab), len(incoherents)

    # Événements : doublons, client inconnu, type, date
    brut = lire_bronze(cur, "evenements")
    cur.execute("SELECT count(*) FROM bronze.reception WHERE source = 'evenements'")
    vol["evenements_recus"] = cur.fetchone()[0]
    vol["evenements_doublons_exacts"] = vol["evenements_recus"] - len(brut)
    valides, rejets, vus = [], [], set()
    for contenu, lot_id in brut:
        try:
            d = datetime.fromisoformat(contenu["event_at"])
        except ValueError:
            rejets.append(("date invalide", contenu)); continue
        if d.date() > date.today():
            rejets.append(("date future", contenu))
        elif contenu["client_id"] not in clients_connus:
            rejets.append(("client inconnu", contenu))
        elif contenu["type_event"] not in TYPES_AUTORISES:
            rejets.append(("type non autorisé", contenu))
        elif contenu["event_id"] in vus:
            rejets.append(("identifiant déjà reçu", contenu))
        else:
            vus.add(contenu["event_id"])
            valides.append((contenu["event_id"], contenu["client_id"], contenu["type_event"], d, lot_id))
    rejeter(cur, run_id, "evenements", rejets)
    execute_values(cur, "INSERT INTO silver.evenements VALUES %s ON CONFLICT (event_id) DO NOTHING",
                   valides, page_size=10000)
    vol["evenements_valides"], vol["evenements_rejetes"] = len(valides), len(rejets)

    # Couverture : dernière date pour laquelle la source d'événements est complète.
    # Seuls les lots de fichiers complets comptent : les événements reçus au fil de l'eau par l'API
    # de collecte sont partiels par nature, et quelques événements récents ne prouvent pas que
    # toute la période est couverte.
    cur.execute("""SELECT max(e.event_at)::date FROM silver.evenements e
                   WHERE e.lot_id IN (SELECT lot_id FROM bronze.reception
                                      WHERE source = 'evenements' AND fichier <> 'api_collecte')""")
    couverture = cur.fetchone()[0]
    if couverture is None:
        raise RuntimeError("aucun événement valide en silver : vérifier la reconnaissance des fichiers bronze")
    cur.execute("""INSERT INTO meta.couverture (source, couvert_jusqu_a) VALUES ('evenements', %s)
                   ON CONFLICT (source) DO UPDATE SET couvert_jusqu_a = EXCLUDED.couvert_jusqu_a, maj_le = now()""",
                (couverture,))
    return vol


# --------------------------------------------------------------- CHARGEMENT GOLD
SQL_GOLD = """
WITH actifs AS (
    SELECT a.client_id, a.plan_code, a.debut, a.fin, o.prix_mensuel, c.code_insee
    FROM silver.abonnements a
    JOIN silver.offres  o USING (plan_code)
    JOIN silver.clients c USING (client_id)
    WHERE a.debut < %(d)s AND (a.fin IS NULL OR a.fin >= %(d)s)
),
agg AS (
    SELECT e.client_id,
           count(*) FILTER (WHERE type_event = 'session'     AND event_at >= %(d)s::date - 30) AS s30,
           count(*) FILTER (WHERE type_event = 'session'     AND event_at <  %(d)s::date - 30) AS s3060,
           count(*) FILTER (WHERE type_event = 'support'     AND event_at >= %(d)s::date - 30) AS sup30,
           count(*) FILTER (WHERE type_event = 'reclamation' AND event_at >= %(d)s::date - 30) AS rec30,
           max(event_at) FILTER (WHERE type_event = 'session') AS derniere
    FROM silver.evenements e
    WHERE event_at >= %(d)s::date - 60 AND event_at < %(d)s
    GROUP BY e.client_id
)
INSERT INTO gold.variables_clients
SELECT ps.client_pseudo,
       %(d)s, a.plan_code, a.prix_mensuel, %(d)s::date - a.debut,
       coalesce(g.s30, 0), coalesce(g.s3060, 0),
       CASE WHEN coalesce(g.s3060, 0) > 0 THEN round((coalesce(g.s30,0) - g.s3060)::numeric / g.s3060, 2) END,
       coalesce(g.sup30, 0), coalesce(g.rec30, 0),
       %(d)s::date - g.derniere::date,
       cm.code_departement,
       CASE WHEN cm.population IS NULL THEN NULL WHEN cm.population < 20000 THEN 'petite'
            WHEN cm.population < 100000 THEN 'moyenne' ELSE 'grande' END,
       CASE WHEN a.fin IS NOT NULL AND a.fin < %(d)s::date + 30 THEN 1
            WHEN %(d)s::date + 29 <= (SELECT couvert_jusqu_a FROM meta.couverture WHERE source = 'evenements') THEN 0
            ELSE NULL END,
       now(), %(run)s
FROM actifs a
LEFT JOIN agg g USING (client_id)
LEFT JOIN silver.communes cm USING (code_insee)
JOIN silver.pseudonymes ps ON ps.client_id = a.client_id
"""


def charger_gold(cur, run_id, dates):
    # Un pseudonyme aléatoire est attribué une fois pour toutes à chaque nouveau client
    cur.execute("""INSERT INTO silver.pseudonymes (client_id)
                   SELECT client_id FROM silver.clients ON CONFLICT (client_id) DO NOTHING""")
    lignes = 0
    for d in dates:
        cur.execute("DELETE FROM gold.variables_clients WHERE date_reference = %s", (d,))
        cur.execute(SQL_GOLD, {"d": d, "run": run_id})
        lignes += cur.rowcount
    return {"lignes_gold": lignes, "dates_reference": len(dates)}
