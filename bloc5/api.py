"""API de prédiction du risque de résiliation.

Points d'accès :
  GET  /sante      état du service et version du modèle chargé
  GET  /modele     fiche résumée du modèle en production
  POST /predire    score de risque pour une liste de clients
  POST /recharger  recharge le modèle après une nouvelle mise en production
Chaque prédiction est historisée (journaux/predictions.csv sur le poste, dossier predictions/ du seau
Cloud Storage sur GCP) : quand la résiliation réelle sera connue (30 jours plus tard),
reentrainement.py comparera prédiction et réalité.
Le modèle en production est relu toutes les 5 minutes : une nouvelle version publiée dans le registre
est prise en compte par toutes les copies du service, sans redéploiement.
Si la variable d'environnement BLOC5_CLE_API est définie, chaque appel doit fournir cette clé
dans l'en-tête X-Cle-API.
Lancement : uvicorn api:app --port 8080
"""
import csv
import io
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Literal, Optional

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import registre
import stockage
from config import DOSSIER_JOURNAUX
from variables import construire

etat = {"modele": None, "fiche": None, "verifie_le": 0.0}
INTERVALLE_VERIFICATION = 300          # secondes entre deux lectures du registre


def charger_production():
    etat["modele"], etat["fiche"] = registre.charger()
    etat["verifie_le"] = time.time()


def actualiser_si_besoin():
    """Recharge le modèle si une autre version a été mise en production entre-temps."""
    if time.time() - etat["verifie_le"] < INTERVALLE_VERIFICATION:
        return
    etat["verifie_le"] = time.time()
    if registre.version_production() != etat["fiche"]["version"]:
        charger_production()


@asynccontextmanager
async def cycle_de_vie(_app):
    charger_production()          # le modèle est chargé une seule fois, au démarrage du service
    yield


app = FastAPI(title="API attrition", description="Score de risque de résiliation à 30 jours", version="1.0",
              lifespan=cycle_de_vie)


def verifier_cle(x_cle_api: Optional[str] = Header(default=None)):
    attendue = os.getenv("BLOC5_CLE_API")
    if attendue and x_cle_api != attendue:
        raise HTTPException(status_code=401, detail="Clé d'API absente ou invalide")


class Client(BaseModel):
    """Variables d'un client à une date de référence, telles que produites par le Bloc 1.

    Les bornes refusent les valeurs impossibles (nombre négatif, prix nul, ...) avant tout calcul.
    """
    client_pseudo: str = Field(min_length=1, max_length=64)
    date_reference: date
    prix_mensuel: float = Field(gt=0, le=1000)
    anciennete_jours: int = Field(ge=0, le=20000)
    sessions_30j: int = Field(ge=0)
    sessions_30_60j: int = Field(ge=0)
    evolution_sessions: Optional[float] = None
    supports_30j: int = Field(ge=0)
    reclamations_30j: int = Field(ge=0)
    jours_depuis_derniere_session: Optional[int] = Field(default=None, ge=0, le=60)
    code_departement: Optional[str] = Field(default=None, max_length=3)
    taille_commune: Optional[Literal["petite", "moyenne", "grande"]] = None


class Demande(BaseModel):
    clients: list[Client] = Field(min_length=1, max_length=10000)


def historiser(lignes):
    if stockage.en_ligne():
        # Un fichier par appel : plusieurs copies du service peuvent écrire en même temps sans conflit
        tampon = io.StringIO()
        ecrivain = csv.DictWriter(tampon, fieldnames=list(lignes[0]))
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
        stockage.ecrire_texte(f"predictions/{date.today().isoformat()}/{datetime.now():%H%M%S}-{uuid.uuid4().hex[:8]}.csv",
                              tampon.getvalue())
        return
    os.makedirs(DOSSIER_JOURNAUX, exist_ok=True)
    chemin = os.path.join(DOSSIER_JOURNAUX, "predictions.csv")
    nouveau = not os.path.exists(chemin)
    with open(chemin, "a", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=list(lignes[0]))
        if nouveau:
            ecrivain.writeheader()
        ecrivain.writerows(lignes)


@app.get("/sante")
def sante():
    return {"statut": "ok", "version_modele": etat["fiche"]["version"]}


@app.get("/modele", dependencies=[Depends(verifier_cle)])
def modele():
    f = etat["fiche"]
    return {"version": f["version"], "famille": f["famille"], "cree_le": f["cree_le"], "seuil": f["seuil"],
            "variables": f["variables"], "donnees": f["donnees"], "mesures_test": f["mesures_test"]}


@app.post("/predire", dependencies=[Depends(verifier_cle)])
def predire(demande: Demande):
    actualiser_si_besoin()
    fiche = etat["fiche"]
    v = fiche["variables"]
    df = construire(pd.DataFrame([c.model_dump() for c in demande.clients]))
    proba = etat["modele"].predict_proba(df[v["numeriques"] + v["binaires"] + v["categorielles"]])[:, 1]

    horodatage = datetime.now().isoformat(timespec="seconds")
    reponses = [{"client_pseudo": c.client_pseudo, "date_reference": c.date_reference.isoformat(),
                 "probabilite": round(float(p), 4), "risque_eleve": bool(p >= fiche["seuil"])}
                for c, p in zip(demande.clients, proba)]
    historiser([{**r, "version_modele": fiche["version"], "predit_le": horodatage} for r in reponses])
    # Journal structuré, lu par Cloud Logging : volume servi et part des clients à risque
    print(json.dumps({"severity": "INFO", "type": "prediction", "version_modele": fiche["version"],
                      "clients": len(reponses), "risque_eleve": sum(r["risque_eleve"] for r in reponses)}))
    return {"version_modele": fiche["version"], "seuil": fiche["seuil"], "predictions": reponses}


@app.post("/recharger", dependencies=[Depends(verifier_cle)])
def recharger():
    charger_production()
    return {"statut": "ok", "version_modele": etat["fiche"]["version"]}
