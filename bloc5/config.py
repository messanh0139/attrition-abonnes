"""Paramètres communs du Bloc 5 : chemins, découpage temporel, variables.

Tous les scripts lisent ces valeurs ici, pour qu'un changement (par exemple une nouvelle
date de découpage) se fasse à un seul endroit.
"""
import glob
import os

ICI = os.path.dirname(os.path.abspath(__file__))

# Dossiers de travail (les tests automatisés les redirigent vers un dossier temporaire)
TRAVAIL = os.getenv("BLOC5_TRAVAIL", ICI)
DOSSIER_RESULTATS = os.path.join(TRAVAIL, "resultats")     # tableaux et rapports
DOSSIER_MODELES = os.path.join(TRAVAIL, "modeles")         # registre des modèles versionnés
DOSSIER_JOURNAUX = os.path.join(TRAVAIL, "journaux")       # prédictions servies, alertes

# Données : par défaut, le dernier export CSV produit par le Bloc 1 (exporter_gold.py).
# On peut indiquer un autre fichier avec la variable d'environnement BLOC5_DONNEES.
DOSSIER_EXPORTS = os.path.join(ICI, "..", "bloc1", "exports")


def fichier_donnees():
    choisi = os.getenv("BLOC5_DONNEES")
    if choisi:
        return choisi
    import stockage
    if stockage.en_ligne():
        # Sur GCP : le dernier export déposé dans le seau, copié dans un cache local
        exports = stockage.lister("donnees/variables_clients_")
        if not exports:
            raise FileNotFoundError("Aucun export dans le seau : déposer un fichier dans donnees/")
        local = os.path.join(TRAVAIL, "cache", os.path.basename(exports[-1]))
        if not os.path.exists(local):
            stockage.telecharger(exports[-1], local)
        return local
    exports = sorted(glob.glob(os.path.join(DOSSIER_EXPORTS, "variables_clients_*.csv")))
    if not exports:
        raise FileNotFoundError("Aucun export trouvé : lancer d'abord bloc1/exporter_gold.py")
    return exports[-1]          # le plus récent (le nom contient la date)



# Découpage dans le temps : on apprend sur le passé et on évalue sur des mois jamais vus.
# Les dates sont les dates de référence de la table d'analyse (le 1er de chaque mois).
FIN_APPRENTISSAGE = "2026-05-01"     # apprentissage : nov. 2025 à mai 2026 (7 mois)
FIN_VALIDATION = "2026-07-01"        # validation : juin et juillet 2026 (choix du modèle et du seuil)
                                     # test : août et septembre 2026 (évaluation finale, une seule fois)

CIBLE = "resiliation_30j"
GRAINE = 42                          # même graine partout : résultats reproductibles
ITERATIONS_RECHERCHE = int(os.getenv("BLOC5_ITERATIONS", "25"))   # combinaisons testées par famille de modèles

# Colonnes qui ne doivent jamais servir de variables : identifiant, date, traçabilité.
COLONNES_EXCLUES = ["client_pseudo", "date_reference", "calcule_le", "run_id", CIBLE]

# Seuils de surveillance du modèle en production
SEUIL_PSI_ALERTE = 0.2               # au-delà, la distribution d'une variable a nettement changé
BAISSE_AUC_ALERTE = 0.05             # baisse de l'AUC tolérée par rapport à la validation


# Sous Windows 11 récent, joblib ne trouve plus l'outil wmic qui lui sert à compter les cœurs
# physiques et affiche une erreur sans conséquence. On lui indique directement ce nombre,
# qui vaut en général la moitié des cœurs logiques : il n'a alors plus besoin de le chercher.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(max(1, (os.cpu_count() or 2) // 2)))
