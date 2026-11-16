"""Stockage des fichiers partagés : dossiers locaux sur le poste, Cloud Storage sur GCP.

Le même code fonctionne dans les deux cas. Le choix se fait par la variable BLOC5_BUCKET :
  - absente               : tout reste dans les dossiers locaux du projet (poste de développement) ;
  - gs://nom-du-seau      : Cloud Storage (services déployés sur GCP) ;
  - fichier:///un/dossier : un dossier qui imite un seau (tests automatisés, démonstration hors ligne).

Organisation du seau :
  donnees/variables_clients_AAAA-MM-JJ.csv   exports de la table d'analyse (nouvelles données)
  modeles/v001/, modeles/production.json      registre des modèles
  predictions/AAAA-MM-JJ/*.csv                prédictions servies par l'API (historisation)
  resultats/                                  surveillance, bilan du cycle de vie
"""
import os
import shutil


def adresse():
    return os.getenv("BLOC5_BUCKET", "").strip()


def en_ligne():
    """Vrai si un seau est configuré (Cloud Storage ou seau simulé)."""
    return bool(adresse())


def _racine_simulee():
    return adresse().removeprefix("fichier://")


def _seau():
    from google.cloud import storage          # importé seulement quand Cloud Storage est utilisé
    return storage.Client().bucket(adresse().removeprefix("gs://"))


def lister(prefixe):
    """Noms des fichiers dont le chemin commence par prefixe, triés."""
    if adresse().startswith("fichier://"):
        racine = _racine_simulee()
        trouves = []
        for dossier, _, fichiers in os.walk(racine):
            for f in fichiers:
                chemin = os.path.relpath(os.path.join(dossier, f), racine).replace(os.sep, "/")
                if chemin.startswith(prefixe):
                    trouves.append(chemin)
        return sorted(trouves)
    return sorted(b.name for b in _seau().list_blobs(prefix=prefixe))


def telecharger(chemin, destination):
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    if adresse().startswith("fichier://"):
        shutil.copyfile(os.path.join(_racine_simulee(), chemin), destination)
    else:
        _seau().blob(chemin).download_to_filename(destination)


def envoyer(source, chemin):
    if adresse().startswith("fichier://"):
        cible = os.path.join(_racine_simulee(), chemin)
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        shutil.copyfile(source, cible)
    else:
        _seau().blob(chemin).upload_from_filename(source)


def ecrire_texte(chemin, texte):
    if adresse().startswith("fichier://"):
        cible = os.path.join(_racine_simulee(), chemin)
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        with open(cible, "w", encoding="utf-8") as f:
            f.write(texte)
    else:
        _seau().blob(chemin).upload_from_string(texte, content_type="text/plain; charset=utf-8")


def lire_texte(chemin):
    if adresse().startswith("fichier://"):
        with open(os.path.join(_racine_simulee(), chemin), encoding="utf-8") as f:
            return f.read()
    return _seau().blob(chemin).download_as_text(encoding="utf-8")


def existe(chemin):
    if adresse().startswith("fichier://"):
        return os.path.exists(os.path.join(_racine_simulee(), chemin))
    return _seau().blob(chemin).exists()


def telecharger_dossier(prefixe, destination):
    """Copie tout ce qui se trouve sous prefixe dans le dossier local destination."""
    for chemin in lister(prefixe):
        telecharger(chemin, os.path.join(destination, chemin[len(prefixe):].lstrip("/")))


def publier_resultats():
    """Publie le dossier des résultats dans le seau, pour le tableau de bord (sans effet en local)."""
    from config import DOSSIER_RESULTATS
    if en_ligne() and os.path.isdir(DOSSIER_RESULTATS):
        envoyer_dossier(DOSSIER_RESULTATS, "resultats")


def envoyer_dossier(source, prefixe):
    for dossier, _, fichiers in os.walk(source):
        for f in fichiers:
            local = os.path.join(dossier, f)
            relatif = os.path.relpath(local, source).replace(os.sep, "/")
            envoyer(local, f"{prefixe.rstrip('/')}/{relatif}")
