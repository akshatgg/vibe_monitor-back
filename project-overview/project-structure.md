# VibeMonitor API - Project Structure & Data Flows

## Project Overview

**VibeMonitor API** is a FastAPI-based backend focused on:
- User authentication (Google OAuth)
- Workspace management (multi-tenant)
- Slack bot integration with OAuth installation flow

---

## Architecture Overview

### Technology Stack
- **Framework:** FastAPI (Python 3.12+)
- **Database:** PostgreSQL/Supabase (async with SQLAlchemy)
- **Authentication:** Google OAuth 2.0 + JWT
- **Slack Integration:** Slack Events API + OAuth 2.0
- **Deployment:** Docker + Docker Compose

### Core Features
1. ✅ Google OAuth authentication
2. ✅ Multi-tenant workspace management
3. ✅ Slack bot with event subscriptions
4. ✅ JWT-based token management
5. ✅ Slack OAuth installation flow with PostgreSQL persistence

---

## Directory Structure

```
vm-api/
├── app/
│   ├── main.py                      # FastAPI app entry point
│   ├── core/                        # Core configuration
│   │   ├── config.py               # Environment settings
│   │   ├── database.py             # Database session management
│   │   └── security.py             # JWT utilities
│   │
│   ├── onboarding/                 # User & Workspace management
│   │   ├── routes/
│   │   │   ├── router.py           # Auth endpoints (login, callback)
│   │   │   └── workspace_router.py # Workspace CRUD endpoints
│   │   ├── services/
│   │   │   ├── auth_service.py     # Google OAuth logic
│   │   │   └── workspace_service.py # Workspace business logic
│   │   ├── models/
│   │   │   └── models.py           # SQLAlchemy models (User, Workspace, etc.)
│   │   └── schemas/
│   │       └── schemas.py          # Pydantic request/response models
│   │
│   ├── slack/                      # Slack integration
│   │   ├── router.py               # /events and /oauth/callback endpoints
│   │   ├── service.py              # Event handling, message sending, installation storage
│   │   ├── models.py               # SlackInstallation SQLAlchemy model
│   │   └── schemas.py              # Slack event payload models
│   │
│   ├── api/routers/                # Central router aggregation
│   │   └── routers.py              # Combines all routers
│   │
│   └── [discontinued modules]
│       ├── ingestion/              # ⚠️ DISCONTINUED - OTel ingestion
│       ├── services/clickhouse/    # ⚠️ DISCONTINUED
│       ├── query/                  # ⚠️ DISCONTINUED
│
├── tests/                          # Test suite
├── docker-compose.dev.yml          # Development environment
├── Dockerfile.dev                  # Development Docker image
├── pyproject.toml                  # Poetry dependencies
├── .env                            # Environment variables (not in git)
└── CLAUDE.md                       # AI assistant context file
```

---

## Data Flow Diagrams

### 1. User Registration & Login Flow

```
┌──────────────┐
│   Frontend   │
└──────┬───────┘
       │
       │ 1. GET /api/v1/auth/login?redirect_uri=...
       ▼
┌─────────────────────────────────────────┐
│   Backend: AuthService                  │
├─────────────────────────────────────────┤
│ 2. Generate Google OAuth URL            │
│    (with PKCE if provided)              │
└──────┬──────────────────────────────────┘
       │
       │ 3. Redirect to Google OAuth
       ▼
┌─────────────────────────────────────────┐
│   Google OAuth                          │
├─────────────────────────────────────────┤
│ 4. User approves permissions            │
└──────┬──────────────────────────────────┘
       │
       │ 5. Redirect to callback with code
       ▼
┌─────────────────────────────────────────┐
│   POST /api/v1/auth/callback            │
├─────────────────────────────────────────┤
│ 6. Exchange code for Google tokens      │
│ 7. Fetch user info from Google          │
│ 8. Check if user exists in DB           │
│    - If not: CREATE user                │
│    - If yes: GET user                   │
│ 9. Generate JWT tokens                  │
│    - access_token (60 min)              │
│    - refresh_token (30 days)            │
│ 10. Store refresh_token in DB           │
└──────┬──────────────────────────────────┘
       │
       │ 11. Return tokens to frontend
       ▼
┌──────────────┐
│   Frontend   │
│ Stores tokens│
└──────────────┘
```

### 2. Workspace Creation Flow

