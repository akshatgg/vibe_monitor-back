# 🚀 VM-API Setup Guide

Complete setup guide for VM-API with Slack bot integration and monitoring stack.

---

## 📋 What is VM-API?

**VM-API** (VibeMonitor API) is a monitoring platform that:

- 📊 Queries metrics from Prometheus (CPU, memory, availability)
- 📝 Queries logs from Loki (error logs, search)
- 💬 Integrates with Slack for bot interactions
- 🔐 Multi-tenant with workspace isolation
- 🤖 AI-powered root cause analysis

---

## ⚡ Quick Start

### Prerequisites

**Required Software:**
- Docker & Docker Compose
- Python 3.12+
- Poetry
- Git

**Required Accounts:**
- Slack workspace
- Ngrok account (free)

---

## 🏗️ Architecture

```
┌─────────────────────────────────┐
│      Your Local Machine         │
│                                 │
│  ┌──────────┐  ┌──────────┐   │
│  │  LGTM    │  │  VM-API  │   │
│  │ (Grafana │◄─┤ (FastAPI)│   │
│  │ Prom/Loki│  │ Port 8000│   │
│  └──────────┘  └────┬─────┘   │
│                     │          │
│              ┌──────▼─────┐    │
│              │ PostgreSQL │    │
│              └────────────┘    │
└─────────────────┬───────────────┘
                  │
           ┌──────▼──────┐
           │    Ngrok    │ (Tunnel)
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │  Internet   │
           │ (Slack API) │
           └─────────────┘
```

---

## 📝 Setup Steps

### 1️⃣ Clone & Setup VM-API

```bash
# Clone repository and navigate to vm-api directory
git clone <repo-url>
cd vm-api

# Copy environment file
cp .env.example .env

# Install dependencies
poetry install

# Start VM-API with Docker Compose
docker compose -f docker-compose.dev.yml --profile full-docker up -d

# Verify running
curl http://localhost:8000/health
# Expected: {"status":"healthy"}
```

---

### 2️⃣ Start Monitoring Stack (LGTM)

**Step 1: Clone LGTM Repository**

```bash
# Clone LGTM stack
git clone <lgtm-repo-url>
cd lgtm
```

**Step 2: Clone Service Repositories**

```bash
# Clone auth, desk, and marketplace services
git clone <auth-repo-url>
git clone <desk-repo-url>
git clone <marketplace-repo-url>
```

**Step 3: Copy Service Data to LGTM Structure**

```bash
# Copy auth data to lgtm/services/auth
cp -r auth/* lgtm/services/auth/

# Copy desk data to lgtm/services/servicedesk
cp -r desk/* lgtm/services/servicedesk/

# Copy marketplace data to lgtm/services/marketplace
cp -r marketplace/* lgtm/services/marketplace/
```

**Step 4: Start LGTM Stack**

```bash
# Navigate to LGTM directory and start
cd lgtm
docker compose up -d

# Verify services
docker ps  # Should show grafana, prometheus, loki

# Access Grafana
# Browser: http://localhost:3000
# Login: admin/admin
```

**Create Grafana API Token:**

1. Grafana → Administration → Service Accounts
2. Click "Add service account" → Name: `vm-api`, Role: `Admin`
3. Click "Add service account token" → Generate
4. **Copy token** (starts with `glsa_...`) - save it!

---

### 3️⃣ Setup Ngrok

```bash
# Install ngrok (example for Linux)
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar -xvzf ngrok-v3-stable-linux-amd64.tgz
sudo mv ngrok /usr/local/bin/

# Sign up at https://ngrok.com and get authtoken
ngrok config add-authtoken YOUR_AUTHTOKEN

# Start ngrok tunnel
ngrok http 8000

# Copy your public URL (e.g., https://abc123.ngrok.io)
```

**Test tunnel:**
```bash
curl https://YOUR_NGROK_URL.ngrok.io/health
```

---

### 4️⃣ Create Slack Bot

**Step 1: Create App**

1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. App Name: `vm-test` (or your choice)
4. Select your workspace

**Step 2: Add Bot Scopes**

Go to **OAuth & Permissions** → Bot Token Scopes:

Add these 7 scopes:
```
app_mentions:read
channels:history
channels:read
chat:write
chat:write.public
commands
groups:read
```

**Step 3: Add Redirect URL**

Still in **OAuth & Permissions** → Redirect URLs:

Add:
```
https://YOUR_NGROK_URL.ngrok.io/api/v1/slack/oauth/callback
```

**Step 4: Enable Event Subscriptions**

Go to **Event Subscriptions** → Toggle ON:

Request URL:
```
https://YOUR_NGROK_URL.ngrok.io/api/v1/slack/events
```

Wait for "Verified ✓"

Subscribe to bot events:
```
app_mention
message.channels
message.groups
message.im
```

**Step 5: Enable Interactivity**

Go to **Interactivity & Shortcuts** → Toggle ON:

Request URL:
```
https://YOUR_NGROK_URL.ngrok.io/api/v1/slack/interactivity
```

**Step 6: Get Credentials**

Go to **Basic Information** → App Credentials:

