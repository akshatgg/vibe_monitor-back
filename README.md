# Git Workflow & Project Setup
This document describes the branching workflow and how to run the OpenTelemetry Observability System.

## 📚 Documentation

- [Project Structure & Architecture](./project-overview/project-structure.md) - Detailed overview of the codebase, data flows, and API endpoints
- [Database ER Diagram](./project-overview/er-diagram.md) - Entity-relationship diagram showing all database tables and relationships

## Branches
- **main** → Production-ready code (protected).
- **dev** → Integration branch where all features get merged.

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

## Project Setup & Testing

### Prerequisites
- Python 3.10+ with virtual environment
- Node.js 18+
- Docker & Docker Compose
- Groq API key
- Slack Bot token

### Environment Setup
```bash
# 1. Create .env file
cp .env.template .env

# 2. Edit .env with your credentials:
# (Add any required environment variables here)
```

### Development Setup

#### Terminal 1 - FastAPI Backend
```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI backend
cd vm-api
uvicorn app.main:app --port 8000 --reload
```

#### Terminal 2 - Node.js Demo App
```bash
# Navigate to demo app
cd vm-api/demo_user

# Install dependencies
npm install

# Start Node.js app
node index.js
```


### Testing the System

#### Test Normal Operation (No Slack notification)
```bash
curl http://localhost:3001/test
# Response: {"message": "Test endpoint", "timestamp": "..."}
# No error = No Slack notification
```

#### Test Error Detection (Triggers Slack notification)
```bash
curl http://localhost:3001/boom
# Response: {"error": "Something went wrong"}
# ✨ Voila! Check #troubleshooting channel for AI-powered error analysis
```

### What Happens During Error Detection
1. **Error Triggered**: `/boom` endpoint returns 500 status
2. **Telemetry Collection**: OpenTelemetry captures logs, traces, metrics
3. **Error Detection**: FastAPI backend detects HTTP 500 in logs
4. **RCA Analysis**: Groq AI analyzes error with telemetry context
5. **Slack Notification**: Progressive updates in #troubleshooting:
   - Initial error alert with details
   - "Analysing Error..." → "Reading Code Repository..." → "Investigating Root Cause..." → "Suggesting Next Steps..."
   - Final analysis with root cause and fix recommendations

### Available Endpoints
- `GET /` - Returns "Client app running"
- `GET /test` - Test endpoint (no error)
- `GET /boom` - Error endpoint (triggers 500)
- `GET /health` - Backend health check






## Quick Command Reference

### Git Commands
```bash
# Get latest changes
git fetch origin

# Update main
git checkout main && git pull origin main

# Create new branch for Linear issue VIB-XX
git checkout -b yourname/vib-XX-issue-description

# Rebase your branch on latest main
git checkout yourname/vib-XX-issue-description && git rebase main

# Push your branch
git push origin yourname/vib-XX-issue-description
```

### Development Commands
```bash
# Manual setup
uvicorn app.main:app --port 8000 --reload  # Backend
node index.js                              # Demo app


# Testing
curl http://localhost:3001/test            # Normal request
curl http://localhost:3001/boom            # Error request
```

## Notes
- Never commit directly to main or dev
- Always create a branch from main for each Linear issue
- Branch naming: `yourname/vib-{number}-{description-kebab-case}`
- PR title format: `yourname/VIB-{number}: Description`
- Always update your branch with latest main before raising a PR
- Test both normal and error scenarios before pushing
- Ensure .env file has valid API keys for full functionality
- Use Docker Compose for consistent development environment
- Monitor #troubleshooting channel for error notifications

### Poetry Package Management
```bash
# Install a new package
poetry add <package name>

# Remove a package
poetry remove <package name>

# Sync pyproject.toml with poetry.lock
poetry lock
```

---

**Happy coding! When you hit `/boom`, magic happens in Slack! ✨**
