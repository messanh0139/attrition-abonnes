#!/bin/bash
# Seules les adresses de la zone des données (10.40.30.0/24) peuvent se connecter à PostgreSQL :
# toute autre origine est refusée, même avec un mot de passe valide.
# Limite constatée lors de la recette : quand un port est publié vers le poste, Docker fait transiter
# les connexions venant des autres réseaux par sa passerelle interne 10.40.30.1, qui appartient à
# cette zone. L'isolation complète passe donc aussi par le mode production (docker-compose.production.yml),
# qui ne publie plus les ports d'administration.
# Exécuté au premier démarrage, ou à la main : docker compose exec -T -u postgres postgres bash /docker-entrypoint-initdb.d/04_zone_donnees.sh
set -e
sed -i 's#^hostssl all all all scram-sha-256#hostssl all all 10.40.30.0/24 scram-sha-256#' "$PGDATA/pg_hba.conf"
grep -q "^hostssl all all 10.40.30.0/24 scram-sha-256" "$PGDATA/pg_hba.conf"
psql -U postgres -d postgres -tAc "SELECT pg_reload_conf()" > /dev/null
echo "Connexions réseau limitées à la zone des données (10.40.30.0/24)"
