# Entity-Relationship Diagram

## Current Database Schema (PostgreSQL/Supabase)

```
┌──────────────────────┐                  ┌──────────────────────┐
│       USERS          │                  │     WORKSPACES       │
├──────────────────────┤                  ├──────────────────────┤
│ id (PK)              │                  │ id (PK)              │
│ name                 │                  │ name                 │
│ email (UNIQUE)       │                  │ domain               │
│ created_at           │                  │ visible_to_org       │
│ updated_at           │                  │ is_paid              │
└──────────┬───────────┘                  │ created_at           │
           │                              │ updated_at           │
           │                              └──────────┬───────────┘
           │                                         │
           │         ┌───────────────────┐           │
           │         │   MEMBERSHIPS     │           │
           └────────>├───────────────────┤<──────────┘
                     │ id (PK)           │
                     │ user_id (FK)      │
                     │ workspace_id (FK) │
                     │ role (ENUM)       │
                     │ created_at        │
                     │ updated_at        │
                     └───────────────────┘
                              │
                              │ Role Values:
                              │ • OWNER
                              │ • MEMBER


┌──────────────────────┐
│   REFRESH_TOKENS     │
├──────────────────────┤
│ token (PK)           │
│ user_id              │  (References users.id, no FK)
│ expires_at           │
│ created_at           │
└──────────────────────┘


┌────────────────────────────────────────────────────────────┐
│      SLACK INTEGRATION ✅ IMPLEMENTED                      │
└────────────────────────────────────────────────────────────┘

┌──────────────────────────┐           ┌──────────────────────┐
│ SLACK_INSTALLATIONS      │           │     WORKSPACES       │
├──────────────────────────┤           ├──────────────────────┤
│ id (PK)                  │           │ id (PK)              │
│ team_id (UNIQUE)         │           └──────────▲───────────┘
│ team_name                │                      │
│ access_token             │  ← Bot token         │
│ bot_user_id              │                      │
│ scope                    │                      │
│ workspace_id (FK) ───────┼──────────────────────┘
│ installed_at             │       Optional link
│ updated_at               │
└──────────────────────────┘
```

---

## Tables

### 1. USERS
**Purpose:** Store user accounts authenticated via Google OAuth

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| name | VARCHAR | NOT NULL | User's full name from Google |
| email | VARCHAR | UNIQUE, NOT NULL | User's email (unique identifier) |
| created_at | TIMESTAMP | DEFAULT NOW() | Account creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Relationships:**
- One-to-Many with `memberships`

---

### 2. WORKSPACES
**Purpose:** Multi-tenant workspaces (similar to Slack workspaces or Notion workspaces)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| name | VARCHAR | NOT NULL | Workspace name |
| domain | VARCHAR | NULLABLE | Company domain (e.g., "acme.com") |
| visible_to_org | BOOLEAN | DEFAULT FALSE | If true, visible to all users with same domain |
| is_paid | BOOLEAN | DEFAULT FALSE | Payment status (future feature) |
| created_at | TIMESTAMP | DEFAULT NOW() | Workspace creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Relationships:**
- One-to-Many with `memberships`

---

### 3. MEMBERSHIPS
**Purpose:** Many-to-many join table linking users to workspaces with roles

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| user_id | VARCHAR | FOREIGN KEY → users.id | User who is a member |
| workspace_id | VARCHAR | FOREIGN KEY → workspaces.id | Workspace they belong to |
| role | ENUM | NOT NULL | Role: OWNER or MEMBER |
| created_at | TIMESTAMP | DEFAULT NOW() | Membership creation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Roles:**
- `OWNER`: Full workspace management permissions
- `MEMBER`: Standard access permissions

**Relationships:**
- Many-to-One with `users`
- Many-to-One with `workspaces`

---

### 4. REFRESH_TOKENS
**Purpose:** Store JWT refresh tokens for authentication token rotation

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| token | VARCHAR | PRIMARY KEY | Refresh token string |
| user_id | VARCHAR | NOT NULL | References users.id (no FK constraint) |
| expires_at | TIMESTAMP | NOT NULL | Token expiration timestamp |
| created_at | TIMESTAMP | DEFAULT NOW() | Token creation timestamp |

**Relationships:**
- Logically references `users` (no FK constraint)

---

### 5. SLACK_INSTALLATIONS ✅
**Purpose:** Store Slack bot OAuth tokens for multi-workspace support

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | VARCHAR | PRIMARY KEY | UUID generated on creation |
| team_id | VARCHAR | UNIQUE, NOT NULL | Slack workspace ID (e.g., T123456) |
| team_name | VARCHAR | NOT NULL | Slack workspace name |
| access_token | VARCHAR | NOT NULL | Bot OAuth token (xoxb-...) - TODO: Encrypt in production |
| bot_user_id | VARCHAR | NULLABLE | Slack bot user ID (e.g., U987654) |
| scope | VARCHAR | NULLABLE | OAuth scopes granted |
| workspace_id | VARCHAR | FOREIGN KEY → workspaces.id | Optional link to internal workspace |
| installed_at | TIMESTAMP | DEFAULT NOW() | Installation timestamp |
| updated_at | TIMESTAMP | ON UPDATE | Last update timestamp |

**Status:** ✅ Implemented - Model defined in `app/slack/models.py`

**Relationships:**
- Optional Many-to-One with `workspaces` (foreign key relationship)

---

## Relationship Summary

### Many-to-Many: Users ↔ Workspaces
```
User A ──┐
         ├──> Membership (OWNER) ──> Workspace 1
User B ──┤
         └──> Membership (MEMBER) ──> Workspace 1

User A ──> Membership (MEMBER) ──> Workspace 2
```

### One-to-Many: Users ↔ RefreshTokens
```
User A ──┬──> RefreshToken 1 (Desktop)
         ├──> RefreshToken 2 (Mobile)
         └──> RefreshToken 3 (Tablet)
```

### Many-to-One: SlackInstallations → Workspaces (Optional)
```
SlackInstallation 1 (team_id: T123456) ──> Workspace 1
SlackInstallation 2 (team_id: T789012) ──> Workspace 2
SlackInstallation 3 (team_id: T345678) ──> Workspace 1  (multiple Slack workspaces can link to same internal workspace)
```