Copy these values:
- **Signing Secret**: Found under "App Credentials" section
- **Client ID**: Found under "App Credentials" section
- **Client Secret**: Click "Show" to reveal, then copy

**Step 7: Create Incoming Webhook (Optional)**

If you want to send notifications to a specific channel:

1. Go to **Incoming Webhooks** (left sidebar)
2. Toggle **"Activate Incoming Webhooks"** to ON
3. Click **"Add New Webhook to Workspace"**
4. Select a channel (e.g., `#general` or `#vm-test`)
5. Click **"Allow"**
6. Copy the **Webhook URL** (looks like: `https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXX`)

---

### 5️⃣ Update VM-API Configuration

Update these lines in your `.env` file:

```bash
# Slack Integration
SLACK_SIGNING_SECRET=your_signing_secret_here
SLACK_WEBHOOK_URL=your_slack_webhook_url_here
SLACK_CLIENT_ID=your_client_id_here
SLACK_CLIENT_SECRET=your_client_secret_here

# Update API base URL to ngrok
API_BASE_URL=https://YOUR_NGROK_URL.ngrok.io
```

**Restart VM-API:**
```bash
docker compose -f docker-compose.dev.yml --profile full-docker down
docker compose -f docker-compose.dev.yml --profile full-docker up -d
```

---

### 6️⃣ Setup Database

**Connect to database:**
```bash
docker exec -it $(docker ps -q -f name=supabase-db) psql -U postgres -d postgres
```

**Create test user:**
```sql
INSERT INTO users (id, email, name, created_at, updated_at)
VALUES (
  '26490a71-98b7-4da4-8ead-2ade4f4f1d53',
  'test@example.com',
  'Test User',
  NOW(),
  NOW()
) ON CONFLICT (email) DO NOTHING;
```

**Add user to workspace 101:**
```sql
INSERT INTO memberships (id, user_id, workspace_id, role, created_at)
VALUES (
  gen_random_uuid(),
  '26490a71-98b7-4da4-8ead-2ade4f4f1d53',
  '101',
  'OWNER',
  NOW()
);
```

**Add Grafana integration:**
```sql
INSERT INTO grafana_integrations (
  id,
  vm_workspace_id,
  grafana_url,
  api_token,
  created_at,
  updated_at
) VALUES (
  gen_random_uuid(),
  '101',
  'http://localhost:3000',
  'YOUR_GRAFANA_TOKEN_HERE',  -- Token from step 2
  NOW(),
  NOW()
);
```

**Exit database:**
```sql
\q
```

---

### 7️⃣ GitHub App Setup (Optional)

This allows VM-API to access GitHub repositories. Skip if you don't need GitHub integration.

---

**Step 1: Create GitHub App**

1. Go to: https://github.com/settings/apps
2. Click **"New GitHub App"**
3. Fill in:

**Basic Information:**
```
GitHub App name: vibemonitor-dev-yourname
Homepage URL: http://localhost:3000
```

**Callback URL:**
```
http://localhost:8000/api/v1/github/callback
```

**Post Installation (Setup URL):**
```
http://localhost:3000/github/callback
```

**Webhook:**
- Check **"Active"**
- **Webhook URL:**
```
https://YOUR_NGROK_URL.ngrok.io/api/v1/github/webhook
```

**Permissions:**
- Repository permissions:
  - Contents: Read-only
  - Metadata: Read-only (auto-selected)

**Where can this app be installed:**
- ✅ **Any account** (make it public)

4. Click **"Create GitHub App"**

---

**Step 2: Get GitHub Credentials**

**App ID:** Copy from top of page (e.g., `2111937`)

**Client ID:** Copy from "About" section (e.g., `Iv23liI8SDc4kEN1eIGo`)

**Generate Private Key:**
1. Scroll to **"Private keys"**
2. Click **"Generate a private key"**
3. A `.pem` file downloads

---

**Step 3: Convert Private Key to Base64**

```bash
# Navigate to Downloads
cd ~/Downloads

# Convert PEM to base64 (single line)
cat vibemonitor-dev-yourname.*.private-key.pem | base64 -w 0

# Copy the output (very long string)
```

---

**Step 4: Update VM-API .env**

Add these lines to your `.env` file:
```bash
# GitHub app
GITHUB_APP_NAME=vibemonitor-dev-yourname
GITHUB_APP_ID=2111937
GITHUB_PRIVATE_KEY_PEM=LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLS...
GITHUB_CLIENT_ID=Iv23liI8SDc4kEN1eIGo
```

---

**Step 5: Install GitHub App**

1. Go to: https://github.com/settings/apps
2. Click your app name
3. Click **"Install App"** (left sidebar)
4. Click **"Install"** next to your username
5. Select repositories:
   - ✅ Only select repositories (choose test repos)
   - Or: All repositories
6. Click **"Install"**

---

### 8️⃣ Install Slack Bot to Workspace

**Generate JWT token:**
```bash
python3 -c "
import jwt
from datetime import datetime, timedelta, timezone

token = jwt.encode({
    'sub': '26490a71-98b7-4da4-8ead-2ade4f4f1d53',
    'email': 'test@example.com',
    'exp': datetime.now(timezone.utc) + timedelta(weeks=1),
    'type': 'access'
}, 'your-super-secret-jwt-key-change-in-production', algorithm='HS256')

print(token)
"
```

