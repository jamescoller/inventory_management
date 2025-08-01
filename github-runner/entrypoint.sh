#!/bin/bash
set -e

REPO_URL="${REPO_URL:-https://github.com/jamescoller/inventory_management}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)}"
RUNNER_LABELS="${RUNNER_LABELS:-inventory-runner}"
GITHUB_PAT="${GITHUB_PAT:?GitHub PAT is required}"

echo "Requesting GitHub runner token..."
RUNNER_TOKEN=$(curl -s -X POST \
  -H "Authorization: token ${GITHUB_PAT}" \
  ${REPO_URL/github.com/api.github.com\/repos}/actions/runners/registration-token \
  | jq -r .token)

cd /home/runner

if [ -f .runner ]; then
  echo "Removing previous runner config..."
  ./config.sh remove --unattended --token "${RUNNER_TOKEN}" || true
fi

echo "Registering new runner..."
./config.sh \
  --url "${REPO_URL}" \
  --token "${RUNNER_TOKEN}" \
  --name "${RUNNER_NAME}" \
  --labels "${RUNNER_LABELS}" \
  --work _work \
  --unattended

echo "Starting runner..."
exec ./run.sh
