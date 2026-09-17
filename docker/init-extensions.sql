-- Run once on first Postgres start against an empty data volume.
-- Creates the pgvector extension that the migration chain depends on.
-- If the volume already exists from before this script was added, connect
-- manually and run: CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS vector;
