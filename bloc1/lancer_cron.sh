#!/bin/bash
# Point d'entrée appelé par cron. Les secrets sont lus dans .env (droits 600), jamais dans la crontab.
cd "$(dirname "$0")" || exit 1
source ./.env
exec /usr/bin/flock -n /tmp/attrition.lock /usr/bin/python3 orchestrer.py --declencheur cron "$@" >> journaux/cron.out 2>&1
