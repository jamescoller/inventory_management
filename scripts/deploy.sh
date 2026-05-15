#!/usr/bin/env bash
set -e

# Navigate to the project root
cd "$(dirname "$0")/.." || exit 1

echo "Current directory: $(pwd)"
echo "Running deployment tasks..."

# Trust the runner workspace
git config --global --add safe.directory "$(pwd)"

echo "Pulling latest code..."
git fetch origin master
git reset --hard origin/master

# .env lives outside the workspace at a fixed path so the actions/checkout
# clean step can't wipe it. Copy it into the workspace before starting Docker.
ENV_SOURCE="${HOME}/.env_inventory"
if [ ! -f "$ENV_SOURCE" ]; then
  echo "ERROR: $ENV_SOURCE not found. Create it from .env.example on the runner host."
  exit 1
fi
cp "$ENV_SOURCE" .env

echo "Restarting Docker Compose stack..."
docker compose down
docker compose up -d --build
