# VibeMonitor API - Project Structure & Data Flows

## Project Overview

**VibeMonitor API** is a FastAPI-based observability and monitoring platform that provides:
- AI-powered Root Cause Analysis (RCA) via Slack and Web Chat
- Multi-tenant workspace management with team collaboration
- Integration with observability platforms (Grafana, AWS CloudWatch, Datadog, New Relic)
- GitHub repository integration for code context in RCA
- Billing and subscription management via Stripe

---

## Architecture Overview

### Technology Stack
- **Framework:** FastAPI (Python 3.12+)
- **Database:** PostgreSQL (Supabase for local, AWS RDS for production)
- **ORM:** SQLAlchemy 2.0 with Alembic migrations
- **Cache/Streaming:** Redis (for SSE pub/sub and caching)
- **Queue:** AWS SQS (LocalStack for local dev)
- **Authentication:** Google OAuth 2.0, GitHub OAuth, Credential-based (email/password)
- **AI/LLM:** Groq API (default), OpenAI, Azure OpenAI, Google Gemini (BYOLLM)
- **Email:** Postmark for transactional emails
- **Payments:** Stripe for billing and subscriptions
- **Deployment:** Docker + ECS on AWS

### Core Features
1. **Authentication & Authorization**
   - Google OAuth 2.0 with PKCE support
   - GitHub OAuth with PKCE support
   - Credential-based auth (email/password with verification)
   - JWT-based token management (access + refresh tokens)
   - Role-based access control (Owner/User)

2. **Multi-tenant Workspaces**
   - Personal and Team workspace types
   - Workspace invitations with email tokens
   - Member management with role permissions

3. **AI-Powered RCA**
   - Slack bot integration with real-time responses
   - Web chat with SSE streaming
   - Multi-provider LLM support (BYOLLM)
   - Prompt injection protection

4. **Observability Integrations**
   - Grafana (Loki logs, Prometheus metrics)
   - AWS CloudWatch (logs and metrics)
   - Datadog (logs and metrics)
   - New Relic (logs and metrics)
   - GitHub (code context for RCA)

5. **Billing & Subscriptions**
   - Free and Pro plans
   - Service-based billing
   - Stripe integration

---

## Directory Structure

