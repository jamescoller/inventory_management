#!/usr/bin/env bash
set -e

# Navigate to the project root
cd "$(dirname "$0")/.." || exit 1

echo "Current directory: $(pwd)"
echo "Running deployment tasks..."

# your deployment commands here

# Trust the mounted repo location
git config --global --add safe.directory "$(pwd)"

echo "Pulling latest code..."
git fetch origin master
git reset --hard origin/master

# deploy.sh

ENV_DEST="./.env"
ENV_SOURCE="/home/runner/.env_shared"

echo "Linking .env from shared volume"
ln -sf "$ENV_SOURCE" "$ENV_DEST"

echo "Restarting Docker Compose stack..."
docker-compose down
docker-compose up -d --build
