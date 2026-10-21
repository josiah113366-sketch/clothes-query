-- Run with psql -X -v ON_ERROR_STOP=1 over verify-full TLS as the DB owner.
-- Supply two NEW random passwords in the process environment, never CLI arguments.
-- Fail on name conflicts; do not reuse/reset existing roles, tables or publications.
\set ON_ERROR_STOP on
\getenv writer_password INFRA_SMOKE_WRITER_PASSWORD
\getenv cdc_password INFRA_SMOKE_CDC_PASSWORD
BEGIN;
CREATE ROLE infra_smoke_writer LOGIN PASSWORD :'writer_password';
CREATE ROLE infra_smoke_cdc LOGIN PASSWORD :'cdc_password';
GRANT rds_replication TO infra_smoke_cdc;
CREATE SCHEMA infra_smoke;
CREATE TABLE infra_smoke.events (id integer PRIMARY KEY, value integer NOT NULL);
ALTER TABLE infra_smoke.events REPLICA IDENTITY FULL;
GRANT USAGE ON SCHEMA infra_smoke TO infra_smoke_writer, infra_smoke_cdc;
GRANT SELECT, INSERT, UPDATE, DELETE ON infra_smoke.events TO infra_smoke_writer;
GRANT SELECT ON infra_smoke.events TO infra_smoke_cdc;
CREATE PUBLICATION infra_smoke_publication FOR TABLE infra_smoke.events;
COMMIT;
-- No rows are inserted by initialization. Only the writer supplies trial data.
