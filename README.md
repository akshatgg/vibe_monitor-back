# Git Workflow & Project Setup
This document describes the branching workflow and how to run the repo.
## 📚 Documentation

- [Project Structure & Architecture](./project-overview/project-structure.md) - Detailed overview of the codebase, data flows, and API endpoints
- [Database ER Diagram](./project-overview/er-diagram.md) - Entity-relationship diagram showing all database tables and relationships
- [Dev Environment Setup](../vm-infra/README_DEV_SETUP.md) - Complete guide to set up dev environment infrastructure

## Branches
- **main** → Production environment (protected) - deploys to `api.vibemonitor.ai`
- **dev** → Development environment - deploys to `dev.vibemonitor.ai`

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

## Deployment

### Automated Deployments via GitHub Actions

The project uses branch-based deployments with GitHub Actions:

| Branch | Environment | ECS Cluster | Service | URL |
|--------|-------------|-------------|---------|-----|
| `main` | Production | `vm-prod` | `vm-api-svc-prod` | https://api.vibemonitor.ai |
| `dev` | Development | `vm-dev` | `vm-api-svc-dev` | https://dev.vibemonitor.ai |

**How it works:**
- Push to `main` branch → GitHub Actions automatically deploys to production
- Push to `dev` branch → GitHub Actions automatically deploys to dev environment

**Deployment workflow:**
1. Build Docker image with environment-specific tag (`prod-{sha}` or `dev-{sha}`)
2. Push to ECR repository
3. Render task definition from `taskdef.template.json` with environment variables
4. Register new ECS task definition
5. Update ECS service with new task definition
6. Wait for service to stabilize

**Infrastructure:**
- All infrastructure setup scripts and documentation are in the `vm-infra` repository
- See [Dev Environment Setup Guide](../vm-infra/README_DEV_SETUP.md) for complete infrastructure setup

**Note:** Migrations run automatically during container startup via `entrypoint.sh` - no manual intervention needed!

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

## Adding Environment Variables

When you need to add a new environment variable to the project, you must update **4 things** to ensure it works in local development and all deployed environments:

### 1. `.env.example`
Add your variable with a placeholder value:
```bash
NEW_VARIABLE_NAME=placeholder_value_here
```

### 2. `app/core/config.py`
Add the variable to the `Settings` class:
```python
class Settings(BaseSettings):
    # ... existing variables ...
    NEW_VARIABLE_NAME: Optional[str] = None  # Description of what it does
```

### 3. `taskdef.template.json`
Add the variable to the `secrets` array using the environment placeholder:
```json
{"name": "NEW_VARIABLE_NAME", "valueFrom": "/vm-api-ENV_PLACEHOLDER/new-variable-name"}
```

**Note:** The `valueFrom` path uses kebab-case and includes `ENV_PLACEHOLDER` which gets replaced with `prod` or `dev` during deployment.

### 4. AWS Systems Manager Parameter Store
Add the variable to both production and dev environments:
```bash
# Production
aws ssm put-parameter --name '/vm-api-prod/new-variable-name' --value 'production-value' --type SecureString --region us-west-1

# Dev
aws ssm put-parameter --name '/vm-api-dev/new-variable-name' --value 'dev-value' --type SecureString --region us-west-1
```

### Example
For a new `GITHUB_WEBHOOK_SECRET` variable:
- ✅ `.env.example`: `GITHUB_WEBHOOK_SECRET=your_webhook_secret`
- ✅ `app/core/config.py`: `GITHUB_WEBHOOK_SECRET: Optional[str] = None`
- ✅ `taskdef.template.json`: `{"name": "GITHUB_WEBHOOK_SECRET", "valueFrom": "/vm-api-ENV_PLACEHOLDER/github-webhook-secret"}`
- ✅ SSM (prod): `/vm-api-prod/github-webhook-secret`
- ✅ SSM (dev): `/vm-api-dev/github-webhook-secret`

## Setting Up GitHub Webhooks

To enable GitHub integration features (install/uninstall tracking, suspension handling), configure webhooks in your GitHub App settings:

### 1. Navigate to GitHub App Settings
Go to your GitHub App settings: `https://github.com/settings/apps/[your-app-name]`

### 2. Configure Webhook URL
Set the Webhook URL to point to your API endpoint:
```
https://your-api.com/api/v1/github/webhook
```

**For local development with ngrok:**
```bash
# Start ngrok tunnel
ngrok http 8000

# Use the ngrok URL in GitHub App settings
https://abc123.ngrok.io/api/v1/github/webhook
```

### 3. Set Webhook Secret
Use the value from your `GITHUB_WEBHOOK_SECRET` environment variable. This secret is used to verify webhook signatures for security.

**Important:** The same secret must be configured in both:
- Your `.env` file (`GITHUB_WEBHOOK_SECRET=your_secret_here`)
- GitHub App webhook settings

### 4. Subscribe to Events
Enable the following webhook events:
- ✅ **Installation** (`installation`) - Tracks when users install/uninstall the app
- ✅ **Installation repositories** (`installation_repositories`) - Tracks repository access changes

### 5. Enable Webhook
Set webhook status to **Active**

### 6. Test Your Webhook
GitHub provides a "Recent Deliveries" tab where you can:
- View webhook payloads sent to your API
- See response status codes
- Redeliver webhooks for testing

### Webhook Event Flow

**When a user uninstalls the app:**
1. User goes to GitHub → Settings → Applications → Uninstall "your-app"
2. GitHub sends `POST /api/v1/github/webhook` with `{"action": "deleted"}`
3. Webhook signature is verified using `GITHUB_WEBHOOK_SECRET`
4. Integration is deleted from database
5. Frontend now shows "not connected" ✅

