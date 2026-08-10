-- VidyaVerse on Neon Postgres: initial schema.
--
-- Two schemas, deliberately.
--
-- `raw` is an append-only landing zone for scraper output. Today the scrapers
-- write straight into the serving collection, so every correction - the domain
-- reclassification, the type fixes, the junk-title purge - had to mutate live
-- rows destructively and could not be undone or replayed. Keeping the raw
-- payload means a reprocess is a re-derive, not a re-scrape of 400 sources.
--
-- `app` is the serving layer. Columns are typed only where the application
-- filters, sorts or joins on them; the long tail of per-source fields lives in
-- `extras` as jsonb. That split matters because the scraped documents vary by
-- source, but the queries never reach into the varying parts - verified against
-- the codebase, which has zero nested-field queries.

CREATE EXTENSION IF NOT EXISTS vector;      -- semantic search, replaces a Python loop
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- fuzzy title matching

-- pg_cron is deliberately absent. Neon only allows it in the `postgres`
-- database, and scheduling cross-database jobs to expire rows in `neondb` is
-- more moving parts than the problem deserves. Mongo's TTL indexes (OTP codes,
-- 90-day auth audit retention) are replaced by a job in the existing job
-- runner, which is portable and visible in application logs rather than hidden
-- in the database.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS app;

-- ---------------------------------------------------------------------------
-- raw: what the scrapers actually saw
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.scrape_events (
    id              bigserial PRIMARY KEY,
    source          text        NOT NULL,
    url             text        NOT NULL,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    -- Lets an unchanged listing be recognised without re-parsing it, and makes
    -- "what changed on this source" answerable after the fact.
    content_hash    text,
    payload         jsonb       NOT NULL
);

CREATE INDEX IF NOT EXISTS scrape_events_source_fetched_idx
    ON raw.scrape_events (source, fetched_at DESC);
CREATE INDEX IF NOT EXISTS scrape_events_url_idx
    ON raw.scrape_events (url);
CREATE INDEX IF NOT EXISTS scrape_events_hash_idx
    ON raw.scrape_events (content_hash);

-- ---------------------------------------------------------------------------
-- app.opportunities: the serving table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app.opportunities (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Carried across from Mongo so migrated rows keep their identity and any
    -- external reference to an _id still resolves.
    legacy_mongo_id             text UNIQUE,

    -- Identity and dedup. `url` is the natural key: the scraper upserts on it,
    -- which becomes ON CONFLICT (url) here.
    url                         text NOT NULL UNIQUE,
    canonical_url_hash          text,
    canonical_key               text,
    title_company_location_hash text,
    duplicate_cluster_key       text,

    -- What a student reads.
    title                       text NOT NULL,
    description                 text NOT NULL DEFAULT '',
    normalized_title            text,
    normalized_organization     text,
    university                  text,
    location                    text,
    work_mode                   text,
    stipend                     text,
    eligibility                 text,
    ppo_available               text,

    -- What the feed filters and sorts on.
    opportunity_type            text,
    domain                      text,
    portal_category             text,
    source                      text,
    source_id                   text,
    opportunity_status          text NOT NULL DEFAULT 'active',
    lifecycle_status            text NOT NULL DEFAULT 'published',
    trust_status                text NOT NULL DEFAULT 'unreviewed',
    url_liveness_status         text NOT NULL DEFAULT 'unknown',
    is_employer_post            boolean NOT NULL DEFAULT false,
    quality_review_required     boolean NOT NULL DEFAULT false,

    trust_score                 smallint NOT NULL DEFAULT 50,
    risk_score                  smallint NOT NULL DEFAULT 50,
    quality_score               real,
    freshness_score             real NOT NULL DEFAULT 1.0,
    dedup_score                 real NOT NULL DEFAULT 0.0,
    source_count                integer NOT NULL DEFAULT 1,
    duplicate_count             integer NOT NULL DEFAULT 0,

    stipend_min                 integer,
    stipend_max                 integer,
    stipend_currency            text,
    stipend_period              text,
    duration_months             real,

    -- Arrays stay arrays: Postgres indexes and queries them natively, so there
    -- is no reason to bury them in jsonb.
    tags                        text[]  NOT NULL DEFAULT '{}',
    seen_on                     text[]  NOT NULL DEFAULT '{}',
    batch_years                 integer[] NOT NULL DEFAULT '{}',

    -- 384 dimensions: the live vectors come from
    -- sentence-transformers/all-MiniLM-L6-v2, verified against the corpus.
    -- EMBED_DIM in rag_intelligence.py is 192, but that is the hash-based
    -- fallback used when the model is unavailable - not what is stored.
    embedding                   vector(384),
    embedding_text_hash         text,
    embedding_model_version     text,
    embedding_updated_at        timestamptz,

    deadline                    timestamptz,
    duration_start              timestamptz,
    duration_end                timestamptz,
    published_at                timestamptz,
    paused_at                   timestamptz,
    closed_at                   timestamptz,
    reviewed_at                 timestamptz,
    url_last_checked_at         timestamptz,
    last_quality_run_at         timestamptz,
    lifecycle_updated_at        timestamptz NOT NULL DEFAULT now(),
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    last_seen_at                timestamptz NOT NULL DEFAULT now(),

    -- Everything else: risk_reasons, verification_evidence, source_ids,
    -- quality_missing_fields, reviewer ids, and whatever a new source adds
    -- tomorrow. No query reaches into this, so it needs no shape.
    extras                      jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Indexes mirror the Mongo compound indexes that were actually declared, so the
-- feed's existing access patterns stay cheap rather than being rediscovered.
CREATE INDEX IF NOT EXISTS opportunities_status_freshness_idx
    ON app.opportunities (opportunity_status, freshness_score DESC, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS opportunities_lifecycle_seen_idx
    ON app.opportunities (lifecycle_status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS opportunities_quality_seen_idx
    ON app.opportunities (quality_score DESC, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS opportunities_source_seen_idx
    ON app.opportunities (source, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS opportunities_trust_idx
    ON app.opportunities (trust_status, risk_score, updated_at DESC);
CREATE INDEX IF NOT EXISTS opportunities_embedding_version_idx
    ON app.opportunities (embedding_model_version, embedding_updated_at);
CREATE INDEX IF NOT EXISTS opportunities_created_idx
    ON app.opportunities (created_at DESC);

-- The feed's real query: active rows in one portal, newest first.
CREATE INDEX IF NOT EXISTS opportunities_portal_active_idx
    ON app.opportunities (portal_category, opportunity_status, created_at DESC);

-- Dedup lookups.
CREATE INDEX IF NOT EXISTS opportunities_canonical_hash_idx ON app.opportunities (canonical_url_hash);
CREATE INDEX IF NOT EXISTS opportunities_cluster_idx        ON app.opportunities (duplicate_cluster_key);

-- Trigram index for title search, replacing the $regex scans.
CREATE INDEX IF NOT EXISTS opportunities_title_trgm_idx
    ON app.opportunities USING gin (title gin_trgm_ops);

-- Tag filtering without unnesting.
CREATE INDEX IF NOT EXISTS opportunities_tags_idx
    ON app.opportunities USING gin (tags);

-- Vector search. HNSW rather than IVFFlat: it needs no training pass and stays
-- accurate as rows are added continuously, which is what a live scraper does.
CREATE INDEX IF NOT EXISTS opportunities_embedding_hnsw_idx
    ON app.opportunities USING hnsw (embedding vector_cosine_ops);
