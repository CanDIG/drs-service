#!/usr/bin/env bash

set -Euo pipefail

export VAULT_URL=$VAULT_URL

if [[ -f "initial_setup" ]]; then
    sed -i s@\<OPA_URL\>@$OPA_URL@ config.ini
    sed -i s@\<VAULT_URL\>@$VAULT_URL@ config.ini
    sed -i s@\<POSTGRES_USERNAME\>@$POSTGRES_USERNAME@ config.ini

    bash create_db.sh
    rm initial_setup
fi

python -c "import candigv2_logging.logging
candigv2_logging.logging.initialize()"

# use the following for development
#python3 htsget_server/server.py

# use the following instead for production deployment
cd drs_server
gunicorn -k uvicorn.workers.UvicornWorker server:app
