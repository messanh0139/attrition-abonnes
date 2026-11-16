"""Rapport de qualité et de profilage, exécuté après chaque chargement."""
import json
import sys

import psycopg2

from config import PG_DSN

CONTROLES = {
    "clients": "SELECT count(*) FROM silver.clients",
    "abonnements": "SELECT count(*) FROM silver.abonnements",
    "evenements": "SELECT count(*) FROM silver.evenements",
    "offres": "SELECT count(*) FROM silver.offres",
    "lignes_gold": "SELECT count(*) FROM gold.variables_clients",
    "evenements_orphelins": """SELECT count(*) FROM silver.evenements e
                               LEFT JOIN silver.clients c USING (client_id) WHERE c.client_id IS NULL""",
    "abonnements_sans_offre": """SELECT count(*) FROM silver.abonnements a
                                 LEFT JOIN silver.offres o USING (plan_code) WHERE o.plan_code IS NULL""",
    "prix_non_positifs": "SELECT count(*) FROM silver.offres WHERE prix_mensuel <= 0",
    "doublons_gold": """SELECT count(*) FROM (SELECT client_pseudo, date_reference FROM gold.variables_clients
                        GROUP BY 1,2 HAVING count(*) > 1) x""",
    "chronologie_incoherente": "SELECT count(*) FROM silver.abonnements WHERE fin < debut",
    "evenements_apres_resiliation": """SELECT count(*) FROM silver.evenements e JOIN silver.abonnements a
                                       USING (client_id) WHERE a.fin IS NOT NULL AND e.event_at::date > a.fin""",
}
PROFIL = {
    "repartition_types": "SELECT type_event, count(*) FROM silver.evenements GROUP BY 1 ORDER BY 2 DESC",
    "repartition_formules": "SELECT plan_code, count(*) FROM silver.abonnements GROUP BY 1 ORDER BY 1",
    "periode_evenements": "SELECT min(event_at)::text, max(event_at)::text FROM silver.evenements",
    "rejets_par_motif": "SELECT source || ' / ' || motif, count(*) FROM meta.rejets WHERE run_id = (SELECT max(run_id) FROM meta.rejets) GROUP BY 1 ORDER BY 2 DESC",
    "cible_gold": """SELECT coalesce(resiliation_30j::text, 'indéterminé'), count(*)
                     FROM gold.variables_clients GROUP BY 1 ORDER BY 1""",
    "valeurs_nulles_gold": """SELECT 'evolution_sessions', count(*) FILTER (WHERE evolution_sessions IS NULL) FROM gold.variables_clients
                              UNION ALL SELECT 'jours_depuis_derniere_session', count(*) FILTER (WHERE jours_depuis_derniere_session IS NULL) FROM gold.variables_clients
                              UNION ALL SELECT 'taille_commune', count(*) FILTER (WHERE taille_commune IS NULL) FROM gold.variables_clients""",
}
BLOQUANTS = ["evenements_orphelins", "abonnements_sans_offre", "prix_non_positifs", "doublons_gold",
             "chronologie_incoherente"]


def rapport(cur):
    r = {"controles": {}, "profil": {}}
    for k, q in CONTROLES.items():
        cur.execute(q); r["controles"][k] = cur.fetchone()[0]
    for k, q in PROFIL.items():
        cur.execute(q); r["profil"][k] = [list(x) for x in cur.fetchall()]
    r["conforme"] = all(r["controles"][k] == 0 for k in BLOQUANTS)
    return r


if __name__ == "__main__":
    with psycopg2.connect(PG_DSN) as cx, cx.cursor() as cur:
        r = rapport(cur)
    sortie = sys.argv[sys.argv.index("--sortie") + 1] if "--sortie" in sys.argv else None
    texte = json.dumps(r, ensure_ascii=False, indent=2, default=str)
    if sortie:
        open(sortie, "w", encoding="utf-8").write(texte)
    print(texte)
    sys.exit(0 if r["conforme"] else 2)
