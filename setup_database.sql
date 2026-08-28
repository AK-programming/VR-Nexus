-- Native-install path: run this manually with psql after installing PostgreSQL
-- and building pgvector. Skip it entirely if you are using docker-compose,
-- which creates the role, database and extension for you (see
-- docker/init-extensions.sql).
--
-- Usage (from a normal Command Prompt / PowerShell):
--   "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -f setup_database.sql
--
-- The names below match the docker-compose defaults on purpose, so DATABASE_URL
-- in .env reads the same whichever path you took:
--   postgresql+psycopg://tender_admin:tender_dev_password@localhost:5432/tender_analysis

CREATE USER tender_admin WITH PASSWORD 'tender_dev_password';
CREATE DATABASE tender_analysis OWNER tender_admin;

\c tender_analysis

-- Requires pgvector to already be built and installed into this Postgres
-- instance - otherwise this line errors with "could not open extension control
-- file". chunks.embedding and tender_chunks.embedding are both vector(768), so
-- the first Alembic migration fails without it.
CREATE EXTENSION IF NOT EXISTS vector;

GRANT ALL PRIVILEGES ON DATABASE tender_analysis TO tender_admin;
GRANT ALL ON SCHEMA public TO tender_admin;
