"""Tests automatisés de la chaîne. Prérequis : base 'attrition' chargée, catalogue servi sur le port 8001."""
import os
import sys
from datetime import date
from decimal import Decimal
from unittest import mock

import pandas as pd
import psycopg2
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api_geo  # noqa: E402
import crawl_scrape  # noqa: E402
import etl  # noqa: E402
from config import PG_DSN  # noqa: E402


@pytest.fixture
def cur():
    cx = psycopg2.connect(PG_DSN)
    with cx.cursor() as c:
        yield c
    cx.rollback()  # aucun test ne laisse de trace en base
    cx.close()


# --- Collecte -----------------------------------------------------------------
def test_conversion_prix():
    assert crawl_scrape.convertir_prix("14,99 € / mois") == Decimal("14.99")
    assert crawl_scrape.convertir_prix("Nous consulter") is None


def test_crawler_respecte_perimetre_et_robots():
    lot, _ = crawl_scrape.collecter(delai=0)
    motifs = {m for _, m in lot["liens_ecartes"]}
    assert lot["liens_decouverts"] == lot["pages_lues"] == 4
    assert motifs == {"doublon", "hors domaine", "interdit par robots.txt"}


def test_prix_illisible_signale_et_non_remplace_par_zero():
    lot, _ = crawl_scrape.collecter(delai=0)
    famille = next(o for o in lot["offres"] if o["plan_code"] == "FAM")
    assert famille["prix_mensuel"] is None and len(lot["anomalies"]) == 1


def test_api_geo_controle_les_champs():
    rep = mock.Mock(status_code=200, json=lambda: [{"code": "44109", "nom": "Nantes"}])
    with mock.patch("requests.Session.get", return_value=rep):
        with pytest.raises(ValueError, match="champs absents"):
            api_geo.interroger("Nantes", api_geo.requests.Session())


def test_api_geo_statut_http_en_erreur():
    rep = mock.Mock(status_code=503)
    with mock.patch("requests.Session.get", return_value=rep):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            api_geo.interroger("Nantes", api_geo.requests.Session())


# --- Transformation -----------------------------------------------------------
def test_normalisation_des_communes():
    s = pd.Series(["Nantes", "NANTES ", "nantes", "Rezé", "  Rezé"])
    assert list(etl.normaliser_communes(s)) == ["Nantes", "Nantes", "Nantes", "Rezé", "Rezé"]


def test_cible_indeterminee_si_periode_future_non_couverte(cur):
    # 2026-09-15 + 29 jours dépasse la couverture des sources (2026-09-30) : pas d'étiquette 0
    etl.charger_gold(cur, 0, [date(2026, 9, 15)])
    cur.execute("""SELECT count(*) FILTER (WHERE resiliation_30j = 0),
                          count(*) FILTER (WHERE resiliation_30j IS NULL)
                   FROM gold.variables_clients WHERE date_reference = '2026-09-15'""")
    zeros, indetermines = cur.fetchone()
    assert zeros == 0 and indetermines > 0


def test_relance_sans_doublon(cur):
    d = date(2026, 3, 1)
    etl.charger_gold(cur, 0, [d])
    cur.execute("SELECT count(*) FROM gold.variables_clients WHERE date_reference = %s", (d,))
    n1 = cur.fetchone()[0]
    etl.charger_gold(cur, 0, [d])
    cur.execute("SELECT count(*), count(DISTINCT client_pseudo) FROM gold.variables_clients WHERE date_reference = %s", (d,))
    n2, distincts = cur.fetchone()
    assert n1 == n2 == distincts


def test_variables_calculees_uniquement_avant_la_date_de_reference(cur):
    # Recalcul indépendant des sessions sur [d-30, d) : doit coïncider pour 100 % des lignes
    cur.execute("""
        WITH attendu AS (
            SELECT ps.client_pseudo AS p, count(*) AS n
            FROM silver.evenements e JOIN silver.pseudonymes ps USING (client_id)
            WHERE e.type_event = 'session' AND e.event_at >= '2026-03-01'::date - 30 AND e.event_at < '2026-03-01'
            GROUP BY ps.client_pseudo)
        SELECT count(*) FROM gold.variables_clients g LEFT JOIN attendu a ON a.p = g.client_pseudo
        WHERE g.date_reference = '2026-03-01' AND g.sessions_30j <> coalesce(a.n, 0)""")
    assert cur.fetchone()[0] == 0


def test_pseudonyme_aleatoire_et_stable(cur):
    # Aucun identifiant réel en gold, et un même client garde le même pseudonyme d'une date à l'autre
    cur.execute("SELECT count(*) FROM gold.variables_clients WHERE client_pseudo::text LIKE 'C%'")
    assert cur.fetchone()[0] == 0
    cur.execute("""SELECT count(DISTINCT client_pseudo) <= (SELECT count(*) FROM silver.clients)
                   FROM gold.variables_clients""")
    assert cur.fetchone()[0]


# --- Intégrité ----------------------------------------------------------------
def test_base_refuse_un_prix_negatif(cur):
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("INSERT INTO silver.offres VALUES ('NEG','Neg',-1,'x',now())")


def test_base_refuse_un_evenement_orphelin(cur):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cur.execute("INSERT INTO silver.evenements VALUES ('EZ1','C99999','session',now(),gen_random_uuid())")
