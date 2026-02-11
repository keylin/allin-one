#!/bin/bash
set -e

# Ensure data directories exist
mkdir -p data/db data/media/videos data/media/images data/media/files data/reports data/logs

# Run database migrations
echo "Running database migrations..."
alembic upgrade head 2>/dev/null || echo "Alembic not configured yet, using create_all"

# Execute the main command
exec "$@"
