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

# .env is gitignored and lives in the workspace root — git reset --hard
# does not touch untracked/ignored files, so it persists across deploys.
if [ ! -f ".env" ]; then
  echo "ERROR: .env file not found in $(pwd). Copy .env.example and fill in values."
  exit 1
fi

echo "Restarting Docker Compose stack..."
docker compose down
docker compose up -d --build
