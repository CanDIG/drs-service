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

psql --quiet -h "$db" -U $PGUSER -d drs -c "SELECT * from program limit 1"
if [[ $? -ne 0 ]]; then
    echo "initializing database..."
    createdb -h "$db" -U $PGUSER drs
    psql --quiet -h "$db" -U $PGUSER -a -d drs -f data/drs.sql >>setup_out.txt
    echo "...done"
fi