```
┌──────────────┐
│   Frontend   │
│ (Authenticated)
└──────┬───────┘
       │
       │ 1. POST /api/v1/workspaces
       │    Header: Authorization: Bearer {access_token}
       │    Body: {name, visible_to_org}
       ▼
┌─────────────────────────────────────────┐
│   Backend: WorkspaceService             │
├─────────────────────────────────────────┤
│ 2. Verify JWT token                     │
│ 3. Extract user_id from token           │
│ 4. Generate workspace_id (UUID)         │
│ 5. Extract domain from user email       │
│    (if visible_to_org = true)           │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Database Transaction                  │
├─────────────────────────────────────────┤
│ 6. INSERT INTO workspaces               │
│    (id, name, domain, visible_to_org)   │
│                                         │
│ 7. INSERT INTO memberships              │
│    (id, user_id, workspace_id,          │
│     role='OWNER')                       │
│                                         │
│ 8. COMMIT                               │
└──────┬──────────────────────────────────┘
       │
       │ 9. Return workspace details
       ▼
┌──────────────┐
│   Frontend   │
└──────────────┘
```

### 3. Slack Bot Installation Flow

```
┌──────────────┐
│   User       │
│ (In Slack)   │
└──────┬───────┘
       │
       │ 1. Click "Add to Slack" button
       │    URL: slack.com/oauth/v2/authorize?client_id=...
       ▼
┌─────────────────────────────────────────┐
│   Slack OAuth                           │
├─────────────────────────────────────────┤
│ 2. Show permission screen               │
│    - app_mentions:read                  │
│    - chat:write                         │
│ 3. User approves                        │
└──────┬──────────────────────────────────┘
       │
       │ 4. Redirect to callback with code
       │    GET /api/v1/slack/oauth/callback?code=ABC123
       ▼
┌─────────────────────────────────────────┐
│   Backend: Slack OAuth Handler          │
├─────────────────────────────────────────┤
│ 5. Verify code is present               │
│ 6. Exchange code for access_token       │
│    POST slack.com/api/oauth.v2.access   │
│    {client_id, client_secret, code}     │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Slack API Response                    │
├─────────────────────────────────────────┤
│ 7. Returns:                             │
│    {                                    │
│      access_token: "xoxb-...",          │
│      team: {id, name},                  │
│      bot_user_id: "U123"                │
│    }                                    │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Backend: Store Installation           │
├─────────────────────────────────────────┤
│ 8. INSERT INTO slack_installations      │
│    - id (UUID)                          │
│    - team_id                            │
│    - team_name                          │
│    - access_token (xoxb-...)            │
│    - bot_user_id                        │
│    - scope                              │
│    - workspace_id (optional FK)         │
│    - installed_at (timestamp)           │
└──────┬──────────────────────────────────┘
       │
       │ 9. Return success message
       ▼
┌──────────────┐
│   User       │
│ Bot installed│
└──────────────┘
```

### 4. Slack Mention Event Flow

```
┌──────────────┐
│   User       │
│ Types in     │
│ Slack:       │
│ @vm-bot hi   │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Slack Events API                      │
├─────────────────────────────────────────┤
│ 1. Detect app_mention event             │
│ 2. Send webhook to backend              │
│    POST /api/v1/slack/events            │
│    Headers:                             │
│      X-Slack-Signature                  │
│      X-Slack-Request-Timestamp          │
│    Body: {event: {...}, team_id, ...}   │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Backend: Verify Request               │
├─────────────────────────────────────────┤
│ 3. Verify HMAC signature                │
│    - Reconstruct signature using        │
│      SLACK_SIGNING_SECRET               │
│    - Compare with X-Slack-Signature     │
│    - If mismatch → Return 403           │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Backend: Parse Event                  │
├─────────────────────────────────────────┤
│ 4. Parse JSON payload                   │
│ 5. Check event type                     │
│    - url_verification → Return challenge│
│    - app_mention → Process message      │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Backend: Extract Context              │
├─────────────────────────────────────────┤
│ 6. extract_message_context()            │
│    - user_id                            │
│    - channel_id                         │
│    - text (message)                     │
│    - timestamp                          │
│    - team_id                            │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Backend: Process Message              │
├─────────────────────────────────────────┤
│ 7. process_user_message()               │
│    - Remove bot mention from text       │
│    - Parse commands (help, status, etc.)│
│    - Generate response                  │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Backend: Send Reply                   │
├─────────────────────────────────────────┤
│ 8. Get access_token for team_id         │
│    - Retrieve from database             │
│      (slack_installations table)        │
│                                         │
│ 9. POST slack.com/api/chat.postMessage  │
│    Headers:                             │
│      Authorization: Bearer {token}      │
│    Body:                                │
│      {channel, text: response}          │
└──────┬──────────────────────────────────┘
       │
       │ 10. Message posted to Slack
       ▼
┌──────────────┐
│   User       │
│ Sees reply   │
│ in channel   │
└──────────────┘
```

---

## API Endpoints

