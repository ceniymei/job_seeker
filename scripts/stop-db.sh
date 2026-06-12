#!/bin/bash

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Stopping Job Seeker Local PostgreSQL Database ==="

if ! command -v docker &> /dev/null; then
    echo "Error: docker is not installed."
    exit 1
fi

cd "$BASE_DIR"
echo "Running docker compose down..."
docker compose down

echo "Database stopped successfully."
