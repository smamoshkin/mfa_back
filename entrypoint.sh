#!/bin/sh
set -e

echo "Starting Gunicorn..."
cd /backend
export PYTHONPATH=/backend:$PYTHONPATH
exec gunicorn --bind 0.0.0.0:8000 --workers 4 --threads 2 \
    -k uvicorn.workers.UvicornWorker --forwarded-allow-ips='*' \
    app.main:app
