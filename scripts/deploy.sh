#!/bin/bash
set -e

# Trust the mounted repo location
git config --global --add safe.directory /mnt/inventory_management

cd /mnt/inventory_management/ || exit 1
echo "Pulling latest code..."
git fetch origin master
git reset --hard origin/master

echo "Restarting Docker Compose stack..."
docker-compose down
docker-compose up -d --build