**Get OAuth URL:**
```bash
curl "http://localhost:8000/api/v1/slack/install?workspace_id=101" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Open the `oauth_url` in browser** and authorize the app.

---

## ✅ Testing

### Test 1: Authentication
```bash
curl "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Test 2: Metrics Health
```bash
curl "http://localhost:8000/api/v1/metrics/health" \
  -H "workspace-id: <workspace_id>"
```

### Test 3: Slack Bot

In Slack:
1. Create channel `#vm-test`
2. Invite bot: `/invite @vm-test`
3. Test: `@vm-test hello`

---

## 🔄 Daily Workflow

**Terminal 1 - LGTM Stack:**
```bash
cd /path/to/lgtm
docker compose up -d
```

**Terminal 2 - Ngrok:**
```bash
ngrok http 8000
# Copy new URL if changed, update Slack app settings
```

**Terminal 3 - VM-API:**
```bash
cd /path/to/vm-api
docker compose -f docker-compose.dev.yml --profile full-docker up -d
```

**Quick Health Check:**
```bash
curl http://localhost:8000/health
curl http://localhost:3000/api/health
curl https://YOUR_NGROK_URL.ngrok.io/health
```

---

## 🐛 Common Issues

### Issue: Slack Events Not Verified

**Solution:**
1. Verify VM-API is running
2. Verify ngrok tunnel is active
3. Check `SLACK_SIGNING_SECRET` in `.env` is correct
4. Restart VM-API: `./dev_stop.sh && ./dev_start.sh`

### Issue: Invalid Slack Scope Error

**Solution:**
Make sure Slack app has EXACTLY these 7 scopes:
```
app_mentions:read
channels:history
channels:read
chat:write
chat:write.public
commands
groups:read
```

### Issue: Grafana Connection Failed

**Solution:**
```bash
# Test Grafana API token
curl "http://localhost:3000/api/datasources" \
  -H "Authorization: Bearer YOUR_GRAFANA_TOKEN"

# If fails, regenerate token in Grafana
# Update database: grafana_integrations table
```

### Issue: Ngrok URL Changed

**When ngrok restarts, update:**
1. Slack app URLs (OAuth, Events, Interactivity)
2. `.env` file: `API_BASE_URL`
3. Restart VM-API

---

## 📊 API Endpoints

### Authentication
```bash
GET /api/v1/auth/me
Header: Authorization: Bearer <jwt_token>
```

### Metrics
```bash
GET /api/v1/metrics/health
Header: workspace-id: 101

GET /api/v1/metrics/labels
GET /api/v1/metrics/labels/job/values
GET /api/v1/metrics/cpu?service_name=express-app
GET /api/v1/metrics/availability?service_name=express-app
```

### Logs
```bash
GET /api/v1/logs/labels
GET /api/v1/logs/service/express-app
GET /api/v1/logs/errors?service_name=express-app
```

### Slack
```bash
GET /api/v1/slack/install?workspace_id=101
Header: Authorization: Bearer <jwt_token>
```

---

## 🔗 Useful Commands

**Generate JWT Token:**
```bash
python3 -c "import jwt; from datetime import datetime, timedelta, timezone; print(jwt.encode({'sub': 'USER_ID', 'email': 'user@example.com', 'exp': datetime.now(timezone.utc) + timedelta(weeks=1), 'type': 'access'}, 'your-super-secret-jwt-key-change-in-production', algorithm='HS256'))"
```

**Check Database:**
```bash
docker exec -it $(docker ps -q -f name=supabase-db) psql -U postgres -d postgres
```

**View Logs:**
```bash
# VM-API logs (if running in docker)
docker logs -f vm-api

# Ngrok inspection
# Open: http://127.0.0.1:4040
```

**Stop Everything:**
```bash
# VM-API
docker compose -f docker-compose.dev.yml --profile full-docker down

# LGTM
cd /path/to/lgtm
docker compose down

# Ngrok (Ctrl+C in terminal)
```

---

## 📚 Additional Resources

- **API Docs:** http://localhost:8000/docs (when running)
- **Monitoring Dashboard:** `MONITORING_DASHBOARD.md`
- **Grafana:** https://grafana.com/docs/
- **Prometheus:** https://prometheus.io/docs/
- **Slack API:** https://api.slack.com/

---

## ✨ Summary Checklist

- [ ] VM-API running on port 8000
- [ ] LGTM stack running (Grafana, Prometheus, Loki)
- [ ] Ngrok tunnel active
- [ ] Slack app created with correct scopes
- [ ] Slack URLs configured
- [ ] `.env` updated with Slack credentials
- [ ] GitHub app created (optional)
- [ ] `.env` updated with GitHub credentials (optional)
- [ ] Database setup (user, workspace, Grafana integration)
- [ ] Slack bot installed via OAuth
- [ ] Bot responds in Slack channel
- [ ] API tests passing

---

**🎉 Setup Complete! Your VM-API is ready to monitor services via Slack bot!** 🚀
