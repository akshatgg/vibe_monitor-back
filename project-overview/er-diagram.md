# Entity-Relationship Diagram

## Current Database Schema (PostgreSQL)

This document describes all database tables and their relationships in the VM-API application.

---

## High-Level Schema Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CORE DOMAIN                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐                  ┌──────────────────────────┐
│       USERS          │                  │       WORKSPACES         │
├──────────────────────┤                  ├──────────────────────────┤
│ id (PK)              │                  │ id (PK)                  │
│ name                 │                  │ name                     │
│ email (UNIQUE)       │                  │ type (personal/team)     │
│ password_hash        │                  │ domain                   │
│ is_verified          │                  │ visible_to_org           │
│ newsletter_subscribed│                  │ is_paid                  │
│ last_visited_ws_id   │                  │ daily_request_limit      │
│ created_at           │                  │ created_at               │
│ updated_at           │                  │ updated_at               │
└──────────┬───────────┘                  └──────────┬───────────────┘
           │                                         │
           │         ┌───────────────────┐           │
           └────────>│   MEMBERSHIPS     │<──────────┘
                     ├───────────────────┤
                     │ id (PK)           │
                     │ user_id (FK)      │
                     │ workspace_id (FK) │
                     │ role (ENUM)       │  Role: OWNER | USER
                     │ created_at        │
                     │ updated_at        │
                     └───────────────────┘
                     (UNIQUE: user_id + workspace_id)


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          WORKSPACE INVITATIONS                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐
│  WORKSPACE_INVITATIONS   │
├──────────────────────────┤
│ id (PK)                  │
│ workspace_id (FK)        │
│ inviter_id (FK → users)  │
│ invitee_email            │
│ invitee_id (FK → users)  │  ← Null if user doesn't exist yet
│ role (ENUM)              │
│ status (ENUM)            │  pending | accepted | declined | expired
│ token (UNIQUE)           │
│ expires_at               │
│ responded_at             │
│ created_at               │
└──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          AUTHENTICATION                                         │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐          ┌──────────────────────────┐
│   REFRESH_TOKENS     │          │   EMAIL_VERIFICATIONS    │
├──────────────────────┤          ├──────────────────────────┤
│ token (PK)           │          │ id (PK)                  │
│ user_id              │          │ user_id (FK)             │
│ expires_at           │          │ token (UNIQUE)           │
│ created_at           │          │ token_hash               │  ← For O(1) lookup
└──────────────────────┘          │ token_type               │  email_verification | password_reset
                                  │ expires_at               │
                                  │ verified_at              │
                                  │ created_at               │
                                  └──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          INTEGRATIONS (Control Plane)                           │
└─────────────────────────────────────────────────────────────────────────────────┘

                          ┌──────────────────────────┐
                          │     INTEGRATIONS         │  ← Central tracking table
                          ├──────────────────────────┤
                          │ id (PK)                  │
                          │ workspace_id (FK)        │
                          │ provider                 │  github | grafana | aws | datadog | newrelic | slack
                          │ status                   │  active | disabled | error
                          │ health_status            │  healthy | failed | null
                          │ last_verified_at         │
                          │ last_error               │
                          │ created_at               │
                          │ updated_at               │
                          └──────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ GITHUB_INTEGRATIONS  │  │ GRAFANA_INTEGRATIONS │  │  SLACK_INSTALLATIONS │
├──────────────────────┤  ├──────────────────────┤  ├──────────────────────┤
│ id (PK)              │  │ id (PK)              │  │ id (PK)              │
│ workspace_id (FK)    │  │ vm_workspace_id (FK) │  │ team_id (UNIQUE)     │
│ integration_id (FK)  │  │ integration_id (FK)  │  │ team_name            │
│ github_user_id       │  │ grafana_url          │  │ access_token         │ ← Encrypted
│ github_username      │  │ api_token            │  │ bot_user_id          │
│ installation_id      │  │ created_at           │  │ scope                │
│ scopes               │  │ updated_at           │  │ workspace_id (FK)    │
│ access_token         │  └──────────────────────┘  │ integration_id (FK)  │
│ token_expires_at     │                            │ installed_at         │
│ is_active            │                            │ updated_at           │
│ created_at           │                            └──────────────────────┘
│ updated_at           │
│ last_synced_at       │
└──────────────────────┘

┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│  AWS_INTEGRATIONS    │  │ DATADOG_INTEGRATIONS │  │ NEWRELIC_INTEGRATIONS│
├──────────────────────┤  ├──────────────────────┤  ├──────────────────────┤
│ id (PK)              │  │ id (PK)              │  │ id (PK)              │
│ workspace_id (FK)    │  │ workspace_id (FK)    │  │ workspace_id (FK)    │
│ integration_id (FK)  │  │ integration_id (FK)  │  │ integration_id (FK)  │
│ role_arn             │  │ api_key              │  │ account_id           │
│ external_id          │  │ app_key              │  │ api_key              │ ← Encrypted
│ access_key_id        │  │ region               │  │ last_verified_at     │
│ secret_access_key    │  │ last_verified_at     │  │ created_at           │
│ session_token        │  │ created_at           │  │ updated_at           │
│ credentials_expiry   │  │ updated_at           │  └──────────────────────┘
│ aws_region           │  └──────────────────────┘
│ is_active            │
│ last_verified_at     │
│ created_at           │
│ updated_at           │
└──────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          RCA JOBS & CHAT                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐          ┌──────────────────────────┐
│         JOBS             │          │     CHAT_SESSIONS        │
├──────────────────────────┤          ├──────────────────────────┤
│ id (PK)                  │          │ id (PK)                  │
│ vm_workspace_id (FK)     │          │ workspace_id (FK)        │
│ source (ENUM)            │  slack   │ source (ENUM)            │  web | slack | msteams
│ slack_integration_id (FK)│  | web   │ user_id (FK)             │  ← Null for Slack
│ trigger_channel_id       │  | ...   │ slack_team_id            │
│ trigger_thread_ts        │          │ slack_channel_id         │
│ trigger_message_ts       │          │ slack_thread_ts          │
│ status (ENUM)            │  queued  │ slack_user_id            │
│ priority                 │  running │ title                    │
│ retries                  │  waiting │ created_at               │
│ max_retries              │  complete│ updated_at               │
│ backoff_until            │  failed  └────────────┬─────────────┘
│ requested_context (JSON) │                       │
│ started_at               │                       │
│ finished_at              │                       ▼
│ error_message            │          ┌──────────────────────────┐
│ created_at               │          │      CHAT_TURNS          │
│ updated_at               │          ├──────────────────────────┤
└──────────────────────────┘          │ id (PK)                  │
                                      │ session_id (FK)          │
                                      │ user_message             │
                                      │ final_response           │
                                      │ status (ENUM)            │  pending | processing | completed | failed
                                      │ job_id (FK → jobs)       │
                                      │ created_at               │
                                      │ updated_at               │
                                      └────────────┬─────────────┘
                                                   │
                   ┌───────────────────────────────┼───────────────────────────────┐
                   ▼                               ▼                               ▼
      ┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
      │     TURN_STEPS       │      │   TURN_FEEDBACKS     │      │    TURN_COMMENTS     │
      ├──────────────────────┤      ├──────────────────────┤      ├──────────────────────┤
      │ id (PK)              │      │ id (PK)              │      │ id (PK)              │
      │ turn_id (FK)         │      │ turn_id (FK)         │      │ turn_id (FK)         │
      │ step_type (ENUM)     │      │ user_id (FK)         │      │ user_id (FK)         │
      │ tool_name            │      │ slack_user_id        │      │ slack_user_id        │
      │ content              │      │ is_positive          │      │ comment              │
      │ status (ENUM)        │      │ source (ENUM)        │      │ source (ENUM)        │
      │ sequence             │      │ created_at           │      │ created_at           │
      │ created_at           │      │ updated_at           │      └──────────────────────┘
      └──────────────────────┘      └──────────────────────┘
                                    (UNIQUE: turn_id + user_id)
                                    (UNIQUE: turn_id + slack_user_id)


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          BILLING & SUBSCRIPTIONS                                │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐          ┌──────────────────────────┐
│        PLANS         │          │      SUBSCRIPTIONS       │
├──────────────────────┤          ├──────────────────────────┤
│ id (PK)              │<─────────│ plan_id (FK)             │
│ name (UNIQUE)        │          │ id (PK)                  │
│ plan_type (ENUM)     │  free    │ workspace_id (FK, UNIQUE)│
│ stripe_price_id      │  | pro   │ stripe_customer_id       │
│ base_service_count   │          │ stripe_subscription_id   │
│ base_price_cents     │          │ status (ENUM)            │  active | past_due | canceled | ...
│ addl_service_cents   │          │ current_period_start     │
│ rca_session_limit    │          │ current_period_end       │
│ is_active            │          │ canceled_at              │
│ created_at           │          │ billable_service_count   │
│ updated_at           │          │ created_at               │
└──────────────────────┘          │ updated_at               │
                                  └──────────────────────────┘

