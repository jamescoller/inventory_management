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

echo "Restarting Docker Compose stack..."
docker-compose down
docker-compose up -d --build
