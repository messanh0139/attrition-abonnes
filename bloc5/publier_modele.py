"""Évaluation et mise en production du dernier modèle enregistré (étape de la chaîne CI/CD).

  1. contrôle de qualité de la dernière version du registre (verifier_modele.py) : en cas d'échec,
     la chaîne s'arrête (code de sortie 1) et rien n'est déployé ;
  2. comparaison avec le modèle en production, sur les mesures du test ;
  3. mise en production seulement si la nouvelle version n'est pas moins bonne (marge de 0,01 d'AUC PR).
Usage : python publier_modele.py
"""
import sys

import registre
import verifier_modele

MARGE = 0.01


def main():
    versions = registre.versions()
    if not versions:
        print("ÉCHEC : registre vide, lancer d'abord optimisation.py")
        sys.exit(1)
    candidate, production = versions[-1], registre.version_production()

    verifier_modele.main(candidate)            # s'arrête ici si le modèle est refusé
    if candidate == production:
        print(f"{candidate} est déjà en production : contrôle de qualité réussi.")
        return

    nouvelle = registre.fiche(candidate)["mesures_test"]["auc_pr"]
    actuelle = registre.fiche(production)["mesures_test"]["auc_pr"] if production else None
    if actuelle is None or nouvelle >= actuelle - MARGE:
        motif = f"publication CI/CD : AUC PR test {nouvelle:.3f}" + (f" contre {actuelle:.3f} pour {production}" if actuelle else "")
        registre.promouvoir(candidate, motif)
        print(f"{candidate} mise en production ({motif}).")
    else:
        print(f"{candidate} moins bonne que {production} ({nouvelle:.3f} contre {actuelle:.3f}) : {production} conservée.")


if __name__ == "__main__":
    main()