┌──────────────────────────┐
│        SERVICES          │
├──────────────────────────┤
│ id (PK)                  │
│ workspace_id (FK)        │
│ name                     │
│ repository_id (FK)       │  ← Optional link to github_integrations
│ repository_name          │  ← Denormalized for display
│ enabled                  │
│ created_at               │
│ updated_at               │
└──────────────────────────┘
(UNIQUE: workspace_id + name)


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          ENVIRONMENTS                                           │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐          ┌──────────────────────────────┐
│      ENVIRONMENTS        │          │  ENVIRONMENT_REPOSITORIES    │
├──────────────────────────┤          ├──────────────────────────────┤
│ id (PK)                  │<─────────│ environment_id (FK)          │
│ workspace_id (FK)        │          │ id (PK)                      │
│ name                     │          │ github_integration_id (FK)   │
│ is_default               │          │ branch                       │
│ auto_discovery_enabled   │          │ created_at                   │
│ created_at               │          │ updated_at                   │
│ updated_at               │          └──────────────────────────────┘
└──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          LLM CONFIGURATION (BYOLLM)                             │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐
│   LLM_PROVIDER_CONFIGS   │
├──────────────────────────┤
│ id (PK)                  │
│ workspace_id (FK, UNIQUE)│
│ provider (ENUM)          │  vibemonitor | openai | azure_openai | gemini
│ model_name               │
│ config_encrypted         │  ← Encrypted JSON with API keys
│ status (ENUM)            │  active | error | unconfigured
│ last_verified_at         │
│ last_error               │
│ created_at               │
│ updated_at               │
└──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SECURITY & MONITORING                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐          ┌──────────────────────────┐
│    SECURITY_EVENTS       │          │   RATE_LIMIT_TRACKING    │
├──────────────────────────┤          ├──────────────────────────┤
│ id (PK)                  │          │ id (PK)                  │
│ event_type (ENUM)        │ prompt   │ workspace_id (FK)        │
│ severity                 │ injection│ resource_type            │  rca_request | api_call
│ workspace_id (FK)        │ | guard  │ window_key               │  e.g., '2025-10-15'
│ slack_integration_id (FK)│ degraded │ count                    │
│ slack_user_id            │          │ created_at               │
│ message_preview          │          │ updated_at               │
│ guard_response           │          └──────────────────────────┘
│ reason                   │          (UNIQUE: workspace_id + resource_type + window_key)
│ event_metadata (JSON)    │
│ detected_at              │
│ created_at               │
└──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────┐
│                          EMAIL TRACKING                                         │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐
│         EMAILS           │
├──────────────────────────┤
│ id (PK)                  │
│ user_id (FK)             │
│ sent_at                  │
│ subject                  │
│ message_id               │  ← Provider tracking ID
│ status                   │  sent | delivered | failed
│ created_at               │
│ updated_at               │
└──────────────────────────┘
```

---

## Enums

### Role (Membership)
```
OWNER  - Full workspace management permissions
USER   - Standard access permissions (formerly MEMBER)
```

### WorkspaceType
```
PERSONAL - Single-user workspace
TEAM     - Multi-user collaborative workspace
```

### JobStatus
```
QUEUED        - Job waiting to be processed
RUNNING       - Job currently being processed
WAITING_INPUT - Job waiting for user input
COMPLETED     - Job finished successfully
FAILED        - Job failed with error
```

### JobSource / FeedbackSource
```
WEB     - Web chat interface
SLACK   - Slack bot
MSTEAMS - MS Teams (future)
```

### TurnStatus
```
PENDING    - Turn not yet started
PROCESSING - Turn being processed
COMPLETED  - Turn finished
FAILED     - Turn failed
```

### StepType
```
TOOL_CALL - Tool execution step
THINKING  - AI reasoning step
STATUS    - Status update step
```

### StepStatus
```
PENDING   - Step not started
RUNNING   - Step in progress
COMPLETED - Step finished
FAILED    - Step failed
```

### InvitationStatus
```
PENDING  - Invitation sent, awaiting response
ACCEPTED - User accepted invitation
DECLINED - User declined invitation
EXPIRED  - Invitation expired
```

### LLMProvider
```
VIBEMONITOR  - Default (uses Groq)
OPENAI       - OpenAI API
AZURE_OPENAI - Azure OpenAI
GEMINI       - Google Gemini
```

### LLMConfigStatus
```
ACTIVE       - Configuration working
ERROR        - Configuration has errors
UNCONFIGURED - Not configured
```

### PlanType
```
FREE - Free tier
PRO  - Paid tier
```

### SubscriptionStatus
```
ACTIVE     - Subscription active
PAST_DUE   - Payment past due
CANCELED   - Subscription canceled
INCOMPLETE - Initial payment incomplete
TRIALING   - In trial period
```

### SecurityEventType
```
PROMPT_INJECTION - Prompt injection attempt detected
GUARD_DEGRADED   - Security guard degradation
```

---

## Table Descriptions

### 1. USERS
**Purpose:** Store user accounts authenticated via Google OAuth, GitHub OAuth, or email/password.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| name | VARCHAR | NOT NULL | User's full name |
| email | VARCHAR | UNIQUE, NOT NULL | User's email (unique identifier) |
| password_hash | VARCHAR | NULLABLE | Bcrypt hash (null for OAuth users) |
| is_verified | BOOLEAN | DEFAULT FALSE | Email verification status |
| newsletter_subscribed | BOOLEAN | DEFAULT TRUE | Newsletter opt-in |
| last_visited_workspace_id | VARCHAR | FK → workspaces.id | Last visited workspace |
| created_at | TIMESTAMP | DEFAULT NOW() | Account creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Relationships:**
- One-to-Many with `memberships`
- One-to-Many with `chat_sessions`
- One-to-Many with `emails`
- One-to-Many with `email_verifications`

---

### 2. WORKSPACES
**Purpose:** Multi-tenant workspaces for team collaboration.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| name | VARCHAR | NOT NULL | Workspace name |
| type | ENUM | DEFAULT 'team' | personal or team |
| domain | VARCHAR | NULLABLE | Company domain (e.g., "acme.com") |
| visible_to_org | BOOLEAN | DEFAULT FALSE | Visible to all domain users |
| is_paid | BOOLEAN | DEFAULT FALSE | Payment status |
| daily_request_limit | INTEGER | DEFAULT 10 | Daily RCA request limit |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Relationships:**
- One-to-Many with `memberships` (CASCADE DELETE)
- One-to-Many with `services` (CASCADE DELETE)
- One-to-One with `subscription` (CASCADE DELETE)
- One-to-One with `llm_provider_config` (CASCADE DELETE)
- One-to-Many with `environments` (CASCADE DELETE)
- One-to-Many with `integrations` (CASCADE DELETE)
- One-to-Many with `workspace_invitations` (CASCADE DELETE)

---

### 3. MEMBERSHIPS
**Purpose:** Many-to-many join table linking users to workspaces with roles.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| user_id | VARCHAR | FK → users.id | User who is a member |
| workspace_id | VARCHAR | FK → workspaces.id | Workspace they belong to |
| role | ENUM | NOT NULL | Role: OWNER or USER |
| created_at | TIMESTAMP | DEFAULT NOW() | Membership creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Constraints:**
- UNIQUE(user_id, workspace_id)

---

### 4. WORKSPACE_INVITATIONS
**Purpose:** Track workspace invitations with email tokens.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| workspace_id | VARCHAR | FK → workspaces.id (CASCADE) | Target workspace |
| inviter_id | VARCHAR | FK → users.id | User who sent invitation |
| invitee_email | VARCHAR | NOT NULL | Email of invitee |
| invitee_id | VARCHAR | FK → users.id, NULLABLE | Invitee user ID if exists |
| role | ENUM | DEFAULT 'user' | Role to grant on accept |
| status | ENUM | DEFAULT 'pending' | Invitation status |
| token | VARCHAR | UNIQUE, NOT NULL | Secure invitation token |
| expires_at | TIMESTAMP | NOT NULL | Token expiration |
| responded_at | TIMESTAMP | NULLABLE | When user responded |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

---

### 5. INTEGRATIONS
**Purpose:** Central control plane for all integrations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| workspace_id | VARCHAR | FK → workspaces.id (CASCADE) | Owning workspace |
| provider | VARCHAR | NOT NULL | github, grafana, aws, datadog, newrelic, slack |
| status | VARCHAR | DEFAULT 'active' | active, disabled, error |
| health_status | VARCHAR | NULLABLE | healthy, failed, null (unchecked) |
| last_verified_at | TIMESTAMP | NULLABLE | Last health check |
| last_error | TEXT | NULLABLE | Last error message |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

---

### 6. JOBS
**Purpose:** Track RCA job lifecycle and status.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| vm_workspace_id | VARCHAR | FK → workspaces.id | Workspace context |
| source | ENUM | DEFAULT 'slack' | slack, web, msteams |
| slack_integration_id | VARCHAR | FK → slack_installations.id | Slack context |
| trigger_channel_id | VARCHAR | NULLABLE | Slack channel |
| trigger_thread_ts | VARCHAR | NULLABLE | Thread timestamp |
| trigger_message_ts | VARCHAR | NULLABLE | Message timestamp |
| status | ENUM | DEFAULT 'queued' | Job status |
| priority | INTEGER | DEFAULT 0 | Priority (higher = more urgent) |
| retries | INTEGER | DEFAULT 0 | Retry count |
| max_retries | INTEGER | DEFAULT 3 | Max retries |
| backoff_until | TIMESTAMP | NULLABLE | Backoff deadline |
| requested_context | JSON | NULLABLE | User query and context |
| started_at | TIMESTAMP | NULLABLE | Processing start |
| finished_at | TIMESTAMP | NULLABLE | Processing end |
| error_message | TEXT | NULLABLE | Error details |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

---

### 7. CHAT_SESSIONS
**Purpose:** Web and Slack chat conversations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| workspace_id | VARCHAR | FK → workspaces.id | Workspace context |
| source | ENUM | DEFAULT 'web' | web, slack, msteams |
| user_id | VARCHAR | FK → users.id, NULLABLE | Web user (null for Slack) |
| slack_team_id | VARCHAR | NULLABLE | Slack workspace ID |
| slack_channel_id | VARCHAR | NULLABLE | Slack channel |
| slack_thread_ts | VARCHAR | NULLABLE | Slack thread |
| slack_user_id | VARCHAR | NULLABLE | Slack user |
| title | VARCHAR(255) | NULLABLE | Session title |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Constraints:**
- UNIQUE(slack_team_id, slack_channel_id, slack_thread_ts) WHERE source = 'slack'

---

### 8. CHAT_TURNS
**Purpose:** Individual turns (question/answer pairs) in a chat session.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| session_id | VARCHAR | FK → chat_sessions.id (CASCADE) | Parent session |
| user_message | TEXT | NOT NULL | User's question |
| final_response | TEXT | NULLABLE | Bot's response |
| status | ENUM | DEFAULT 'pending' | Turn status |
| job_id | VARCHAR | FK → jobs.id | RCA job processing this turn |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

---

### 9. TURN_FEEDBACKS
**Purpose:** User feedback (thumbs up/down) on chat turns.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| turn_id | VARCHAR | FK → chat_turns.id (CASCADE) | Turn being rated |
| user_id | VARCHAR | FK → users.id, NULLABLE | Web user |
| slack_user_id | VARCHAR | NULLABLE | Slack user |
| is_positive | BOOLEAN | NOT NULL | True = thumbs up |
| source | ENUM | DEFAULT 'web' | web or slack |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Constraints:**
- UNIQUE(turn_id, user_id)
- UNIQUE(turn_id, slack_user_id)

---

### 10. SERVICES
**Purpose:** Billable services within a workspace.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| workspace_id | VARCHAR | FK → workspaces.id (CASCADE) | Owning workspace |
| name | VARCHAR(255) | NOT NULL | Service name |
| repository_id | VARCHAR | FK → github_integrations.id | Linked repository |
| repository_name | VARCHAR(255) | NULLABLE | Denormalized repo name |
| enabled | BOOLEAN | DEFAULT TRUE | Active status |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Constraints:**
- UNIQUE(workspace_id, name)

---

### 11. PLANS
**Purpose:** Billing plan definitions (seeded data).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| name | VARCHAR(50) | UNIQUE, NOT NULL | "Free" or "Pro" |
| plan_type | ENUM | NOT NULL | free or pro |
| stripe_price_id | VARCHAR(255) | NULLABLE | Stripe price ID |
| base_service_count | INTEGER | DEFAULT 5 | Included services |
| base_price_cents | INTEGER | DEFAULT 0 | Base price (3000 = $30) |
| additional_service_price_cents | INTEGER | DEFAULT 500 | Per extra service |
| rca_session_limit_daily | INTEGER | DEFAULT 10 | Daily RCA limit |
| is_active | BOOLEAN | DEFAULT TRUE | Available for purchase |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

---

### 12. SUBSCRIPTIONS
**Purpose:** Workspace subscription state and Stripe integration.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| workspace_id | VARCHAR | FK, UNIQUE → workspaces.id (CASCADE) | One per workspace |
| plan_id | VARCHAR | FK → plans.id | Current plan |
| stripe_customer_id | VARCHAR(255) | NULLABLE | Stripe customer |
| stripe_subscription_id | VARCHAR(255) | NULLABLE | Stripe subscription |
| status | ENUM | DEFAULT 'active' | Subscription status |
| current_period_start | TIMESTAMP | NULLABLE | Billing period start |
| current_period_end | TIMESTAMP | NULLABLE | Billing period end |
| canceled_at | TIMESTAMP | NULLABLE | Cancellation time |
| billable_service_count | INTEGER | DEFAULT 0 | Extra services |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

---

### 13. LLM_PROVIDER_CONFIGS
**Purpose:** BYOLLM (Bring Your Own LLM) configuration per workspace.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID |
| workspace_id | VARCHAR | FK, UNIQUE → workspaces.id (CASCADE) | One per workspace |
| provider | ENUM | DEFAULT 'vibemonitor' | LLM provider |
| model_name | VARCHAR(100) | NULLABLE | Model to use |
| config_encrypted | TEXT | NULLABLE | Encrypted API keys (JSON) |
| status | ENUM | DEFAULT 'active' | Configuration status |
| last_verified_at | TIMESTAMP | NULLABLE | Last verification |
| last_error | TEXT | NULLABLE | Last error message |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

---

## Relationship Summary

### Core Domain
```
User ──┬──> Membership (OWNER) ──> Workspace
       └──> Membership (USER) ──> Workspace
```

### Integrations
```
Workspace ──> Integration (control plane)
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
GitHub          Grafana          Slack
Integration     Integration      Installation
```

### Chat Flow
```
ChatSession ──> ChatTurn ──┬──> TurnStep (tool calls)
                           ├──> TurnFeedback (ratings)
                           └──> TurnComment (comments)

ChatTurn ──> Job (processing)
```

### Billing
```
Workspace ──> Subscription ──> Plan
          │
          └──> Services (billable units)
```

### Environments
```
Workspace ──> Environment ──> EnvironmentRepository ──> GitHubIntegration
```
