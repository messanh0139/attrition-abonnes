"""Tableau de bord du modèle d'attrition (Streamlit) : démonstration et suivi en production.

Onglets :
  Prédire               score de risque d'un client, calculé par l'API déployée (ou localement)
  Modèle en production  version, performances, variables et historique des mises en production
  Surveillance          performance et dérive des données mois par mois, alertes
  Prédictions servies   prédictions historisées par l'API

Les données viennent du seau Cloud Storage sur GCP (variable BLOC5_BUCKET), des dossiers locaux sinon.
Lancement : streamlit run dashboard.py
"""
import io
import json
import os
from datetime import date

import pandas as pd
import requests
import streamlit as st

import registre
import stockage
from config import DOSSIER_RESULTATS
from reentrainement import predictions_historisees
from variables import construire

URL_API = os.getenv("BLOC5_URL_API", "").rstrip("/")
CLE_API = os.getenv("BLOC5_CLE_API", "")

st.set_page_config(page_title="Attrition – suivi du modèle", page_icon="📉", layout="wide")


# ---------- Lecture des données, gardées en cache 5 minutes ----------

@st.cache_resource(ttl=300)
def modele_en_production():
    return registre.charger()


@st.cache_data(ttl=300)
def historique_versions():
    registre.synchroniser()
    if not os.path.exists(registre.FICHIER_PRODUCTION):
        return pd.DataFrame()
    with open(registre.FICHIER_PRODUCTION, encoding="utf-8") as f:
        return pd.DataFrame(json.load(f)["historique"])


def lire_resultat(nom):
    """Contenu d'un fichier de résultats : dans le seau sur GCP, dans le dossier local sinon."""
    if stockage.en_ligne():
        chemin = f"resultats/{nom}"
        return stockage.lire_texte(chemin) if stockage.existe(chemin) else None
    local = os.path.join(DOSSIER_RESULTATS, nom)
    return open(local, encoding="utf-8").read() if os.path.exists(local) else None


@st.cache_data(ttl=300)
def surveillance():
    texte = lire_resultat("surveillance.csv")
    return pd.read_csv(io.StringIO(texte)) if texte else pd.DataFrame()


@st.cache_data(ttl=300)
def bilan_cycle():
    texte = lire_resultat("cycle.json")
    return json.loads(texte) if texte else {}


@st.cache_data(ttl=300)
def predictions():
    servies = predictions_historisees()
    return servies if servies is not None else pd.DataFrame()


# ---------- En-tête ----------

modele, fiche = modele_en_production()
st.title("Risque de résiliation des abonnés")
st.caption(f"Modèle en production : {fiche['version']} ({fiche['famille']}) · "
           f"données : {'seau Cloud Storage' if stockage.en_ligne() else 'dossiers locaux'} · "
           f"prédictions : {'API déployée' if URL_API else 'calcul local'}")

onglet_prediction, onglet_modele, onglet_surveillance, onglet_historique = st.tabs(
    ["Prédire", "Modèle en production", "Surveillance", "Prédictions servies"])


# ---------- Prédire ----------

with onglet_prediction:
    st.subheader("Score de risque d'un client")
    with st.form("client"):
        c1, c2, c3 = st.columns(3)
        prix = c1.selectbox("Formule", [9.99, 14.99, 19.99], format_func=lambda p: {9.99: "Essentiel", 14.99: "Confort", 19.99: "Premium"}[p])
        anciennete = c1.number_input("Ancienneté (jours)", min_value=0, max_value=5000, value=400)
        taille = c1.selectbox("Taille de la commune", ["petite", "moyenne", "grande"], index=2)
        sessions_30 = c2.number_input("Sessions sur 30 jours", min_value=0, max_value=200, value=2)
        sessions_60 = c2.number_input("Sessions entre 30 et 60 jours", min_value=0, max_value=200, value=9)
        jours = c2.number_input("Jours depuis la dernière session", min_value=0, max_value=60, value=20)
        supports = c3.number_input("Demandes au support sur 30 jours", min_value=0, max_value=50, value=1)
        reclamations = c3.number_input("Réclamations sur 30 jours", min_value=0, max_value=50, value=1)
        departement = c3.selectbox("Département", ["44", "35", "49", "56", "53", "69", "33"])
        envoye = st.form_submit_button("Calculer le risque")

    if envoye:
        client = {"client_pseudo": "demonstration", "date_reference": date.today().replace(day=1).isoformat(),
                  "prix_mensuel": prix, "anciennete_jours": int(anciennete), "sessions_30j": int(sessions_30),
                  "sessions_30_60j": int(sessions_60),
                  "evolution_sessions": None if sessions_60 == 0 else round((sessions_30 - sessions_60) / sessions_60, 2),
                  "supports_30j": int(supports), "reclamations_30j": int(reclamations),
                  "jours_depuis_derniere_session": int(jours), "code_departement": departement, "taille_commune": taille}
        if URL_API:
            reponse = requests.post(f"{URL_API}/predire", json={"clients": [client]},
                                    headers={"X-Cle-API": CLE_API}, timeout=15)
            reponse.raise_for_status()
            resultat = reponse.json()["predictions"][0]
            probabilite, risque = resultat["probabilite"], resultat["risque_eleve"]
        else:
            v = fiche["variables"]
            ligne = construire(pd.DataFrame([client]).assign(date_reference=lambda d: pd.to_datetime(d["date_reference"])))
            probabilite = float(modele.predict_proba(ligne[v["numeriques"] + v["binaires"] + v["categorielles"]])[0, 1])
            risque = probabilite >= fiche["seuil"]
        m1, m2 = st.columns(2)
        m1.metric("Probabilité de résiliation à 30 jours", f"{probabilite:.1%}")
        m2.metric("Niveau de risque", "Élevé" if risque else "Faible", help=f"Seuil de décision : {fiche['seuil']:.1%}")
        if risque:
            st.warning("Client à contacter en priorité par le service client.")
        else:
            st.success("Pas d'action prioritaire pour ce client.")


