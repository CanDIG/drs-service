#!/usr/bin/env bash

set -Euo pipefail

# db=${DB_PATH:-data/files.db}
db=${DB_PATH:-"postgres-db"}

# PGPASSWORD is used by psql to avoid the password prompt
export PGPASSWORD=${PGPASSWORD:-$(cat $POSTGRES_PASSWORD_FILE)}
export PGUSER=$POSTGRES_USERNAME

until pg_isready -h "$db" -p 5432 -U $PGUSER; do
  echo "Waiting for the database at $db to be ready..."
  sleep 1
done

echo "database is at $db"
pwd

# migrate tables from genomic db, if existing
psql --quiet -h "$db" -U $PGUSER -d genomic -c "SELECT * from drs_object limit 1"
if [[ $? -eq 0 ]]; then
    echo "migrating tables..."
    createdb -h "$db" -U $PGUSER drs
    pg_dump -h "$db" -U $PGUSER -t program genomic | psql -h "$db" -U $PGUSER -d drs
    pg_dump -h "$db" -U $PGUSER -t drs_object genomic | psql -h "$db" -U $PGUSER -d drs
    pg_dump -h "$db" -U $PGUSER -t access_method genomic | psql -h "$db" -U $PGUSER -d drs
    pg_dump -h "$db" -U $PGUSER -t content_object genomic | psql -h "$db" -U $PGUSER -d drs
    psql --quiet -h "$db" -U $PGUSER -d genomic -c "DROP TABLE IF EXISTS content_object"
    psql --quiet -h "$db" -U $PGUSER -d genomic -c "DROP TABLE IF EXISTS access_method"
    psql --quiet -h "$db" -U $PGUSER -d genomic -c "ALTER TABLE variantfile DROP CONSTRAINT variantfile_drs_object_id_fkey"
    psql --quiet -h "$db" -U $PGUSER -d genomic -c "DROP TABLE IF EXISTS drs_object"
    psql --quiet -h "$db" -U $PGUSER -d genomic -c "DROP TABLE IF EXISTS program"
    echo "...done"
fi

psql --quiet -h "$db" -U $PGUSER -d drs -c "SELECT * from program limit 1"
if [[ $? -ne 0 ]]; then
    echo "initializing database..."
    createdb -h "$db" -U $PGUSER drs
    psql --quiet -h "$db" -U $PGUSER -a -d drs -f data/drs.sql >>setup_out.txt
    echo "...done"
fi
