#!/usr/bin/env bash
# Polystation deployment script
# Usage: ./deploy/deploy.sh [--rebuild]
set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

echo "=== Polystation Deployment ==="
echo "Directory: $PROJECT_DIR"
echo "Compose:   $COMPOSE_FILE"

# Pull latest code
if git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Pulling latest changes..."
    git pull --ff-only || echo "Warning: git pull failed (might have local changes)"
fi

# Build and start
if [[ "${1:-}" == "--rebuild" ]]; then
    echo "Rebuilding containers..."
    docker compose -f "$COMPOSE_FILE" build --no-cache
else
    echo "Building containers..."
    docker compose -f "$COMPOSE_FILE" build
fi

echo "Starting services..."
docker compose -f "$COMPOSE_FILE" up -d

# Wait for health check
echo "Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8420/api/markets/health > /dev/null 2>&1; then
        echo "Polystation is healthy!"
        echo ""
        echo "=== Services ==="
        echo "  Dashboard:   http://localhost:8420"
        echo "  Grafana:     http://localhost:3000 (admin/polystation)"
        echo "  Prometheus:  http://localhost:9090"
        echo "  Redis:       localhost:6379"
        exit 0
    fi
    sleep 2
done

echo "ERROR: Health check failed after 60 seconds"
docker compose -f "$COMPOSE_FILE" logs --tail=20 polystation
exit 1