### Authentication Endpoints (`/api/v1/auth`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/auth/login` | Redirect to Google OAuth | No |
| POST | `/auth/callback` | Handle OAuth callback, return JWT tokens | No |
| POST | `/auth/refresh` | Refresh access token using refresh token | No |
| GET | `/auth/me` | Get current user info | Yes (JWT) |
| POST | `/auth/logout` | Revoke refresh tokens | Yes (JWT) |

### Workspace Endpoints (`/api/v1/workspaces`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/workspaces` | Create new workspace | Yes (JWT) |
| GET | `/workspaces` | Get user's workspaces | Yes (JWT) |
| GET | `/workspaces/{id}` | Get workspace details | Yes (JWT) |
| PATCH | `/workspaces/{id}` | Update workspace | Yes (JWT + Owner) |
| DELETE | `/workspaces/{id}` | Delete workspace | Yes (JWT + Owner) |
| POST | `/workspaces/{id}/members` | Add member to workspace | Yes (JWT + Owner) |
| DELETE | `/workspaces/{id}/members/{user_id}` | Remove member | Yes (JWT + Owner) |

### Slack Endpoints (`/api/v1/slack`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/slack/events` | Receive Slack events (mentions, messages) | Slack Signature |
| GET | `/slack/oauth/callback` | Handle Slack OAuth installation | No |

### Health Endpoint

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/health` | Check API health status | No |

---

## Environment Variables

### Core Configuration
```bash
ENVIRONMENT=development|production
API_BASE_URL=http://localhost:8000
LOG_LEVEL=INFO
```

### Database
```bash
DATABASE_URL=postgresql://user:pass@localhost:54322/postgres  # Dev
SUPABASE_DATABASE_URL=postgresql://...                        # Prod
```

### JWT Authentication
```bash
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
```

### Google OAuth
```bash
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback
```

### Slack Integration
```bash
SLACK_SIGNING_SECRET=your-slack-signing-secret
SLACK_CLIENT_ID=your-slack-client-id
SLACK_CLIENT_SECRET=your-slack-client-secret
```

### CORS
```bash
ALLOWED_ORIGINS=["http://localhost:3000","https://vibemonitor.ai"]
```

---

## Key Design Patterns

### 1. Multi-Tenancy via Workspaces
- Users belong to multiple workspaces
- Data scoped by `workspace_id`
- Role-based access control (Owner/Member)

### 2. OAuth 2.0 Flows
- **Google OAuth:** Authorization Code flow with PKCE support
- **Slack OAuth:** Authorization Code flow for bot installation
- Tokens stored securely (JWT for users, bot tokens for Slack)

### 3. Async-First Architecture
- FastAPI with async/await
- AsyncPG for PostgreSQL
- Non-blocking HTTP requests via httpx

### 4. Environment-Aware Configuration
- Development: Local PostgreSQL (Docker)
- Production: Supabase hosted PostgreSQL
- Config loaded from Pydantic Settings

---

## Token Management

### JWT Tokens (User Authentication)
- **Access Token:** Short-lived (60 min), used for API requests
- **Refresh Token:** Long-lived (30 days), used to get new access tokens
- Stored in `refresh_tokens` table

### Slack Bot Tokens
- **Bot User OAuth Token (`xoxb-...`):** Never expires (unless revoked)
- Obtained during Slack OAuth installation
- ✅ Stored in PostgreSQL (`slack_installations` table)

---

## Security Considerations

### Authentication
- ✅ Google OAuth 2.0 with PKCE support
- ✅ JWT tokens with expiration
- ✅ Refresh token rotation

### Slack Integration
- ✅ Request signature verification (HMAC-SHA256)
- ✅ Timestamp validation (prevent replay attacks)
- ✅ Bot tokens stored in PostgreSQL
- ⚠️ Bot tokens not encrypted (TODO: Add encryption at rest)

### Database
- ✅ Async session management
- ✅ Connection pooling
- ✅ Slack installation tokens persisted in PostgreSQL
- ⚠️ Bot tokens not encrypted (TODO)

---

## Future Improvements

### Database
- [x] Implement `slack_installations` table
- [ ] Encrypt sensitive tokens at rest (Slack access tokens, refresh tokens)
- [ ] Add database migrations with Alembic

### Features
- [ ] Workspace invitation system
- [ ] Billing integration
- [ ] Incident management
- [ ] Advanced Slack bot commands

### Performance
- [ ] Caching layer (Redis)
- [ ] Rate limiting
- [ ] Query optimization

---

## Notes

### Discontinued Modules
The following modules are marked as discontinued and should not be used:
- `app/ingestion/` - OpenTelemetry ingestion
- `app/services/clickhouse/` - ClickHouse integration
- `app/query/` - Log query endpoints

Focus development efforts on:
- Authentication & workspace management
- Slack integration
- Core API features