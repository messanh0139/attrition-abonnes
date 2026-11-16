"""Recette de l'architecture de sécurité : exposition, contrôle d'accès, isolation des zones, parcours complet.

Prérequis, en mode production (ports d'administration non publiés) :
  docker compose -f docker-compose.yml -f docker-compose.production.yml --profile minio --profile acces up -d
  docker compose --profile traitements up -d catalogue
Usage      : python recette_architecture.py
Résultat   : tableau à l'écran et journaux/recette_architecture.csv

Chaque essai indique le comportement attendu (autorisé ou refusé) et celui constaté.
Les essais d'isolation sont lancés depuis l'intérieur des zones, comme le ferait un attaquant qui
aurait pris le contrôle d'un conteneur : il tente une vraie connexion à PostgreSQL, avec un mot de
passe valide, et un accès anonyme à MinIO.
"""
import csv
import os
import socket
import ssl
import subprocess
import time
from datetime import datetime, timedelta

import requests

ICI = os.path.dirname(os.path.abspath(__file__))
CA = os.path.join(ICI, "certs", "ca.crt")
PASSERELLE = "https://localhost:8443"
ENV_DOCKER = {**os.environ, "COMPOSE_PROFILES": "minio,acces,traitements"}


def nom_projet():
    """Nom du projet Docker (fichier .env), qui préfixe les réseaux et les images."""
    chemin = os.path.join(ICI, ".env")
    if os.path.exists(chemin):
        for ligne in open(chemin, encoding="utf-8"):
            if ligne.startswith("COMPOSE_PROJECT_NAME="):
                return ligne.split("=", 1)[1].strip()
    return os.path.basename(ICI).lower()


PROJET = nom_projet()
IMAGE_ESSAI = f"{PROJET}-traitements"        # image disposant de Python et du pilote PostgreSQL
CODE_CONNEXION = ("import os, psycopg2; c = psycopg2.connect(host=os.environ['H'], dbname='attrition', "
                  "user=os.environ['U'], password=os.environ['P'], sslmode=os.environ['M'], "
                  "sslrootcert=os.environ.get('CA', ''), connect_timeout=5); "
                  "c.cursor().execute('SELECT 1'); print('connexion acceptée')")
CODE_MINIO = ("import requests, urllib3; urllib3.disable_warnings()\n"
              "try: print('HTTP', requests.get('https://10.40.30.20:9000/bronze/', verify=False, timeout=5).status_code)\n"
              "except requests.RequestException as e: print('REFUS', type(e).__name__)")
resultats = []


def noter(zone, essai, attendu, autorise, detail=""):
    """autorise vaut None quand l'essai n'a pas pu avoir lieu : il est alors compté non conforme."""
    conforme = autorise is not None and (attendu == "autorisé") == autorise
    resultats.append({"Zone": zone, "Essai": essai, "Attendu": attendu,
                      "Constaté": "impossible" if autorise is None else "autorisé" if autorise else "refusé",
                      "Conforme": "OUI" if conforme else "NON", "Détail": str(detail)[:70]})


