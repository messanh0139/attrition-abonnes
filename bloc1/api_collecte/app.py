"""API de collecte des événements de l'application (zone d'accès, derrière la passerelle HTTPS).

Rôle : recevoir les événements envoyés par l'application, les contrôler et les déposer tels quels
dans la couche bronze. Elle ne fait rien d'autre :
  - elle se connecte avec le rôle r_ingestion, qui ne peut qu'insérer dans bronze.reception ;
  - elle ne lit aucune donnée existante (ce rôle n'a pas accès à silver) : l'existence du client
    est vérifiée plus tard par l'ETL, qui trace les rejets dans meta.rejets ;
  - elle n'est joignable que par la passerelle : aucun port n'est publié sur le poste.

Points d'accès :
  GET  /sante         état du service
  POST /evenements    dépôt d'un lot d'événements (jeton obligatoire : en-tête Authorization: Bearer ...)
"""
import json
import os
import secrets
import uuid
from datetime import datetime
from typing import Literal

import psycopg2
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator


def lire_secret(nom, defaut=None):
    """Les secrets sont fournis par Docker dans /run/secrets, jamais écrits dans le code."""
    chemin = f"/run/secrets/{nom}"
    if os.path.exists(chemin):
        return open(chemin, encoding="utf-8").read().strip()
    return os.getenv(nom.upper(), defaut)


def connexion():
    return psycopg2.connect(host=os.getenv("PG_HOTE", "postgres"), port=int(os.getenv("PG_PORT", "5432")),
                            dbname="attrition", user="r_ingestion", password=lire_secret("pg_ingestion"),
                            sslmode="verify-full", sslrootcert=os.getenv("PG_CA", "/certs/ca.crt"),
                            connect_timeout=5)


def verifier_jeton(authorization: str = Header(default="")):
    attendu = lire_secret("jeton_collecte")
    fourni = authorization.removeprefix("Bearer ").strip()
    # Comparaison à durée constante : le temps de réponse ne révèle rien du jeton attendu
    if not attendu or not secrets.compare_digest(fourni, attendu):
        raise HTTPException(status_code=401, detail="Jeton d'accès absent ou invalide")


class Evenement(BaseModel):
    """Mêmes règles que la base : identifiants au bon format, type connu, date valide et non future."""
    event_id: str = Field(pattern=r"^E\d{8,11}$")
    client_id: str = Field(pattern=r"^C\d{5,9}$")
    type_event: Literal["session", "support", "reclamation", "resiliation"]
    event_at: datetime

    @field_validator("event_at")
    @classmethod
    def pas_dans_le_futur(cls, valeur):
        if valeur.replace(tzinfo=None) > datetime.now():
            raise ValueError("date future")
        return valeur


class Lot(BaseModel):
    evenements: list[Evenement] = Field(min_length=1, max_length=5000)


app = FastAPI(title="API de collecte", description="Dépôt des événements en couche bronze", version="1.0")


@app.get("/sante")
def sante():
    return {"statut": "ok"}


@app.post("/evenements", status_code=201, dependencies=[Depends(verifier_jeton)])
def deposer(lot: Lot):
    lot_id = str(uuid.uuid4())
    lignes = [(json.dumps({**e.model_dump(), "event_at": e.event_at.replace(tzinfo=None).isoformat()}),) for e in lot.evenements]
    try:
        with connexion() as cx, cx.cursor() as cur:
            cur.executemany("INSERT INTO bronze.reception (source, fichier, lot_id, contenu) "
                            "VALUES ('evenements', 'api_collecte', %s, %s::jsonb)",
                            [(lot_id, l[0]) for l in lignes])
    except psycopg2.Error:
        raise HTTPException(status_code=503, detail="Dépôt impossible pour le moment")
    return {"lot_id": lot_id, "evenements_deposes": len(lignes)}
