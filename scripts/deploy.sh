#!/bin/bash
set -e

echo "Pulling latest code..."
git fetch origin master
git reset --hard origin/master

echo "Restarting Docker Compose stack..."
docker compose down
docker compose up -d --build
