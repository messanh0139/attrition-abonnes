"""Chiffre une sauvegarde PostgreSQL, puis vérifie qu'elle se déchiffre à l'identique.

La clé est lue dans secrets/cle_sauvegarde.txt (générée par generer_certificats.py).
Usage : python chiffrer_sauvegarde.py sauvegardes/attrition_AAAAMMJJ_HHMM.dump
Résultat : fichier .dump.chiffre ; la copie en clair est supprimée après vérification.
"""
import os
import sys

from cryptography.fernet import Fernet

ICI = os.path.dirname(os.path.abspath(__file__))


def main(chemin):
    cle = open(os.path.join(ICI, "secrets", "cle_sauvegarde.txt"), "rb").read().strip()
    f = Fernet(cle)
    clair = open(chemin, "rb").read()
    chiffre = f.encrypt(clair)
    sortie = chemin + ".chiffre"
    open(sortie, "wb").write(chiffre)
    identique = f.decrypt(open(sortie, "rb").read()) == clair
    if identique:
        os.remove(chemin)
    print(f"Sauvegarde chiffrée : {sortie} ({len(chiffre)} octets) ; déchiffrement vérifié : {'OUI' if identique else 'NON'}")
    sys.exit(0 if identique else 1)


if __name__ == "__main__":
    main(sys.argv[1])
