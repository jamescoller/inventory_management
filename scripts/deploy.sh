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

if [ ! -f "${HOME}/.env_inventory" ]; then
  echo "ERROR: ${HOME}/.env_inventory not found. Create it from .env.example on the runner host."
  exit 1
fi

if [ ! -f "${HOME}/inventory_db_dir/inventory_db.sqlite3" ]; then
  echo "ERROR: ${HOME}/inventory_db_dir/inventory_db.sqlite3 not found. Copy the database to the runner host."
  exit 1
fi

echo "Restarting Docker Compose stack..."
docker compose down
docker compose up -d --build
