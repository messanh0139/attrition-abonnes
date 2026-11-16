-- Schéma cible PostgreSQL 16 — architecture médaillon (bronze / silver / gold)
-- bronze : données reçues telles quelles (JSONB), jamais modifiées
-- silver : données validées, typées, normalisées (modèle relationnel)
-- gold   : variables d'analyse, pseudonymisées
-- meta   : traçabilité (exécutions, rejets, couverture des sources)

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS meta;

-- ---------- BRONZE ----------
CREATE TABLE IF NOT EXISTS bronze.reception (
    reception_id  BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,          -- 'evenements', 'clients', 'abonnements', 'catalogue', 'api_geo'
    fichier       TEXT        NOT NULL,
    lot_id        UUID        NOT NULL,
    recu_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    contenu       JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bronze_lot ON bronze.reception (source, lot_id);

-- ---------- SILVER ----------
CREATE TABLE IF NOT EXISTS silver.communes (
    code_insee        CHAR(5) PRIMARY KEY,
    nom               TEXT    NOT NULL,
    code_departement  VARCHAR(3) NOT NULL,
    population        INTEGER CHECK (population >= 0),
    collecte_le       TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.offres (
    plan_code     VARCHAR(10) PRIMARY KEY CHECK (plan_code ~ '^[A-Z]{2,10}$'),
    nom           TEXT          NOT NULL,
    prix_mensuel  NUMERIC(8,2)  NOT NULL CHECK (prix_mensuel > 0),
    url_source    TEXT          NOT NULL,
    collecte_le   TIMESTAMPTZ   NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.clients (
    client_id         VARCHAR(10) PRIMARY KEY CHECK (client_id ~ '^C[0-9]{5}$'),
    created_at        DATE    NOT NULL,
    commune_norm      TEXT    NOT NULL,
    code_insee        CHAR(5) REFERENCES silver.communes (code_insee),
    consentement      BOOLEAN NOT NULL CHECK (consentement)
);

CREATE TABLE IF NOT EXISTS silver.abonnements (
    abonnement_id  BIGSERIAL PRIMARY KEY,
    client_id      VARCHAR(10) NOT NULL REFERENCES silver.clients (client_id),
    plan_code      VARCHAR(10) NOT NULL REFERENCES silver.offres (plan_code),
    debut          DATE NOT NULL,
    fin            DATE,
    CONSTRAINT ck_chronologie CHECK (fin IS NULL OR fin >= debut),
    CONSTRAINT uq_abonnement UNIQUE (client_id, debut)
);
CREATE INDEX IF NOT EXISTS ix_abo_client ON silver.abonnements (client_id);

CREATE TABLE IF NOT EXISTS silver.evenements (
    event_id    VARCHAR(12) PRIMARY KEY,
    client_id   VARCHAR(10) NOT NULL REFERENCES silver.clients (client_id),
    type_event  TEXT        NOT NULL CHECK (type_event IN ('session','support','reclamation','resiliation')),
    event_at    TIMESTAMP   NOT NULL,
    lot_id      UUID        NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evt_client_date ON silver.evenements (client_id, event_at);

-- Table de correspondance des pseudonymes : réservée au rôle ETL (schéma silver)
CREATE TABLE IF NOT EXISTS silver.pseudonymes (
    client_id      VARCHAR(10) PRIMARY KEY REFERENCES silver.clients (client_id),
    client_pseudo  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid()   -- identifiant aléatoire
);

-- ---------- GOLD ----------
CREATE TABLE IF NOT EXISTS gold.variables_clients (
    client_pseudo        UUID        NOT NULL,           -- pseudonyme aléatoire, jamais l'identifiant réel
    date_reference       DATE        NOT NULL,
    plan_code            VARCHAR(10) NOT NULL,
    prix_mensuel         NUMERIC(8,2) NOT NULL CHECK (prix_mensuel > 0),
    anciennete_jours     INTEGER     NOT NULL CHECK (anciennete_jours >= 0),
    sessions_30j         INTEGER     NOT NULL CHECK (sessions_30j >= 0),
    sessions_30_60j      INTEGER     NOT NULL CHECK (sessions_30_60j >= 0),
    evolution_sessions   NUMERIC(6,2),                   -- NULL si aucune session sur 30-60 j
    supports_30j         INTEGER     NOT NULL CHECK (supports_30j >= 0),
    reclamations_30j     INTEGER     NOT NULL CHECK (reclamations_30j >= 0),
    jours_depuis_derniere_session INTEGER,
    code_departement     VARCHAR(3),
    taille_commune       TEXT CHECK (taille_commune IN ('petite','moyenne','grande')),
    resiliation_30j      SMALLINT CHECK (resiliation_30j IN (0,1)),   -- NULL = indéterminé
    calcule_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id               BIGINT      NOT NULL,
    PRIMARY KEY (client_pseudo, date_reference)
);

-- ---------- META ----------
CREATE TABLE IF NOT EXISTS meta.etl_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    lance_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    termine_le   TIMESTAMPTZ,
    declencheur  TEXT NOT NULL,                 -- 'manuel' | 'cron'
    statut       TEXT NOT NULL CHECK (statut IN ('en_cours','succes','echec')),
    volumes      JSONB,
    erreur       TEXT
);

CREATE TABLE IF NOT EXISTS meta.rejets (
    rejet_id   BIGSERIAL PRIMARY KEY,
    run_id     BIGINT NOT NULL,
    source     TEXT   NOT NULL,
    motif      TEXT   NOT NULL,
    contenu    JSONB  NOT NULL
);

CREATE TABLE IF NOT EXISTS meta.couverture (
    source          TEXT PRIMARY KEY,
    couvert_jusqu_a DATE NOT NULL,             -- dernière date pour laquelle la source est complète
    maj_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meta.fichiers_ingeres (
    fichier    TEXT PRIMARY KEY,
    taille     BIGINT NOT NULL,               -- un fichier déjà intégré, de même taille, n'est pas relu
    lot_id     UUID NOT NULL,
    lignes     INTEGER NOT NULL,
    run_id     BIGINT NOT NULL,
    ingere_le  TIMESTAMPTZ DEFAULT now()
);