```
vm-api/
├── app/
│   ├── main.py                      # FastAPI app entry point
│   ├── models.py                    # All SQLAlchemy models (unified)
│   ├── worker.py                    # Background worker for RCA jobs
│   │
│   ├── api/routers/                 # Central router aggregation
│   │   └── routers.py               # Combines all routers
│   │
│   ├── auth/                        # Authentication module (restructured)
│   │   ├── account/                 # Account management (profile, deletion)
│   │   │   ├── router.py            # GET/PATCH /account, DELETE /account
│   │   │   ├── service.py           # Account operations, deletion logic
│   │   │   └── schemas.py           # Account schemas
│   │   ├── credential/              # Email/password authentication
│   │   │   ├── router.py            # /auth/register, /auth/login
│   │   │   ├── service.py           # Password hashing, verification
│   │   │   └── schemas.py           # Credential schemas
│   │   ├── github/                  # GitHub OAuth
│   │   │   ├── router.py            # /auth/github/login, /auth/github/callback
│   │   │   └── service.py           # GitHub OAuth flow with PKCE
│   │   ├── google/                  # Google OAuth
│   │   │   ├── router.py            # /auth/google/login, /auth/google/callback
│   │   │   └── service.py           # Google OAuth flow with PKCE
│   │   └── routers/                 # Legacy auth router
│   │
│   ├── billing/                     # Billing & subscriptions
│   │   ├── router.py                # /billing/* endpoints
│   │   ├── service.py               # Stripe integration, plan management
│   │   └── schemas.py               # Billing schemas
│   │
│   ├── chat/                        # Web chat module
│   │   ├── router.py                # /chat, /sessions, /turns endpoints
│   │   ├── service.py               # Chat session management
│   │   ├── streaming.py             # SSE streaming with Redis pub/sub
│   │   └── schemas.py               # Chat schemas
│   │
│   ├── core/                        # Core utilities
│   │   ├── config.py                # Environment settings (Pydantic)
│   │   ├── database.py              # Database session management
│   │   ├── security.py              # JWT utilities, password hashing
│   │   └── token_processor.py       # Encryption for sensitive data
│   │
│   ├── datasources/                 # Grafana datasource discovery
│   │   ├── router.py                # /datasources endpoints
│   │   └── service.py               # Datasource operations
│   │
│   ├── email_service/               # Email sending (Postmark)
│   │   ├── service.py               # Email sending logic
│   │   └── templates.py             # Email templates
│   │
│   ├── engagement/                  # User engagement tracking
│   │   └── service.py               # Engagement events
│   │
│   ├── environments/                # Environment configuration
│   │   ├── router.py                # /environments endpoints
│   │   ├── service.py               # Environment CRUD
│   │   └── schemas.py               # Environment schemas
│   │
│   ├── github/                      # GitHub App integration
│   │   ├── router.py                # /github/webhook, /github/callback
│   │   ├── service.py               # GitHub API operations
│   │   └── schemas.py               # GitHub schemas
│   │
│   ├── grafana/                     # Grafana integration
│   │   ├── router.py                # /grafana/* endpoints
│   │   └── service.py               # Grafana API client
│   │
│   ├── integrations/                # Unified integrations module
│   │   ├── router.py                # /integrations/* endpoints
│   │   ├── service.py               # Integration lifecycle management
│   │   ├── health.py                # Health check logic
│   │   └── schemas.py               # Integration schemas
│   │
│   ├── llm/                         # LLM configuration (BYOLLM)
│   │   ├── router.py                # /llm-config endpoints
│   │   ├── service.py               # LLM provider management
│   │   └── schemas.py               # LLM config schemas
│   │
│   ├── log/                         # Log querying
│   │   ├── router.py                # /logs/* endpoints
│   │   └── service.py               # Loki query builder
│   │
│   ├── metrics/                     # Metrics querying
│   │   ├── router.py                # /metrics/* endpoints
│   │   └── service.py               # Prometheus query builder
│   │
│   ├── middleware/                  # FastAPI middleware
│   │   ├── rate_limit.py            # Rate limiting middleware
│   │   └── workspace.py             # Workspace context middleware
│   │
│   ├── onboarding/                  # Workspace & membership management
│   │   ├── routes/
│   │   │   ├── workspace_router.py  # /workspaces CRUD
│   │   │   └── membership_router.py # /invitations, /members endpoints
│   │   ├── services/
│   │   │   ├── workspace_service.py # Workspace operations
│   │   │   └── membership_service.py # Invitation and member management
│   │   └── schemas/                 # Pydantic schemas
│   │
│   ├── security/                    # Security features
│   │   ├── guard.py                 # Prompt injection detection (LLM-based)
│   │   └── service.py               # Security event logging
│   │
│   ├── services/                    # External service clients
│   │   ├── groq/                    # Groq LLM client
│   │   ├── rca/                     # Root Cause Analysis agent
│   │   │   ├── agent.py             # LangChain ReAct agent
│   │   │   ├── tools.py             # RCA tools (logs, metrics, code)
│   │   │   ├── prompts.py           # System prompts
│   │   │   └── README.md            # RCA documentation
│   │   └── sqs/                     # AWS SQS client
│   │
│   ├── slack/                       # Slack integration
│   │   ├── router.py                # /slack/* endpoints
│   │   ├── service.py               # Slack event handling
│   │   └── schemas.py               # Slack payload schemas
│   │
│   ├── utils/                       # Shared utilities
│   │   └── rate_limiter.py          # Rate limiting utilities
│   │
│   ├── workers/                     # Background workers
│   │   └── rca_orchestrator.py      # RCA job processor
│   │
│   ├── aws/                         # AWS CloudWatch integration
│   │   ├── router.py                # /aws/* endpoints
│   │   └── service.py               # CloudWatch API client
│   │
│   ├── datadog/                     # Datadog integration
│   │   ├── router.py                # /datadog/* endpoints
│   │   └── service.py               # Datadog API client
│   │
│   └── newrelic/                    # New Relic integration
│       ├── router.py                # /newrelic/* endpoints
│       └── service.py               # New Relic API client
│
├── alembic/                         # Database migrations
│   ├── versions/                    # Migration files
│   └── env.py                       # Alembic configuration
│
├── docs/                            # API documentation
│   ├── FRONTEND_INTEGRATION.md      # Frontend API reference
│   ├── FRONTEND_CHAT_INTEGRATION.md # Web chat API reference
│   └── JOBS_SYSTEM.md               # Jobs system documentation
│
├── project-overview/                # Project documentation
│   ├── project-structure.md         # This file
│   └── er-diagram.md                # Database ER diagram
│
├── tests/                           # Test suite
├── docker-compose.dev.yml           # Development environment
├── Dockerfile.dev                   # Development Docker image
├── taskdef.template.json            # ECS task definition template
├── pyproject.toml                   # Poetry dependencies
├── .env.example                     # Environment variables template
├── CLAUDE.md                        # AI assistant context file
├── README.md                        # Project README
└── SETUP_GUIDE.md                   # Setup instructions
```

