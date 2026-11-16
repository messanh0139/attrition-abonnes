"""Crawling puis scraping du catalogue des offres.

Étape 1 (crawling) : découverte des liens d'offres depuis la page d'accueil,
en restant sur le domaine du catalogue et en respectant robots.txt.
Étape 2 (scraping) : extraction du code, du nom et du prix de chaque offre.
Une page sans prix exploitable est signalée comme anomalie, jamais remplacée par 0.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import BRONZE_DIR, CATALOGUE_URL

USER_AGENT = "attrition-collecteur/1.0 (projet pedagogique)"
PRIX_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€")


def lire_robots(base):
    rp = robotparser.RobotFileParser()
    rp.set_url(urljoin(base, "/robots.txt"))
    rp.read()
    return rp


def crawler(base, session, rp):
    """Retourne la liste dédoublonnée des URL d'offres autorisées."""
    rep = session.get(base + "/", timeout=10)
    rep.raise_for_status()
    soup = BeautifulSoup(rep.content, "html.parser")  # octets bruts : le charset est lu dans la balise meta
    hote = urlparse(base).netloc
    trouves, ecartes = [], []
    for a in soup.find_all("a", href=True):
        url = urljoin(base + "/", a["href"])
        if urlparse(url).netloc != hote:
            ecartes.append((url, "hors domaine"))
        elif not rp.can_fetch(USER_AGENT, url):
            ecartes.append((url, "interdit par robots.txt"))
        elif "/offres/" not in url:
            ecartes.append((url, "hors catalogue"))
        elif url in trouves:
            ecartes.append((url, "doublon"))
        else:
            trouves.append(url)
    return trouves, ecartes


def convertir_prix(texte):
    m = PRIX_RE.search(texte or "")
    return Decimal(m.group(1).replace(",", ".")) if m else None


def scraper(url, session):
    rep = session.get(url, timeout=10)
    rep.raise_for_status()
    soup = BeautifulSoup(rep.content, "html.parser")  # octets bruts : le charset est lu dans la balise meta
    bloc = soup.select_one("article.offre")
    prix_brut = bloc.select_one(".offre-prix").get_text(strip=True)
    return {
        "plan_code": bloc["data-code"],
        "nom": bloc.select_one(".offre-nom").get_text(strip=True),
        "prix_brut": prix_brut,
        "prix_mensuel": convertir_prix(prix_brut),
        "url_source": url,
    }


def collecter(base=CATALOGUE_URL, delai=None):
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    rp = lire_robots(base)
    delai = rp.crawl_delay(USER_AGENT) or 0 if delai is None else delai
    urls, ecartes = crawler(base, session, rp)
    offres, anomalies = [], []
    for url in urls:
        fiche = scraper(url, session)
        if fiche["prix_mensuel"] is None:
            anomalies.append({"url": url, "motif": f"prix illisible : {fiche['prix_brut']!r}"})
        offres.append(fiche)
        time.sleep(delai)
    horodatage = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lot = {
        "source": "catalogue_web", "collecte_le": horodatage,
        "liens_decouverts": len(urls), "liens_ecartes": ecartes,
        "pages_lues": len(offres), "anomalies": anomalies,
        "offres": [{**o, "prix_mensuel": str(o["prix_mensuel"]) if o["prix_mensuel"] is not None else None} for o in offres],
    }
    chemin = f"{BRONZE_DIR}/catalogue_{horodatage[:10]}.json"
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(lot, f, ensure_ascii=False, indent=2)
    return lot, chemin


if __name__ == "__main__":
    base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else CATALOGUE_URL
    lot, chemin = collecter(base)
    print(f"{lot['liens_decouverts']} liens d'offres, {len(lot['liens_ecartes'])} écartés, "
          f"{lot['pages_lues']} pages lues, {len(lot['anomalies'])} anomalie(s) -> {chemin}")
    for u, m in lot["liens_ecartes"]:
        print("  écarté :", u, "-", m)
    for a in lot["anomalies"]:
        print("  anomalie :", a)
