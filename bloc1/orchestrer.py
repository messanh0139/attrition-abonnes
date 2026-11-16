"""Orchestration de la chaîne complète, appelée chaque nuit à 02:00 (cron sous Linux, Planificateur de tâches sous Windows).

Ordre : collecte catalogue -> collecte API Géo -> bronze -> silver -> gold -> contrôle qualité.
Bronze, silver et gold sont écrits dans UNE transaction : si une étape ou le contrôle qualité
échoue, rien n'est validé et la couche gold reste dans son état précédent.
Chaque exécution est tracée dans meta.etl_runs et dans journaux/orchestration.log.
Un échec écrit une alerte dans journaux/alertes.log et rend un code de sortie non nul.
"""
import argparse
import json
import logging
import os
import sys
import traceback
from datetime import date

import psycopg2
from psycopg2.extras import Json

import api_geo
import crawl_scrape
import etl
import qualite
from config import PG_DSN

ICI = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(filename=os.path.join(ICI, "journaux", "orchestration.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orchestrer")


def dates_reference(debut=date(2025, 11, 1), fin=date(2026, 9, 1)):
    d, res = debut, []
    while d <= fin:
        res.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--declencheur", default="manuel", choices=["manuel", "cron", "planificateur", "conteneur"])
    p.add_argument("--date-reference", type=date.fromisoformat)
    p.add_argument("--sans-api-geo", action="store_true")
    a = p.parse_args()
    dates = [a.date_reference] if a.date_reference else dates_reference()

    suivi = psycopg2.connect(PG_DSN); suivi.autocommit = True
    with suivi.cursor() as c:
        c.execute("INSERT INTO meta.etl_runs (declencheur, statut) VALUES (%s, 'en_cours') RETURNING run_id",
                  (a.declencheur,))
        run_id = c.fetchone()[0]
    log.info("run %s démarré (%s)", run_id, a.declencheur)
    volumes = {}
    try:
        lot, _ = crawl_scrape.collecter()  # applique le délai demandé par robots.txt
        volumes["catalogue"] = {"pages": lot["pages_lues"], "anomalies": len(lot["anomalies"])}
        if not a.sans_api_geo:
            try:
                with psycopg2.connect(PG_DSN) as cx, cx.cursor() as cur:
                    cur.execute("SELECT DISTINCT commune_norm FROM silver.clients")
                    noms = [r[0] for r in cur.fetchall()]
                if noms:
                    g, _ = api_geo.collecter(noms)
                    volumes["api_geo"] = {"demandes": g["demandes"], "trouvees": g["trouvees"]}
            except Exception as exc:  # source facultative : mode dégradé, pas d'échec global
                volumes["api_geo"] = {"statut": "indisponible", "erreur": str(exc)[:200]}
                log.warning("run %s : API Géo indisponible, enrichissement reporté (%s)", run_id, exc)
        cx = psycopg2.connect(PG_DSN)
        try:
            with cx.cursor() as cur:
                volumes["bronze"] = etl.extraire_bronze(cur, run_id)
                volumes["silver"] = etl.charger_silver(cur, run_id)
                volumes["gold"] = etl.charger_gold(cur, run_id, dates)
                rq = qualite.rapport(cur)
                volumes["qualite"] = rq["controles"]
                if not rq["conforme"]:
                    raise RuntimeError(f"contrôle qualité bloquant : {rq['controles']}")
            cx.commit()
        except Exception:
            cx.rollback()
            raise
        finally:
            cx.close()
        statut, erreur = "succes", None
    except Exception as exc:
        statut, erreur = "echec", f"{type(exc).__name__}: {exc}"
        log.error("run %s en échec : %s\n%s", run_id, erreur, traceback.format_exc())
        with open(os.path.join(ICI, "journaux", "alertes.log"), "a", encoding="utf-8") as f:
            f.write(f"ALERTE run {run_id} : {erreur}\n")
    with suivi.cursor() as c:
        c.execute("UPDATE meta.etl_runs SET statut=%s, termine_le=now(), volumes=%s, erreur=%s WHERE run_id=%s",
                  (statut, Json(volumes, dumps=lambda o: json.dumps(o, default=str)), erreur, run_id))
    log.info("run %s terminé : %s %s", run_id, statut, json.dumps(volumes, default=str))
    print(json.dumps({"run_id": run_id, "statut": statut, "erreur": erreur, "volumes": volumes},
                     ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if statut == "succes" else 1)


if __name__ == "__main__":
    main()
