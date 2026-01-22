#!/bin/bash

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Stopping development environment...${NC}"
echo ""

# Stop infrastructure containers
docker compose -f docker-compose.dev.yml down

echo ""
echo -e "${YELLOW}Killing processes on development ports...${NC}"

# Ports used by dev environment
PORTS=(8000 54322 3500 8080 8002 6379 4566)

for port in "${PORTS[@]}"; do
    if lsof -i :$port -t > /dev/null 2>&1; then
        echo "Killing processes on port $port..."
        lsof -i :$port -t | xargs -r kill -9 2>/dev/null
    fi
done

echo ""
echo -e "${GREEN}✓ Development environment stopped${NC}"
echo -e "${GREEN}✓ All development ports cleared${NC}"
