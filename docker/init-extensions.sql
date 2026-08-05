-- Runs automatically ONLY on first container start (empty data volume).
-- Creates the pgvector extension inside the tender_system database so
-- the Chunk model's vector column works exactly like it did on the
-- native install.
CREATE EXTENSION IF NOT EXISTS vector;
