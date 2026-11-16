"""Génère l'autorité de certification interne, les certificats TLS et les clés de chiffrement.

Fichiers produits (jamais versionnés) :
  certs/ca.crt                           autorité de certification interne (à distribuer aux clients)
  certs/postgres/server.crt, .key        certificat TLS de PostgreSQL
  certs/minio/public.crt, private.key    certificat TLS de MinIO
  certs/passerelle/server.crt, .key      certificat TLS de la passerelle HTTPS
  secrets/minio_kms.txt                  clé de chiffrement des objets stockés dans MinIO
  secrets/cle_sauvegarde.txt             clé de chiffrement des sauvegardes
  secrets/jeton_collecte.txt             jeton d'accès à l'API de collecte
  secrets/pg_ingestion.txt, pg_etl.txt   mots de passe des rôles utilisés par les conteneurs
Les certificats sont valables pour localhost, 127.0.0.1 et le nom du service Docker.

Le script est incrémental : il ne crée que les fichiers absents. Il ne remplace jamais une clé
existante, car cela rendrait illisibles les objets MinIO et les sauvegardes déjà chiffrés.
"""
import base64
import datetime as dt
import ipaddress
import os
import secrets

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ICI = os.path.dirname(os.path.abspath(__file__))
MAINTENANT = dt.datetime.now(dt.timezone.utc)


def cle_rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def ecrire(chemin, contenu):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "wb") as f:
        f.write(contenu)


def pem_cle(cle):
    return cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())


def autorite():
    cle = cle_rsa()
    nom = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Projet attrition"),
                     x509.NameAttribute(NameOID.COMMON_NAME, "Autorité de certification interne")])
    cert = (x509.CertificateBuilder().subject_name(nom).issuer_name(nom).public_key(cle.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(MAINTENANT - dt.timedelta(minutes=5))
            .not_valid_after(MAINTENANT + dt.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(cle, hashes.SHA256()))
    return cle, cert


def certificat_serveur(nom_service, cle_ca, cert_ca):
    cle = cle_rsa()
    noms = [x509.DNSName("localhost"), x509.DNSName(nom_service), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nom_service)]))
            .issuer_name(cert_ca.subject).public_key(cle.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(MAINTENANT - dt.timedelta(minutes=5))
            .not_valid_after(MAINTENANT + dt.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName(noms), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(cle_ca, hashes.SHA256()))
    return cle, cert


def chemin(*morceaux):
    return os.path.join(ICI, *morceaux)


def creer_si_absent(fichier, contenu, crees):
    if not os.path.exists(fichier):
        ecrire(fichier, contenu)
        crees.append(os.path.relpath(fichier, ICI))


def main():
    crees = []
    # Autorité de certification : réutilisée si elle existe déjà
    if os.path.exists(chemin("certs", "ca.crt")) and os.path.exists(chemin("secrets", "ca.key")):
        cert_ca = x509.load_pem_x509_certificate(open(chemin("certs", "ca.crt"), "rb").read())
        cle_ca = serialization.load_pem_private_key(open(chemin("secrets", "ca.key"), "rb").read(), password=None)
    else:
        cle_ca, cert_ca = autorite()
        creer_si_absent(chemin("certs", "ca.crt"), cert_ca.public_bytes(serialization.Encoding.PEM), crees)
        creer_si_absent(chemin("secrets", "ca.key"), pem_cle(cle_ca), crees)

    for service, dossier, nom_crt, nom_cle in (("postgres", "postgres", "server.crt", "server.key"),
                                                ("minio", "minio", "public.crt", "private.key"),
                                                ("passerelle", "passerelle", "server.crt", "server.key")):
        if not os.path.exists(chemin("certs", dossier, nom_crt)):
            cle, cert = certificat_serveur(service, cle_ca, cert_ca)
            creer_si_absent(chemin("certs", dossier, nom_crt), cert.public_bytes(serialization.Encoding.PEM), crees)
            creer_si_absent(chemin("certs", dossier, nom_cle), pem_cle(cle), crees)

    cle_kms = base64.b64encode(secrets.token_bytes(32)).decode()
    creer_si_absent(chemin("secrets", "minio_kms.txt"), f"attrition-cle:{cle_kms}".encode(), crees)
    creer_si_absent(chemin("secrets", "cle_sauvegarde.txt"), Fernet.generate_key(), crees)
    creer_si_absent(chemin("secrets", "jeton_collecte.txt"), secrets.token_urlsafe(32).encode(), crees)
    # Mots de passe de démonstration des rôles, identiques à ceux de la recette (à changer en production)
    creer_si_absent(chemin("secrets", "pg_ingestion.txt"), b"ing-demo", crees)
    creer_si_absent(chemin("secrets", "pg_etl.txt"), b"etl-demo", crees)

    if crees:
        print("Fichiers créés :")
        for f in crees:
            print("  " + f)
    else:
        print("Rien à créer : tous les certificats et toutes les clés existent déjà.")


if __name__ == "__main__":
    main()
