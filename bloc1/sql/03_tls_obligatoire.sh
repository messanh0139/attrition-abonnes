#!/bin/bash
# Exécuté au premier démarrage : toute connexion réseau doit être chiffrée par TLS.
# La règle « host » acceptant les connexions non chiffrées devient « hostssl ».
set -e
sed -i 's/^host all all all scram-sha-256$/hostssl all all all scram-sha-256/' "$PGDATA/pg_hba.conf"
grep -q "^hostssl all all all scram-sha-256" "$PGDATA/pg_hba.conf" && echo "TLS obligatoire pour les connexions réseau"
