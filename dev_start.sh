#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   VM-API Development Environment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Install Python dependencies
echo -e "${YELLOW}[1/4] Installing Python dependencies...${NC}"

# Check for Python 3.12
if ! command -v python3.12 &> /dev/null; then
    echo -e "${YELLOW}Python 3.12 not found. Please install it first.${NC}"
    exit 1
fi

# Check for poetry in common locations
POETRY_CMD=""
if command -v poetry &> /dev/null; then
    POETRY_CMD="poetry"
elif [ -f "$HOME/.local/bin/poetry" ]; then
    POETRY_CMD="$HOME/.local/bin/poetry"
elif [ -f "$HOME/.local/share/pypoetry/venv/bin/poetry" ]; then
    POETRY_CMD="$HOME/.local/share/pypoetry/venv/bin/poetry"
fi

# Install poetry if not found
if [ -z "$POETRY_CMD" ]; then
    echo -e "${YELLOW}Poetry not found. Installing poetry...${NC}"
    curl -sSL https://install.python-poetry.org | python3.12 -

    # Set poetry command after installation
    if [ -f "$HOME/.local/bin/poetry" ]; then
        POETRY_CMD="$HOME/.local/bin/poetry"
    elif [ -f "$HOME/.local/share/pypoetry/venv/bin/poetry" ]; then
        # Create symlink if it doesn't exist
        mkdir -p "$HOME/.local/bin"
        ln -sf "$HOME/.local/share/pypoetry/venv/bin/poetry" "$HOME/.local/bin/poetry"
        POETRY_CMD="$HOME/.local/bin/poetry"
    else
        echo -e "${YELLOW}Poetry installation failed.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Poetry installed successfully${NC}"
fi

# Configure poetry to use Python 3.12
echo -e "${YELLOW}Configuring poetry to use Python 3.12...${NC}"
$POETRY_CMD env use python3.12

# Install dependencies
echo -e "${YELLOW}Installing project dependencies...${NC}"
$POETRY_CMD install
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}Poetry install failed. Please check your pyproject.toml${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Step 2: Start infrastructure containers
echo -e "${YELLOW}[2/4] Starting infrastructure containers (Supabase, LocalStack)...${NC}"
docker compose -f docker-compose.dev.yml up -d

# Wait for containers to be healthy
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
sleep 5

# Check LocalStack health
echo -e "${YELLOW}Checking LocalStack health...${NC}"
for i in {1..30}; do
    if curl -sf http://localhost:4566/_localstack/health | grep -q '"sqs": "running"'; then
        echo -e "${GREEN}✓ LocalStack is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}Warning: LocalStack may not be fully ready${NC}"
    fi
    sleep 2
done

# Check Supabase DB
echo -e "${YELLOW}Checking Supabase DB...${NC}"
for i in {1..30}; do
    if docker exec vm-api-supabase-db-1 pg_isready -U postgres &> /dev/null 2>&1; then
        echo -e "${GREEN}✓ Supabase DB is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}Warning: Supabase DB may not be fully ready${NC}"
    fi
    sleep 2
done

echo -e "${GREEN}✓ Infrastructure containers started${NC}"
echo ""

# Step 3: Set environment variables for local development
echo -e "${YELLOW}[3/4] Setting up environment variables...${NC}"

# Load other environment variables from .env file if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

 # Override for host-run services
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:54322/postgres"
export AWS_ENDPOINT_URL="http://localhost:4566"
export SQS_QUEUE_URL="http://localhost:4566/000000000000/vm-api-queue"
export AWS_REGION="us-east-1"
# DO NOT export AWS credentials - let boto3 use ~/.aws/credentials for real AWS
# LocalStack SQS will work without credentials when using AWS_ENDPOINT_URL
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}"

# Owner Role Configuration (for two-stage STS AssumeRole)
# Set these if you want to test two-stage authentication locally
export OWNER_ROLE_ARN="${OWNER_ROLE_ARN:-}"
export OWNER_ROLE_EXTERNAL_ID="${OWNER_ROLE_EXTERNAL_ID:-}"

export ENVIRONMENT="local"

echo -e "${GREEN}✓ Environment configured${NC}"
echo ""

# Step 4: Start uvicorn server
echo -e "${YELLOW}[4/4] Starting uvicorn server...${NC}"
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Server starting on http://localhost:8000${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Services available:${NC}"
echo -e "  • API: http://localhost:8000"
echo -e "  • Supabase Studio: http://localhost:3500"
echo -e "  • LocalStack: http://localhost:4566"
echo -e "  • Supabase DB: postgresql://postgres:postgres@localhost:54322/postgres"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Start uvicorn with poetry
$POETRY_CMD run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