---

## Data Flow Diagrams

### 1. User Registration & Login Flow (Google OAuth)

```
┌──────────────┐
│   Frontend   │
└──────┬───────┘
       │
       │ 1. GET /api/v1/auth/google/login?redirect_uri=...
       ▼
┌─────────────────────────────────────────┐
│   Backend: GoogleAuthService            │
├─────────────────────────────────────────┤
│ 2. Generate Google OAuth URL            │
│    (with PKCE code_verifier)            │
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
│   POST /api/v1/auth/google/callback     │
├─────────────────────────────────────────┤
│ 6. Exchange code for Google tokens      │
│ 7. Fetch user info from Google          │
│ 8. Check if user exists in DB           │
│    - If not: CREATE user + workspace    │
│    - If yes: GET user                   │
│ 9. Generate JWT tokens                  │
│    - access_token (30 min)              │
│    - refresh_token (7 days)             │
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

### 2. Workspace Invitation Flow

```
┌──────────────┐
│ Workspace    │
│   Owner      │
└──────┬───────┘
       │
       │ 1. POST /api/v1/workspaces/{id}/invitations
       │    Body: {email, role}
       ▼
┌─────────────────────────────────────────┐
│   Backend: MembershipService            │
├─────────────────────────────────────────┤
│ 2. Validate owner permissions           │
│ 3. Check workspace is team type         │
│ 4. Generate invitation token            │
│ 5. Create invitation record             │
│ 6. Send invitation email (Postmark)     │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│   Invitee receives email                │
├─────────────────────────────────────────┤
│ 7. Clicks invitation link               │
│    /invite?token=xxx                    │
└──────┬──────────────────────────────────┘
       │
       │ 8. POST /api/v1/invitations/{id}/accept
       ▼
┌─────────────────────────────────────────┐
│   Backend: Accept Invitation            │
├─────────────────────────────────────────┤
│ 9. Validate token not expired           │
│ 10. Create membership record            │
│ 11. Update invitation status            │
│ 12. Return workspace details            │
└──────────────────────────────────────────┘
```

### 3. Web Chat with SSE Streaming Flow

```
┌──────────────┐
│   Frontend   │
│ (React App)  │
└──────┬───────┘
       │
       │ 1. POST /api/v1/workspaces/{wid}/chat
       │    Body: {message, session_id?}
       ▼
┌─────────────────────────────────────────┐
│   Backend: ChatService                  │
├─────────────────────────────────────────┤
│ 2. Create/get session                   │
│ 3. Create turn record                   │
│ 4. Create RCA job                       │
│ 5. Enqueue job to SQS                   │
│ 6. Return turn_id + session_id          │
└──────┬──────────────────────────────────┘
       │
       │ 7. GET /api/v1/.../turns/{turn_id}/stream
       │    (SSE connection)
       ▼
┌─────────────────────────────────────────┐
│   Backend: SSE Streaming                │
├─────────────────────────────────────────┤
│ 8. Subscribe to Redis pub/sub           │
│    channel: turn:{turn_id}              │
└──────┬──────────────────────────────────┘
       │
       │ (Meanwhile...)
       │
┌──────▼──────────────────────────────────┐
│   Worker: RCA Orchestrator              │
├─────────────────────────────────────────┤
│ 9. Poll SQS queue                       │
│ 10. Execute RCA agent                   │
│     - Fetch logs                        │
│     - Fetch metrics                     │
│     - Search code                       │
│ 11. Publish events to Redis:            │
│     - tool_start                        │
│     - tool_end                          │
│     - thinking                          │
│     - complete                          │
└─────────────────────────────────────────┘
       │
       │ 12. SSE events streamed to frontend
       ▼