# ---------- Modèle en production ----------

with onglet_modele:
    m = fiche["mesures_test"]
    st.subheader(f"Version {fiche['version']}, créée le {fiche['cree_le'][:10]}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AUC ROC (test)", f"{m['auc_roc']:.3f}")
    c2.metric("AUC PR (test)", f"{m['auc_pr']:.3f}")
    c3.metric("Départs captés en contactant 10 %", f"{m['rappel_top10']:.0%}")
    c4.metric("Seuil de décision", f"{fiche['seuil']:.1%}")
    st.write(f"Famille : **{fiche['famille']}** · données : {fiche['donnees']['fichier']} · "
             f"apprentissage du {fiche['donnees']['periode_apprentissage'][0]} au {fiche['donnees']['periode_apprentissage'][1]}, "
             f"test du {fiche['donnees']['periode_test'][0]} au {fiche['donnees']['periode_test'][1]}")
    v = fiche["variables"]
    st.write("Variables utilisées : " + ", ".join(v["numeriques"] + v["binaires"] + v["categorielles"]))
    st.subheader("Historique des mises en production")
    st.dataframe(historique_versions(), use_container_width=True, hide_index=True)


# ---------- Surveillance ----------

with onglet_surveillance:
    suivi = surveillance()
    if suivi.empty:
        st.info("Aucun résultat de surveillance pour le moment : lancer surveillance.py ou le cycle de vie.")
    else:
        suivi["mois"] = pd.to_datetime(suivi["mois"]).dt.strftime("%Y-%m")
        c1, c2 = st.columns(2)
        c1.write("**Performance du modèle par mois (AUC ROC)**")
        c1.line_chart(suivi.set_index("mois")[["auc_roc"]])
        c2.write("**Dérive des données par mois (PSI maximal, alerte au-delà de 0,2)**")
        c2.bar_chart(suivi.set_index("mois")[["psi_max"]])
        st.dataframe(suivi, use_container_width=True, hide_index=True)
    cycle = bilan_cycle()
    if cycle:
        st.subheader("Dernier cycle de vie")
        st.write(f"{cycle['date'][:16].replace('T', ' ')} : {cycle['decision']}")
        for alerte in cycle.get("alertes", []):
            st.error(alerte)
        if not cycle.get("alertes"):
            st.success("Aucune alerte lors du dernier cycle.")


# ---------- Prédictions servies ----------

with onglet_historique:
    servies = predictions()
    if servies.empty:
        st.info("Aucune prédiction servie par l'API pour le moment.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Prédictions servies", len(servies))
        c2.metric("Part de clients à risque élevé", f"{servies['risque_eleve'].astype(str).eq('True').mean():.0%}")
        c3.metric("Probabilité moyenne", f"{servies['probabilite'].mean():.1%}")
        classes = pd.cut(servies["probabilite"], bins=[0, 0.05, 0.1, 0.2, 0.4, 1.0], include_lowest=True)
        st.write("**Répartition des probabilités prédites**")
        repartition = classes.value_counts(sort=False)
        repartition.index = repartition.index.astype(str)
        st.bar_chart(repartition.rename("clients"))
        st.dataframe(servies.tail(20), use_container_width=True, hide_index=True)
