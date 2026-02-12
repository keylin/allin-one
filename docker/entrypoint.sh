#!/bin/bash
set -e

# Ensure data directories exist
mkdir -p data/db data/media/videos data/media/images data/media/files data/reports data/logs

# Run database migrations
echo "Running database migrations..."
alembic upgrade head || echo "Alembic migration failed, falling back to create_all"

# Execute the main command
exec "$@"
