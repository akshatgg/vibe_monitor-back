# Git Workflow & Project Setup
This document describes the branching workflow and how to run the repo.
## 📚 Documentation

- [Project Structure & Architecture](./project-overview/project-structure.md) - Detailed overview of the codebase, data flows, and API endpoints
- [Database ER Diagram](./project-overview/er-diagram.md) - Entity-relationship diagram showing all database tables and relationships

## Branches
- **main** → Production-ready code (protected).

## Workflow

### 1. Clone the repository
```bash
git clone <repo-url>
cd vm-api
```

### 2. Set up remotes (if not already done)
```bash
git remote -v     # check remote
```

### 3. Create a branch for your Linear issue
When working on a Linear issue (e.g., VIB-32: Add new feature):
```bash
# Branch naming format: your_name/vib-{issue-number}-{issue-heading-kebab-case}
# Example for Shashi working on VIB-32 "Add Slack notifications":
git checkout -b shashi/vib-32-add-slack-notifications

# Example for Suhani working on VIB-55 "Update README":
git checkout -b suhani/vib-55-update-readme
```

### 4. Keep your branch up to date with main
Before starting new work:
```bash
# Fetch latest changes from remote
git fetch origin

# Switch to main and pull latest
git checkout main
git pull origin main

# Switch back to your branch and rebase on main
git checkout shashi/vib-32-add-slack-notifications
git rebase main   # preferred (clean history)
```

### 5. Do your work
```bash
# Make changes
git add .
git commit -m "your commit message"
git push origin yourname/vib-XX-issue-description
```

### 6. Create a Pull Request (PR)
- Go to GitHub.
- Create a PR from `your branch → main`.
- **PR Title Format:** `your_name/VIB-{number}: Description`
  - Example: `shashi/VIB-32: Add Slack notifications`
  - Example: `suhani/VIB-55: Update README with new workflow`
- Add Linear issue link in PR description
- Wait for review and approval before merging.

### 7. Sync after PRs are merged
When changes are merged into main:
```bash
git fetch origin
git checkout main
git pull origin main
# Delete your old feature branch
git branch -d shashi/vib-32-add-slack-notifications
# Create new branch for next issue
git checkout -b shashi/vib-45-new-feature
```

## Development Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.12+
- Poetry (will be auto-installed if not present)

### Quick Start (Recommended for Development)

Run uvicorn server on your host machine with hot reload, while infrastructure runs in Docker:

```bash
# Start dev environment (auto-installs dependencies, starts containers, runs uvicorn) 
## make the file executable first using 
chmod +x dev_start.sh

./dev_start.sh

# Stop dev environment
./dev_stop.sh
```

This setup provides:
- ✅ Fast hot reload for code changes
- ✅ Easy debugging (attach debugger directly)
- ✅ Full IDE integration
- ✅ Auto-installs Python dependencies
- ✅ Infrastructure services in Docker (Supabase, LocalStack)

### Services & Ports

| Service | URL | Description |
|---------|-----|-------------|
| **VM-API** | http://localhost:8000 | FastAPI application |
| **Supabase Studio** | http://localhost:3500 | Database management UI |
| **LocalStack** | http://localhost:4566 | AWS services emulation (SQS) |
| **Supabase DB** | postgresql://postgres:postgres@localhost:54322/postgres | PostgreSQL database |

### Alternative: Full Docker Setup

If you prefer to run everything in Docker (including the API):

```bash
# Run all services in Docker
docker compose -f docker-compose.dev.yml --profile full-docker up -d

# Stop all services
docker compose -f docker-compose.dev.yml down
```

### Manual Setup

```bash
# 1. Create .env file
cp .env.example .env

# 2. Edit .env with your credentials

# 3. Install dependencies
poetry install

# 4. Start infrastructure only
docker compose -f docker-compose.dev.yml up -d

# 5. Start uvicorn server
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```






