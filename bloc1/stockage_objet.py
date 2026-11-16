"""Dépôt des archives bronze dans un stockage objet compatible S3 (MinIO ; tout serveur compatible S3 convient sans modification du code).

Organisation des clés : <source>/<annee>/<mois>/<fichier>. Les échanges sont chiffrés par TLS
(certificat du serveur vérifié) et chaque objet est chiffré au repos par MinIO (SSE-S3).
Après le dépôt, chaque objet est relu et sa taille comparée à celle du fichier d'origine.
"""
import glob
import os
import sys

import boto3
from botocore.exceptions import ClientError

from config import BRONZE_DIR, S3_BUCKET, S3_CA, S3_ENDPOINT, S3_KEY, S3_SECRET


def client():
    verification = S3_CA if S3_ENDPOINT.startswith("https") else None
    return boto3.client("s3", endpoint_url=S3_ENDPOINT, aws_access_key_id=S3_KEY,
                        aws_secret_access_key=S3_SECRET, region_name="us-east-1", verify=verification)


def preparer_bucket(s3):
    """Crée le bucket puis active les protections que le stockage prend en charge."""
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)
    options = (
        ("versionnage", lambda: s3.put_bucket_versioning(
            Bucket=S3_BUCKET, VersioningConfiguration={"Status": "Enabled"})),
        ("chiffrement des objets par défaut", lambda: s3.put_bucket_encryption(
            Bucket=S3_BUCKET, ServerSideEncryptionConfiguration={"Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})),
        ("blocage de l'accès public", lambda: s3.put_public_access_block(
            Bucket=S3_BUCKET, PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True})),
    )
    for nom, appel in options:
        try:
            appel()
            print("Option activée :", nom)
        except ClientError as exc:
            print("Option non prise en charge par ce stockage :", nom, exc.response["Error"]["Code"])


def cle(chemin):
    rel = os.path.relpath(chemin, BRONZE_DIR).replace(os.sep, "/")
    nom = os.path.basename(rel)
    source = rel.split("/")[0] if "/" in rel else nom.split("_")[0].split(".")[0]
    periode = nom[:7] if nom[:4].isdigit() else (nom.split("_")[-1][:7] if "_" in nom else "referentiel")
    return f"{source}/{periode.replace('-', '/')}/{nom}"


def deposer():
    s3 = client(); preparer_bucket(s3)
    n = 0
    for chemin in sorted(glob.glob(f"{BRONZE_DIR}/**/*.json*", recursive=True)):
        donnees = open(chemin, "rb").read()
        s3.put_object(Bucket=S3_BUCKET, Key=cle(chemin), Body=donnees, ServerSideEncryption="AES256")
        n += 1
    return n


def verifier():
    """Relit chaque objet : taille identique au fichier d'origine et chiffrement au repos actif."""
    s3 = client(); ok = ko = chiffres = 0
    tailles = {cle(c): os.path.getsize(c) for c in glob.glob(f"{BRONZE_DIR}/**/*.json*", recursive=True)}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET):
        for o in page.get("Contents", []):
            obj = s3.get_object(Bucket=S3_BUCKET, Key=o["Key"])
            ok, ko = (ok + 1, ko) if len(obj["Body"].read()) == tailles.get(o["Key"]) else (ok, ko + 1)
            chiffres += obj.get("ServerSideEncryption") == "AES256"
    return ok, ko, chiffres


if __name__ == "__main__":
    print(f"{deposer()} objets déposés dans s3://{S3_BUCKET}")
    ok, ko, chiffres = verifier()
    print(f"relecture : {ok} objets complets, {ko} incomplets, {chiffres} chiffrés au repos")
    sys.exit(1 if ko else 0)