def lancer(commande, timeout=180):
    """Exécute une commande ; en cas de succès, garde la réponse de l'essai et non les messages de Docker."""
    r = subprocess.run(commande, cwd=ICI, env=ENV_DOCKER, capture_output=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    if r.returncode == 0 and r.stdout.strip():
        return r.returncode, r.stdout.strip()
    return r.returncode, (r.stdout + r.stderr).strip()


def docker(*args, timeout=180):
    return lancer(["docker", "compose", *args], timeout)


def joindre_depuis(service, hote, port, executer="exec"):
    """Tente une connexion TCP depuis l'intérieur d'un conteneur. Renvoie (connecté, détail)."""
    code_python = f"import socket; socket.create_connection(('{hote}', {port}), 3); print('connecté')"
    if executer == "run":
        rc, sortie = docker("run", "--rm", "--no-deps", service, "python", "-c", code_python)
    else:
        rc, sortie = docker("exec", "-T", service, "python", "-c", code_python)
    derniere = sortie.splitlines()[-1] if sortie else f"code {rc}"
    # Conteneur arrêté ou outil absent : l'essai n'a pas eu lieu, ce n'est pas un refus réseau
    if rc != 0 and any(m in sortie.lower() for m in ("not found", "not running", "no such service", "no container")):
        return None, f"essai impossible : {derniere}"
    return rc == 0, derniere


def interpreter(rc, sortie):
    """Distingue une connexion acceptée, un refus et un essai qui n'a pas pu avoir lieu."""
    derniere = sortie.splitlines()[-1] if sortie else f"code {rc}"
    if rc == 0:
        return True, derniere
    if any(m in sortie for m in ("no pg_hba.conf entry", "timeout expired", "timed out", "Connection refused",
                                 "No route to host", "Network is unreachable", "could not connect")):
        raison = next((l for l in sortie.splitlines() if "FATAL" in l or "time" in l or "route" in l.lower()), derniere)
        if "FATAL" in raison:
            return False, raison[raison.find("FATAL"):]
        return False, raison.split("failed:")[-1].strip() if "failed:" in raison else raison.strip()
    return None, f"essai impossible : {derniere}"


def connexion_base(contexte, hote, role, mot_de_passe, mode, ca=""):
    """Tente une connexion à PostgreSQL depuis une zone : conteneur existant ou conteneur d'essai."""
    variables = ["-e", f"H={hote}", "-e", f"U={role}", "-e", f"P={mot_de_passe}", "-e", f"M={mode}", "-e", f"CA={ca}"]
    if contexte == "api_collecte":
        rc, sortie = docker("exec", "-T", *variables, "api_collecte", "python", "-c", CODE_CONNEXION)
    elif contexte == "orchestrateur":       # le conteneur de l'ETL, rattaché aux traitements et aux données
        rc, sortie = docker("run", "--rm", "--no-deps", *variables, "traitements", "python", "-c", CODE_CONNEXION)
    else:                                   # conteneur d'essai placé dans le seul réseau de la zone indiquée
        rc, sortie = lancer(["docker", "run", "--rm", "--network", f"{PROJET}_{contexte}", *variables,
                             IMAGE_ESSAI, "python", "-c", CODE_CONNEXION], timeout=120)
    return interpreter(rc, sortie)


def psql(requete):
    rc, sortie = docker("exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "attrition", "-tAc", requete)
    return sortie.strip()


def mode_deploiement():
    """Mode production si PostgreSQL ne publie aucun port vers le poste."""
    rc, sortie = docker("port", "postgres", "5432")
    # Un port non publié est renvoyé sous la forme « :0 » : seule une adresse réelle signale une publication
    publie = rc == 0 and any(a in sortie for a in ("127.0.0.1:", "0.0.0.0:", "[::]:"))
    return "développement (ports d'administration publiés)" if publie else "production (ports d'administration non publiés)"


def main():
    mode = mode_deploiement()
    print(f"Mode de déploiement : {mode}\n")
    jeton = open(os.path.join(ICI, "secrets", "jeton_collecte.txt"), encoding="utf-8").read().strip()

    # 1. Exposition : seule la passerelle est joignable, en TLS 1.3
    r = requests.get(f"{PASSERELLE}/sante", verify=CA, timeout=5)
    contexte = ssl.create_default_context(cafile=CA)
    with socket.create_connection(("localhost", 8443), 5) as brut, contexte.wrap_socket(brut, server_hostname="localhost") as tls:
        version = tls.version()
    noter("accès", "Passerelle en HTTPS", "autorisé", r.status_code == 200, f"HTTP {r.status_code}, {version}")

    ancien = ssl.create_default_context(cafile=CA)
    ancien.maximum_version = ssl.TLSVersion.TLSv1_2
    try:
        with socket.create_connection(("localhost", 8443), 5) as brut, ancien.wrap_socket(brut, server_hostname="localhost"):
            noter("accès", "Passerelle en TLS 1.2", "refusé", True, "connexion acceptée")
    except ssl.SSLError as e:
        noter("accès", "Passerelle en TLS 1.2", "refusé", False, e.reason)

    r = requests.get("http://localhost:8443/sante", timeout=5)
    noter("accès", "Passerelle sans chiffrement (HTTP)", "refusé", r.status_code == 200, f"HTTP {r.status_code}")

    try:
        socket.create_connection(("127.0.0.1", 8000), 3).close()
        noter("accès", "API de collecte en direct, sans passerelle", "refusé", True, "port joignable")
    except OSError as e:
        noter("accès", "API de collecte en direct, sans passerelle", "refusé", False, "connexion refusée, aucun port publié")

    r = requests.get(f"{PASSERELLE}/docs", verify=CA, timeout=5)
    noter("accès", "Chemin non exposé (/docs)", "refusé", r.status_code == 200, f"HTTP {r.status_code}")

    # 2. Contrôle d'accès de l'API de collecte
    client = psql("SELECT a.client_id FROM silver.abonnements a WHERE a.fin IS NULL AND NOT EXISTS "
                  "(SELECT 1 FROM silver.evenements e WHERE e.client_id = a.client_id AND e.type_event = 'resiliation') "
                  "ORDER BY 1 LIMIT 1")
    evenement = {"event_id": "E9" + str(int(time.time()))[-10:], "client_id": client, "type_event": "session",
                 "event_at": (datetime.now() - timedelta(hours=1)).replace(microsecond=0).isoformat()}
    r = requests.post(f"{PASSERELLE}/evenements", json={"evenements": [evenement]}, verify=CA, timeout=10)
    noter("accès", "Dépôt sans jeton", "refusé", r.status_code == 201, f"HTTP {r.status_code}")
    entete = {"Authorization": f"Bearer {jeton}"}
    r = requests.post(f"{PASSERELLE}/evenements", json={"evenements": [{**evenement, "type_event": "sesion"}]},
                      headers=entete, verify=CA, timeout=10)
    noter("accès", "Dépôt d'un événement invalide", "refusé", r.status_code == 201, f"HTTP {r.status_code}")
    r = requests.post(f"{PASSERELLE}/evenements", json={"evenements": [evenement]}, headers=entete, verify=CA, timeout=10)
    noter("accès", "Dépôt d'un événement valide", "autorisé", r.status_code == 201,
          f"HTTP {r.status_code}, {evenement['event_id']} pour {client}")

    # 3. Isolation des zones : connexions réelles, avec des mots de passe valides
    mdp_etl = open(os.path.join(ICI, "secrets", "pg_etl.txt"), encoding="utf-8").read().strip()
    mdp_ingestion = open(os.path.join(ICI, "secrets", "pg_ingestion.txt"), encoding="utf-8").read().strip()
    for zone, essai, attendu, args in (
            ("isolation", "Zone d'accès vers PostgreSQL, mot de passe valide", "refusé",
             ("acces", "10.40.30.10", "r_etl", mdp_etl, "require")),
            ("isolation", "Zone des traitements vers PostgreSQL, mot de passe valide", "refusé",
             ("traitements", "10.40.30.10", "r_etl", mdp_etl, "require")),
            ("isolation", "API de collecte vers PostgreSQL (r_ingestion)", "autorisé",
             ("api_collecte", "postgres", "r_ingestion", mdp_ingestion, "verify-full", "/certs/ca.crt")),
            ("isolation", "Orchestrateur vers PostgreSQL (r_etl)", "autorisé",
             ("orchestrateur", "postgres", "r_etl", mdp_etl, "verify-full", "/app/certs/ca.crt"))):
        autorise, detail = connexion_base(*args)
        noter(zone, essai, attendu, autorise, detail)

    _, sortie = lancer(["docker", "run", "--rm", "--network", f"{PROJET}_acces", IMAGE_ESSAI, "python", "-c", CODE_MINIO],
                       timeout=120)
    if "HTTP" in sortie or "REFUS" in sortie:
        noter("isolation", "Zone d'accès vers MinIO, sans identifiants", "refusé", "HTTP 200" in sortie, sortie.splitlines()[-1])
    else:
        noter("isolation", "Zone d'accès vers MinIO, sans identifiants", "refusé", None, f"essai impossible : {sortie[-60:]}")

    connecte, detail = joindre_depuis("traitements", "10.40.10.20", 8000, "run")
    noter("isolation", "Zone des traitements vers l'API de collecte", "refusé", connecte, detail)

    # 4. Parcours complet : l'orchestrateur, dans la zone des traitements, intègre l'événement reçu
    rc, sortie = docker("run", "--rm", "traitements", timeout=600)
    present = psql(f"SELECT count(*) FROM silver.evenements WHERE event_id = '{evenement['event_id']}'") == "1"
    noter("traitements", "Orchestrateur en conteneur, événement intégré en silver", "autorisé",
          rc == 0 and present, "exécution réussie" if rc == 0 else sortie.splitlines()[-1:])

    os.makedirs(os.path.join(ICI, "journaux"), exist_ok=True)
    with open(os.path.join(ICI, "journaux", "recette_architecture.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(resultats[0]), delimiter=";")
        w.writeheader(); w.writerows(resultats)
    for l in resultats:
        print(f"{l['Zone']:<12} {l['Essai']:<56} {l['Attendu']:<9} {l['Constaté']:<9} {l['Conforme']:<4} {l['Détail'][:38]}")
    ko = sum(l["Conforme"] == "NON" for l in resultats)
    print(f"\nMode {mode} : {len(resultats)} essais, {ko} non conforme(s).")


if __name__ == "__main__":
    main()
