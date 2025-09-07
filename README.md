# Git Workflow & Project Setup
This document describes the branching workflow and how to run the OpenTelemetry Observability System.

## Branches
- **main** → Production-ready code (protected).
- **dev** → Integration branch where all features get merged.
- **dev-tushar**, **dev-kartikay** → Individual developer branches.

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

### 3. Always work on your own branch
For example, if you are Tushar:
```bash
git checkout dev-tushar
```

### 4. Keep your branch up to date with dev
Before starting new work:
```bash
# Fetch latest changes from remote
git fetch origin

# Switch to dev and pull latest
git checkout dev
git pull origin dev

# Switch back to your branch and rebase/merge dev
git checkout dev-tushar
git rebase dev   # preferred (clean history)
# OR
git merge dev    # if you want to keep merge commits
```

### 5. Do your work
```bash
# Make changes
git add .
git commit -m "your commit message"
git push origin dev-tushar
```

### 6. Create a Pull Request (PR)
- Go to GitHub/GitLab.
- Create a PR from `your branch → dev`.
- Wait for review and approval before merging.

### 7. Sync after PRs are merged
When someone else's changes are merged into dev:
```bash
git fetch origin
git checkout dev
git pull origin dev
git checkout dev-tushar
git rebase dev   # or git merge dev
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
# GROQ_API_KEY=your_groq_api_key_here
# SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
# SLACK_DEFAULT_CHANNEL=#troubleshooting
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

# Update dev
git checkout dev && git pull origin dev

# Rebase your branch on latest dev
git checkout dev-<yourname> && git rebase dev

# Push your branch
git push origin dev-<yourname>
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
- Always update your branch with latest dev before raising a PR
- Test both normal and error scenarios before pushing
- Ensure .env file has valid API keys for full functionality
- Use Docker Compose for consistent development environment
- Monitor #troubleshooting channel for error notifications

---

**Happy coding! When you hit `/boom`, magic happens in Slack! ✨**