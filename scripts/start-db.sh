#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Get absolute path of the script's directory to locate docker-compose.yml correctly
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Starting Job Seeker Local PostgreSQL Database ==="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: docker is not installed. Please install Docker first."
    exit 1
fi

# Start PostgreSQL container
cd "$BASE_DIR"
echo "Running docker compose up..."
docker compose up -d

echo "--------------------------------------------------------"
echo "Database started successfully!"
echo "Connection DSN: postgresql://postgres:postgres@localhost:5432/job_seeker"
echo "You can set this in config.yaml or run:"
echo "  export DATABASE_URL=\"postgresql://postgres:postgres@localhost:5432/job_seeker\""
echo "--------------------------------------------------------"