┌──────────────┐
│   Frontend   │
│ Shows steps  │
│ + response   │
└──────────────┘
```

### 4. RCA Agent ReAct Loop

```
User Query: "Why is my api-gateway service slow?"
       │
       ▼
┌─────────────────────────────────────────┐
│   RCA Agent (LangChain ReAct)           │
├─────────────────────────────────────────┤
│ Thought: Check for recent errors        │
│ Action: fetch_error_logs_tool           │
│ Input: {service: "api-gateway"}         │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Observation: Found 15 timeout errors    │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Thought: Check latency metrics          │
│ Action: fetch_http_latency_tool         │
│ Input: {service: "api-gateway", p99}    │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Observation: p99 latency = 12s          │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Thought: Check CPU/memory               │
│ Action: fetch_cpu_metrics_tool          │
│ Input: {service: "api-gateway"}         │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Observation: CPU at 95%                 │
└──────┬──────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────┐
│ Final Answer:                           │
│ Root cause: Resource saturation         │
│ Evidence: High CPU, timeout errors      │
│ Recommendation: Scale horizontally      │
└─────────────────────────────────────────┘
```

---

## API Endpoints

### Authentication (`/api/v1/auth`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/auth/google/login` | Initiate Google OAuth flow | No |
| POST | `/auth/google/callback` | Handle Google OAuth callback | No |
| GET | `/auth/github/login` | Initiate GitHub OAuth flow | No |
| POST | `/auth/github/callback` | Handle GitHub OAuth callback | No |
| POST | `/auth/register` | Register with email/password | No |
| POST | `/auth/login` | Login with email/password | No |
| POST | `/auth/verify-email` | Verify email address | No |
| POST | `/auth/forgot-password` | Request password reset | No |
| POST | `/auth/reset-password` | Reset password with token | No |
| POST | `/auth/refresh` | Refresh access token | No |
| GET | `/auth/me` | Get current user info | Yes |
| POST | `/auth/logout` | Revoke refresh tokens | Yes |

### Account (`/api/v1/account`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/account` | Get account profile | Yes |
| PATCH | `/account` | Update account profile | Yes |
| GET | `/account/deletion-preview` | Preview account deletion | Yes |
| DELETE | `/account` | Delete account | Yes |

### Workspaces (`/api/v1/workspaces`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/workspaces` | Create new workspace | Yes |
| GET | `/workspaces` | Get user's workspaces | Yes |
| GET | `/workspaces/{id}` | Get workspace details | Yes |
| PATCH | `/workspaces/{id}` | Update workspace | Yes (Owner) |
| DELETE | `/workspaces/{id}` | Delete workspace | Yes (Owner) |

### Membership & Invitations

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/workspaces/{id}/invitations` | Invite member | Yes (Owner) |
| GET | `/workspaces/{id}/invitations` | List workspace invitations | Yes (Owner) |
| GET | `/workspaces/{id}/members` | List workspace members | Yes |
| PATCH | `/workspaces/{id}/members/{uid}` | Update member role | Yes (Owner) |
| DELETE | `/workspaces/{id}/members/{uid}` | Remove member | Yes (Owner) |
| POST | `/workspaces/{id}/leave` | Leave workspace | Yes |
| GET | `/invitations` | Get my pending invitations | Yes |
| POST | `/invitations/{id}/accept` | Accept invitation | Yes |
| POST | `/invitations/{id}/decline` | Decline invitation | Yes |

### Web Chat (`/api/v1/workspaces/{wid}`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/chat` | Send message | Yes |
| GET | `/sessions` | List chat sessions | Yes |
| GET | `/sessions/search` | Search chat sessions | Yes |
| GET | `/sessions/{sid}` | Get session details | Yes |
| PATCH | `/sessions/{sid}` | Update session title | Yes |
| DELETE | `/sessions/{sid}` | Delete session | Yes |
| GET | `/turns/{tid}` | Get turn details | Yes |
| GET | `/turns/{tid}/stream` | SSE stream for turn | Yes |
| POST | `/turns/{tid}/feedback` | Submit feedback | Yes |
| POST | `/turns/{tid}/comments` | Add comment | Yes |

