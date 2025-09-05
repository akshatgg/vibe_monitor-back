# Git Workflow
This document describes the branching and PR workflow for this repository.

## Branches
- **main** → Production-ready code (protected).
- **dev** → Integration branch where all features get merged.
- **dev-tushar**, **dev-kartikay** → Individual developer branches.

## Workflow

### 1. Clone the repository
```bash
git clone <repo-url>
cd <repo-folder>
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
- Create a PR from ```your branch → dev. ```
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

## Quick Command Reference
Get latest changes
```
git fetch origin
```

Update dev
```
git checkout dev

git pull origin dev
```

# Rebase your branch on latest dev
```
git checkout dev-<yourname>
git rebase dev
```

# Push your branch
```
git push origin dev-<yourname>
```

## Notes
- Never commit directly to main or dev.
- Always update your branch with latest dev before raising a PR.
- Resolve conflicts locally before pushing.
- Use rebase for cleaner history (preferred).

---
