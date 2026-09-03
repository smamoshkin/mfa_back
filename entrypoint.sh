#!/bin/sh
set -e

echo "Starting Gunicorn..."
cd /backend
export PYTHONPATH=/backend:$PYTHONPATH
# --timeout 180: тяжёлые экспорты Excel укладываются в дефолтные 30 сек,
# из-за чего gunicorn убивал воркеры посреди выгрузки (WORKER TIMEOUT)
exec gunicorn --bind 0.0.0.0:8000 --workers 4 --threads 2 \
    -k uvicorn.workers.UvicornWorker --forwarded-allow-ips='*' \
    --timeout 180 --graceful-timeout 30 \
    app.main:app
