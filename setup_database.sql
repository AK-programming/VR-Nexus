-- Run this manually with psql after installing PostgreSQL and building pgvector.
-- See README.md Section 3 for the full context.
--
-- Usage (from a normal Command Prompt / PowerShell):
--   "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -f setup_database.sql

CREATE USER tender_admin WITH PASSWORD 'tender_dev_password';
CREATE DATABASE tender_analysis OWNER tender_admin;

\c tender_analysis

-- Requires pgvector to already be built and installed into this Postgres instance
-- (README.md Section 3.3) - otherwise this line errors with "could not open extension control file".
CREATE EXTENSION IF NOT EXISTS vector;

GRANT ALL PRIVILEGES ON DATABASE tender_analysis TO tender_admin;
GRANT ALL ON SCHEMA public TO tender_admin;
