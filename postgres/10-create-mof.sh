#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set=ON_ERROR_STOP=1 \
  --set=app_password="$(cat /run/secrets/db_password)" <<'SQL'
SELECT format('CREATE ROLE mof LOGIN PASSWORD %L', :'app_password') \gexec
CREATE DATABASE mof OWNER mof;
REVOKE ALL ON DATABASE mof FROM PUBLIC;
SQL
