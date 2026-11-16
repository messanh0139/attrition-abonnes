"""Mesures de performance communes à tous les scripts.

Les résiliations ne représentent qu'environ 3 % des lignes : l'exactitude (accuracy) n'a pas
de sens ici, puisqu'un modèle qui prédirait « jamais de résiliation » aurait 97 % de bonnes
réponses. On utilise donc des mesures adaptées aux classes déséquilibrées.
"""
import numpy as np
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, precision_score,
                             recall_score, roc_auc_score)

PART_CIBLEE = 0.10      # hypothèse métier : le service client peut contacter 10 % des abonnés par mois


def mesures(y, proba, seuil=None):
    """Mesures indépendantes du seuil, puis mesures pour une campagne ciblant 10 % des clients."""
    y, proba = np.asarray(y), np.asarray(proba)
    resultat = {
        "auc_roc": roc_auc_score(y, proba),                 # capacité à classer partis avant restés
        "auc_pr": average_precision_score(y, proba),        # plus exigeante quand la classe est rare
        "brier": brier_score_loss(y, proba),                # qualité des probabilités
    }
    # Campagne : on contacte les 10 % de clients au risque le plus élevé
    nb = max(1, int(len(proba) * PART_CIBLEE))
    cibles = np.argsort(-proba)[:nb]
    resultat["precision_top10"] = y[cibles].mean()                  # part de futurs partis parmi les contactés
    resultat["rappel_top10"] = y[cibles].sum() / max(1, y.sum())    # part des départs captés par la campagne
    resultat = {k: float(v) for k, v in resultat.items()}
    if seuil is not None:
        predit = (proba >= seuil).astype(int)
        resultat.update({"seuil": float(seuil), "precision": float(precision_score(y, predit, zero_division=0)),
                         "rappel": float(recall_score(y, predit)), "f1": float(f1_score(y, predit))})
    return resultat


def meilleur_seuil(y, proba):
    """Seuil qui maximise le F1 : compromis entre clients contactés à tort et départs manqués."""
    candidats = np.unique(np.quantile(proba, np.linspace(0.5, 0.995, 200)))
    scores = [f1_score(y, (proba >= s).astype(int)) for s in candidats]
    return float(candidats[int(np.argmax(scores))])
