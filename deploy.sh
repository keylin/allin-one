#!/bin/bash
set -e

REMOTE_HOST="${DEPLOY_HOST:-user@your-server}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/allin-one}"

echo "=== Deploying Allin-One to ${REMOTE_HOST}:${REMOTE_DIR} ==="

# 1. Sync files
echo ">> Syncing files..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude 'venv' \
    --exclude 'data' \
    --exclude 'node_modules' \
    --exclude '__pycache__' \
    --exclude '.env' \
    ./ ${REMOTE_HOST}:${REMOTE_DIR}/

# 2. Remote build & restart
echo ">> Building and restarting..."
ssh ${REMOTE_HOST} << EOF
cd ${REMOTE_DIR}
docker compose up -d --build
docker compose exec -T allin-one alembic upgrade head 2>/dev/null || true
docker image prune -f
echo "=== Deploy complete ==="
docker compose ps
EOF
