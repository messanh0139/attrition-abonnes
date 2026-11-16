"""Enrichissement territorial par l'API Géo (geo.api.gouv.fr), service public sous Licence Ouverte Etalab 2.0.

Pour chaque commune déclarée (nom normalisé), un seul appel : on demande la commune la plus peuplée
portant ce nom. La réponse brute complète est archivée en bronze avec sa date de collecte.
Contrôles : statut HTTP 200, JSON de type liste, champs attendus présents, délai maximal de 10 s.
"""
import json
import sys
import time
from datetime import datetime, timezone

import psycopg2
import requests

from config import BRONZE_DIR, PG_DSN

URL = "https://geo.api.gouv.fr/communes"
CHAMPS = ["code", "nom", "codeDepartement", "population"]


def interroger(nom, session):
    rep = session.get(URL, params={"nom": nom, "fields": ",".join(CHAMPS), "boost": "population",
                                   "limit": 1}, timeout=10)
    if rep.status_code != 200:
        raise RuntimeError(f"HTTP {rep.status_code} pour {nom}")
    donnees = rep.json()
    if not isinstance(donnees, list):
        raise ValueError(f"réponse inattendue pour {nom}")
    for c in donnees:
        manquants = [k for k in CHAMPS if k not in c]
        if manquants:
            raise ValueError(f"champs absents {manquants} pour {nom}")
    return donnees


def collecter(noms):
    s = requests.Session()
    s.headers["User-Agent"] = "attrition-collecteur/1.0 (projet pedagogique)"
    reponses, non_trouvees, erreurs = {}, [], {}
    for nom in noms:
        try:
            r = interroger(nom, s)
            reponses[nom] = r
            if not r:
                non_trouvees.append(nom)
        except Exception as exc:  # une erreur sur une commune n'arrête pas le lot
            erreurs[nom] = str(exc)
        time.sleep(0.1)  # 10 requêtes par seconde au plus, bien en deçà des limites du service
    horodatage = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lot = {"source": "api_geo", "url": URL, "licence": "Licence Ouverte / Etalab 2.0",
           "collecte_le": horodatage, "demandes": len(noms), "trouvees": len(reponses) - len(non_trouvees),
           "non_trouvees": non_trouvees, "erreurs": erreurs, "reponses": reponses}
    if erreurs and not reponses:
        raise ConnectionError(f"API Géo injoignable : {next(iter(erreurs.values()))}")
    chemin = f"{BRONZE_DIR}/api_geo_{horodatage[:10]}.json"
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(lot, f, ensure_ascii=False, indent=2)
    return lot, chemin


if __name__ == "__main__":
    with psycopg2.connect(PG_DSN) as cx, cx.cursor() as cur:
        cur.execute("SELECT DISTINCT commune_norm FROM silver.clients ORDER BY 1")
        noms = [r[0] for r in cur.fetchall()]
    lot, chemin = collecter(noms)
    print(f"{lot['demandes']} communes demandées, {lot['trouvees']} trouvées, "
          f"{len(lot['non_trouvees'])} sans résultat, {len(lot['erreurs'])} erreur(s) -> {chemin}")
    sys.exit(1 if lot["erreurs"] else 0)