**Supported webhook events:**
- `installation.deleted` - User uninstalled the app → Delete integration from DB
- `installation.suspend` - App was suspended → Mark integration as inactive
- `installation.unsuspend` - App was unsuspended → Reactivate integration with new token
- `installation_repositories.*` - Repository access changed → Logged for awareness

## Database Migrations

This project uses **Alembic** for database schema migrations. Migrations ensure safe and version-controlled database changes.

### Why Migrations?

- ✅ **Version control for database schema** - Track all schema changes in git
- ✅ **Safe production deployments** - Apply changes without data loss
- ✅ **Rollback capability** - Revert problematic changes
- ✅ **Team collaboration** - Everyone stays in sync with schema changes

### Running Migrations

**Important**: Always run migrations before starting the application in production.

```bash
# Apply all pending migrations
alembic upgrade head

# Check current migration version
alembic current

# View migration history
alembic history
```

### Creating New Migrations

When you modify database models in `app/models.py`, you **must** create a migration:

```bash
# 1. Make changes to models in app/models.py

# 2. Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# 3. Review the generated migration file in alembic/versions/
# 4. Edit if needed to ensure it's correct

# 5. Test the migration locally
alembic upgrade head    # Apply migration
alembic downgrade -1    # Test rollback
alembic upgrade head    # Re-apply

# 6. Commit the migration file with your code changes
git add alembic/versions/*.py
git commit -m "Add migration for [your changes]"
```

### Migration Best Practices

1. **Always review auto-generated migrations** - Alembic's autogenerate is smart but not perfect
2. **Add `server_default` for NOT NULL columns** - Prevents errors with existing data
3. **Test both upgrade and downgrade** - Ensure migrations are reversible
4. **One migration per feature** - Keep migrations focused and atomic
5. **Never edit applied migrations** - Create a new migration to fix issues

### Common Migration Scenarios

#### Adding a new column (nullable)
```python
# Auto-generated is usually fine
op.add_column('table_name', sa.Column('new_column', sa.String(), nullable=True))
```

#### Adding a new column (NOT NULL)
```python
# Must provide server_default for existing rows
op.add_column(
    'table_name',
    sa.Column('new_column', sa.Boolean(), nullable=False, server_default=sa.text('true'))
)
```

#### Removing a column
```python
op.drop_column('table_name', 'column_name')
```

### Production Deployment

**Migrations run automatically in production!** 🎉

The Docker container includes an `entrypoint.sh` script that:
1. Runs `alembic upgrade head` to apply all pending migrations
2. Starts the application only if migrations succeed
3. Exits with error code if migrations fail (prevents bad deployments)

This means:
- ✅ No manual migration steps needed for production deployments
- ✅ Database schema always matches deployed code
- ✅ Safe rollouts (ECS won't deploy if migrations fail)
- ✅ Zero-downtime deployments (Alembic handles concurrent migration attempts safely)

**How it works:**
```bash
# Dockerfile CMD runs entrypoint.sh automatically:
./entrypoint.sh
  ├── alembic upgrade head  # Apply migrations
  └── uvicorn app.main:app  # Start application (only if migrations succeed)
```

**Important notes:**
- First container to start acquires database lock and runs migrations
- Other containers wait for migrations to complete
- If migration fails, container exits and ECS rolls back deployment
- Migrations are idempotent - safe to run multiple times

### ECS Production Configuration

**Health Check Configuration:**

This deployment uses **ALB target group health checks** (not container-level health checks):
- Health check path: `/health`
- Health check protocol: HTTP
- Grace period: 60 seconds (configured in ECS service)
- Interval: 15 seconds
- Healthy threshold: 2 consecutive successes
- Unhealthy threshold: 3 consecutive failures

**Recommended grace period settings:**
- Default: 60 seconds (sufficient for most migrations)
- If migrations take >30 seconds: Increase to 90-120 seconds
- Monitor CloudWatch logs during first deployment to verify migration duration

**Why ALB health checks instead of container health checks:**
- ALB already performs HTTP checks on `/health` endpoint
- Avoids unnecessary dependencies (curl) in container
- Simpler configuration and troubleshooting

### Migration Rollback Strategy

**What happens during rollback:**
- ECS can roll back to previous task definition (previous code)
- Database migrations are **forward-only** and cannot be automatically rolled back
- This creates a potential state mismatch if migrations ran but deployment failed

**Best practices:**
1. **Make migrations backward-compatible:**
   - When adding columns: make them nullable initially
   - When removing columns: deprecate first, remove later
   - Never rename columns in a single migration

2. **Example backward-compatible migration:**
   ```python
   # GOOD: Add nullable column first
   op.add_column('users', sa.Column('new_field', sa.String(), nullable=True))

   # Later, after deployment succeeds, make it non-null if needed
   op.alter_column('users', 'new_field', nullable=False)
   ```

3. **If deployment fails after migrations:**
   - Old code must still work with new schema
   - Test migrations in staging with old code first
   - Have a rollback SQL script ready for destructive changes

4. **Emergency rollback procedure:**
   ```bash
   # If you must rollback a migration manually:
   alembic downgrade -1  # Rollback one migration
   alembic current       # Verify current version
   ```

### Troubleshooting

**"Target database is not up to date"**
```bash
# This means you have unapplied migrations. Run:
alembic upgrade head
```

**"Can't locate revision"**
```bash
# Database and migration files are out of sync. Check:
alembic current  # What version DB thinks it's at
alembic history  # What migrations exist
```

**Fresh database setup**
```bash
# For a completely new database:
alembic upgrade head  # Creates all tables and applies all migrations
```






