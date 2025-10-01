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

### Setup
```bash
# 1. Create .env file
cp .env.template .env

# 2. Edit .env with your credentials

# 3. Start the development environment
docker compose -f docker-compose.dev.yml up
```