### LLM Configuration (`/api/v1/workspaces/{wid}`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/llm-config` | Get LLM configuration | Yes (Owner) |
| PUT | `/llm-config` | Update LLM configuration | Yes (Owner) |
| POST | `/llm-config/verify` | Verify LLM credentials | Yes (Owner) |
| DELETE | `/llm-config` | Reset to default (VibeMonitor) | Yes (Owner) |

### Environments (`/api/v1`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/environments/workspace/{wid}` | List environments | Yes |
| POST | `/environments` | Create environment | Yes (Owner) |
| PATCH | `/environments/{id}` | Update environment | Yes (Owner) |
| DELETE | `/environments/{id}` | Delete environment | Yes (Owner) |
| POST | `/environments/{id}/set-default` | Set as default | Yes (Owner) |
| POST | `/environments/{id}/repositories` | Add repository | Yes (Owner) |
| GET | `/environments/{id}/available-repositories` | List available repos | Yes |

### Services (`/api/v1/workspaces/{wid}`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/services` | List services | Yes |
| GET | `/services/count` | Get service count & limits | Yes |
| POST | `/services` | Create service | Yes (Owner) |
| PATCH | `/services/{id}` | Update service | Yes (Owner) |
| DELETE | `/services/{id}` | Delete service | Yes (Owner) |

### Billing (`/api/v1/billing`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/billing/plans` | Get available plans | No |
| GET | `/billing/workspaces/{wid}/subscription` | Get subscription | Yes |
| GET | `/billing/workspaces/{wid}/usage` | Get usage stats | Yes |
| POST | `/billing/workspaces/{wid}/subscribe/pro` | Subscribe to Pro | Yes (Owner) |
| POST | `/billing/workspaces/{wid}/billing-portal` | Open Stripe portal | Yes (Owner) |
| POST | `/billing/workspaces/{wid}/subscription/cancel` | Cancel subscription | Yes (Owner) |
| POST | `/billing/webhooks/stripe` | Stripe webhook | Stripe Signature |

### Integrations (`/api/v1/integrations`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/integrations/workspace/{wid}` | List integrations | Yes |
| GET | `/integrations/workspace/{wid}/available` | Get allowed integrations | Yes |
| POST | `/integrations/{id}/health-check` | Trigger health check | Yes |

### Slack (`/api/v1/slack`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/slack/events` | Receive Slack events | Slack Signature |
| GET | `/slack/oauth/callback` | Handle OAuth installation | No |
| GET | `/slack/install` | Get OAuth install URL | Yes |
| POST | `/slack/interactivity` | Handle interactive components | Slack Signature |

### GitHub (`/api/v1/github`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/github/webhook` | Handle GitHub webhooks | GitHub Signature |
| GET | `/github/callback` | Handle OAuth callback | No |

### Health

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/health` | API health status | No |

---

## Environment Variables

### Core Configuration
```bash
ENVIRONMENT=local|dev|staging|prod
API_BASE_URL=http://localhost:8000
WEB_APP_URL=https://vibemonitor.ai/
LOG_LEVEL=INFO
```

### Database
```bash
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:54322/postgres
```

### JWT & Security
```bash
JWT_SECRET_KEY=your-secret-key-here
CRYPTOGRAPHY_SECRET=your-32-byte-encryption-key
```

### OAuth Providers
```bash
# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# GitHub OAuth (for user auth)
GITHUB_OAUTH_CLIENT_ID=your-github-oauth-client-id
GITHUB_OAUTH_CLIENT_SECRET=your-github-oauth-client-secret
```

### GitHub App (for repository integration)
```bash
GITHUB_APP_NAME=your-app-name
GITHUB_APP_ID=your-app-id
GITHUB_PRIVATE_KEY_PEM=base64-encoded-private-key
GITHUB_CLIENT_ID=your-github-app-client-id
GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

### Slack Integration
```bash
SLACK_SIGNING_SECRET=your-slack-signing-secret
SLACK_CLIENT_ID=your-slack-client-id
SLACK_CLIENT_SECRET=your-slack-client-secret
```

### AI/LLM
```bash
GROQ_API_KEY=your-groq-api-key
GROQ_LLM_MODEL=llama-3.3-70b-versatile
GEMINI_API_KEY=your-gemini-api-key
GEMINI_LLM_MODEL=gemini-2.5-flash
```

