"""Génère un jeu synthétique réaliste, tel que l'API de l'application l'aurait reçu.

- 5 000 clients, période d'observation du 2025-10-01 au 2026-09-30.
- Comportements avant résiliation simulés : baisse d'usage, hausse des réclamations.
- Anomalies injectées volontairement pour éprouver les contrôles :
  événements rejoués, client inconnu, type mal orthographié, date invalide,
  date future, communes mal saisies, contrat dont la fin précède le début.
La graine fixe rend le jeu strictement reproductible.
"""
import json
import os
from datetime import date, timedelta

import numpy as np

from config import BRONZE_DIR, GRAINE

N_CLIENTS = 5000
DEBUT, FIN = date(2025, 10, 1), date(2026, 9, 30)
NB_JOURS = (FIN - DEBUT).days + 1
PLANS = {"ESS": (0.50, 0.040), "CONF": (0.35, 0.032), "PREM": (0.15, 0.022)}  # part, risque mensuel
# Communes de rattachement déclarées (nom seul). La taille sert uniquement à la simulation.
COMMUNES = [("Nantes", "grande"), ("Rennes", "grande"), ("Angers", "grande"), ("Lyon", "grande"),
            ("Bordeaux", "grande"), ("Saint-Herblain", "moyenne"), ("Rezé", "moyenne"),
            ("Cholet", "moyenne"), ("Vannes", "moyenne"), ("Laval", "moyenne"),
            ("Ancenis-Saint-Géréon", "petite"), ("Clisson", "petite"), ("Machecoul-Saint-Même", "petite"),
            ("Châteaubriant", "petite"), ("Pornic", "petite"), ("Guérande", "petite")]
FACTEUR_TAILLE = {"grande": 1.25, "moyenne": 1.0, "petite": 0.8}


def main():
    rng = np.random.default_rng(GRAINE)
    os.makedirs(f"{BRONZE_DIR}/evenements", exist_ok=True)
    clients, abonnements, evenements = [], [], []
    codes = list(PLANS)
    parts = [PLANS[c][0] for c in codes]
    eid = 0
    for i in range(1, N_CLIENTS + 1):
        cid = f"C{i:05d}"
        # 60 % déjà clients au début de la période, 40 % arrivent pendant
        if rng.random() < 0.6:
            debut = DEBUT - timedelta(days=int(rng.integers(30, 700)))
        else:
            debut = DEBUT + timedelta(days=int(rng.integers(0, 300)))
        plan = codes[rng.choice(3, p=parts)]
        commune, taille = COMMUNES[rng.integers(len(COMMUNES))]
        saisie = commune
        r = rng.random()
        if r < 0.03:
            saisie = commune.upper() + " "          # casse et espace parasite
        elif r < 0.05:
            saisie = commune.lower()
        clients.append({"client_id": cid, "created_at": max(debut, DEBUT - timedelta(days=700)).isoformat(),
                        "commune_declaree": saisie, "consentement": True})
        # Durée de vie : risque mensuel selon formule et taille de commune
        risque_jour = PLANS[plan][1] * FACTEUR_TAILLE[taille] / 30
        fin = None
        j0 = max(0, (debut - DEBUT).days)
        for j in range(j0, NB_JOURS):
            if rng.random() < risque_jour:
                fin = DEBUT + timedelta(days=j)
                break
        abo = {"client_id": cid, "plan_code": plan, "debut": debut.isoformat(),
               "fin": fin.isoformat() if fin else None}
        if rng.random() < 0.003 and fin:
            abo["fin"] = (debut - timedelta(days=5)).isoformat()   # incohérence volontaire
        abonnements.append(abo)
        # Événements journaliers
        taux_sess = rng.gamma(2.0, 0.18)
        jfin = (fin - DEBUT).days if fin else NB_JOURS - 1
        for j in range(j0, jfin + 1):
            jour = DEBUT + timedelta(days=j)
            avant_fin = (jfin - j) if fin else 999
            k_sess = 0.2 + 0.8 * avant_fin / 45 if avant_fin < 45 else 1.0
            k_rec = 4.0 if avant_fin < 60 else 1.0
            for type_e, taux in (("session", taux_sess * k_sess), ("support", 0.008 * k_rec),
                                 ("reclamation", 0.003 * k_rec)):
                for _ in range(rng.poisson(taux)):
                    eid += 1
                    h = int(rng.integers(0, 86400))
                    evenements.append({"event_id": f"E{eid:08d}", "client_id": cid, "type_event": type_e,
                                       "event_at": f"{jour.isoformat()}T{h//3600:02d}:{h%3600//60:02d}:{h%60:02d}"})
        if fin:
            eid += 1
            evenements.append({"event_id": f"E{eid:08d}", "client_id": cid, "type_event": "resiliation",
                               "event_at": f"{fin.isoformat()}T12:00:00"})
    # --- Anomalies d'événements ---
    n = len(evenements)
    idx = rng.choice(n, size=int(n * 0.005), replace=False)
    evenements += [dict(evenements[k]) for k in idx]                              # rejeux
    for k in rng.choice(n, size=int(n * 0.002), replace=False):
        evenements[k]["client_id"] = "C9" + evenements[k]["client_id"][2:]        # client inconnu
    for k in rng.choice(n, size=int(n * 0.001), replace=False):
        evenements[k]["type_event"] = "sesion"                                     # faute de saisie
    for k in rng.choice(n, size=int(n * 0.0005), replace=False):
        evenements[k]["event_at"] = "2026-02-30T10:00:00"                          # date impossible
    for k in rng.choice(n, size=int(n * 0.0005), replace=False):
        evenements[k]["event_at"] = "2027-01-15T10:00:00"                          # date future
    # --- Écriture bronze : un fichier JSONL par mois de réception ---
    par_mois = {}
    for e in evenements:
        par_mois.setdefault(e["event_at"][:7], []).append(e)
    for mois, lignes in par_mois.items():
        with open(f"{BRONZE_DIR}/evenements/{mois}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in lignes)
    for nom, lignes in (("clients", clients), ("abonnements", abonnements)):
        with open(f"{BRONZE_DIR}/{nom}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in lignes)
    print(f"{len(clients)} clients, {len(abonnements)} abonnements, {len(evenements)} événements bruts "
          f"répartis dans {len(par_mois)} fichiers mensuels")


if __name__ == "__main__":
    main()