### AWS Services
```bash
AWS_REGION=us-east-1
SQS_QUEUE_URL=http://localhost:4566/000000000000/vm-api-queue
AWS_ACCESS_KEY_ID=test  # LocalStack only
AWS_SECRET_ACCESS_KEY=test  # LocalStack only
AWS_ENDPOINT_URL=http://localhost:4566  # LocalStack only
OWNER_ROLE_ARN=arn:aws:iam::xxx:role/VibemonitorOwnerRole
```

### Redis
```bash
REDIS_URL=redis://localhost:6379
```

### Email (Postmark)
```bash
POSTMARK_SERVER_TOKEN=your-postmark-token
```

### Stripe Billing
```bash
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRO_PLAN_PRICE_ID=price_...
STRIPE_ADDITIONAL_SERVICE_PRICE_ID=price_...
```

### Observability
```bash
OTEL_ENABLED=true
OTEL_OTLP_ENDPOINT=http://localhost:4317
SENTRY_DSN=your-sentry-dsn
```

---

## Key Design Patterns

### 1. Multi-Tenancy via Workspaces
- Users belong to multiple workspaces
- Data scoped by `workspace_id`
- Role-based access control (Owner/User)
- Personal vs Team workspace types

### 2. OAuth 2.0 Flows
- **Google OAuth:** Authorization Code flow with PKCE support
- **GitHub OAuth:** Authorization Code flow with PKCE support
- **Slack OAuth:** Authorization Code flow for bot installation
- Tokens stored securely (JWT for users, encrypted bot tokens for Slack)

### 3. Unified Integrations Architecture
- Central `integrations` table tracks all providers
- Provider-specific tables for credentials
- Health check system for all integrations
- Automatic status tracking

### 4. BYOLLM (Bring Your Own LLM)
- Workspace-level LLM configuration
- Support for OpenAI, Azure OpenAI, Gemini
- Rate limiting bypassed for BYOLLM users
- Encrypted credential storage

### 5. SSE Streaming for Real-time Updates
- Redis pub/sub for event distribution
- Server-Sent Events for frontend
- Step-by-step RCA progress updates

### 6. Environment-Aware Configuration
- Development: Local PostgreSQL + LocalStack + Redis
- Production: AWS RDS + SQS + ElastiCache
- Template-based ECS task definitions

---

## Token Management

### JWT Tokens (User Authentication)
- **Access Token:** Short-lived (30 min), used for API requests
- **Refresh Token:** Long-lived (7 days), used to get new access tokens
- Stored in `refresh_tokens` table

### Integration Tokens
- **Slack Bot Tokens (`xoxb-...`):** Encrypted in database
- **GitHub Installation Tokens:** Encrypted, auto-refreshed
- **Grafana API Tokens:** Encrypted in database
- **AWS STS Credentials:** Temporary, encrypted

---

## Security Considerations

### Authentication
- Google/GitHub OAuth 2.0 with PKCE support
- Credential-based auth with email verification
- JWT tokens with expiration and refresh rotation
- Password hashing with bcrypt

### API Security
- Request signature verification (Slack, GitHub webhooks)
- Rate limiting per workspace
- CORS configuration for allowed origins

### Data Protection
- Sensitive tokens encrypted at rest (Fernet encryption)
- RLS considerations for multi-tenancy
- Prompt injection detection for AI queries

### Infrastructure
- Secrets loaded from AWS SSM Parameter Store in production
- Private subnets for RDS
- IAM roles for ECS tasks

---

## Background Workers

### RCA Orchestrator Worker
- Polls SQS queue for RCA jobs
- Executes LangChain ReAct agent
- Publishes progress events to Redis
- Updates job status in database

**Start worker:**
```bash
python -m app.worker
```

---

## Future Improvements

### Completed
- [x] Workspace invitation system
- [x] Billing integration (Stripe)
- [x] Caching layer (Redis for SSE)
- [x] Rate limiting
- [x] BYOLLM support
- [x] Web chat with SSE streaming
- [x] Multiple observability integrations
- [x] Database migrations with Alembic
- [x] Encrypt sensitive tokens at rest

### Planned
- [ ] MS Teams integration
- [ ] Automated remediation actions
- [ ] Custom alerting rules
- [ ] Dashboard generation from RCA
