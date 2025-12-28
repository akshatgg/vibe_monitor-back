# Frontend Integration Guide

> API Documentation for Frontend Engineers
> Last Updated: December 2024

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Account Management API](#1-account-management-api)
4. [Workspace Management API](#2-workspace-management-api)
5. [LLM Configuration API (BYOLLM)](#3-llm-configuration-api-byollm)
6. [Environments API](#4-environments-api)
7. [Services API](#5-services-api)
8. [Billing & Subscriptions API](#6-billing--subscriptions-api)
9. [Membership & Invitations API](#7-membership--invitations-api)
10. [Integrations API](#8-integrations-api)
11. [Chat API](#9-chat-api)
12. [Error Handling](#error-handling)
13. [Integration Restrictions](#integration-restrictions)

---

## Overview

### Base URL
```
Production: https://api.vibemonitor.ai
Development: http://localhost:8000
```

### Content Type
All requests should use `Content-Type: application/json`

### Common Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (successful DELETE) |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 402 | Payment Required (limit exceeded) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not Found |
| 422 | Unprocessable Entity |
| 500 | Server Error |

---

## Authentication

All API requests (except public endpoints) require a JWT token in the Authorization header:

```http
Authorization: Bearer <jwt_token>
```

### Getting a Token

#### Google OAuth
```http
POST /auth/google/callback
Content-Type: application/json

{
  "code": "google_auth_code",
  "redirect_uri": "https://app.vibemonitor.ai/auth/callback"
}
```

#### Email/Password Login
```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "name": "John Doe",
    "email": "user@example.com"
  }
}
```

---

## 1. Account Management API

### Get Deletion Preview

Shows what will happen when user deletes their account.

```http
GET /account/deletion-preview
Authorization: Bearer <token>
```

**Response:**
```json
{
  "can_delete": false,
  "blocking_workspaces": [
    {
      "id": "ws_123",
      "name": "Engineering Team",
      "type": "team",
      "member_count": 5,
      "action_required": "Transfer ownership or remove other members before deleting"
    }
  ],
  "workspaces_to_delete": [
    {
      "id": "ws_456",
      "name": "My Personal Space",
      "type": "personal",
      "user_role": "owner"
    }
  ],
  "workspaces_to_leave": [
    {
      "id": "ws_789",
      "name": "Other Team",
      "type": "team",
      "user_role": "user"
    }
  ],
  "message": "Cannot delete account: You are the sole owner of 1 workspace(s) with other members."
}
```

**Frontend Logic:**
- If `can_delete` is `false`, show `blocking_workspaces` with actions required
- Show `workspaces_to_delete` as warning (will be permanently deleted)
- Show `workspaces_to_leave` as info (user will be removed)

### Delete Account

```http
DELETE /account
Authorization: Bearer <token>
Content-Type: application/json

{
  "confirmation": "DELETE",
  "password": "user_password"  // Only required for email/password accounts
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `confirmation` | string | Yes | Must be "DELETE" or user's email |
| `password` | string | Conditional | Required for credential-based accounts, rejected for OAuth accounts |

**Response (200):**
```json
{
  "success": true,
  "deleted_workspaces": ["ws_456"],
  "left_workspaces": ["ws_789"],
  "message": "Account deleted successfully"
}
```

---

## 2. Workspace Management API

### List User's Workspaces

```http
GET /workspaces
Authorization: Bearer <token>
```

**Response:**
```json
{
  "workspaces": [
    {
      "id": "ws_123",
      "name": "My Personal Space",
      "type": "personal",
      "domain": null,
      "visible_to_org": false,
      "is_paid": false,
      "user_role": "owner",
      "created_at": "2024-01-15T10:30:00Z"
    },
    {
      "id": "ws_456",
      "name": "Engineering Team",
      "type": "team",
      "domain": "acme.com",
      "visible_to_org": true,
      "is_paid": true,
      "user_role": "owner",
      "created_at": "2024-02-20T14:00:00Z"
    }
  ]
}
```

### Create Workspace

```http
POST /workspaces
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "New Workspace",
  "type": "team"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Workspace name (1-255 chars) |
| `type` | enum | Yes | `"personal"` or `"team"` |

**Response (201):**
```json
{
  "id": "ws_new",
  "name": "New Workspace",
  "type": "team",
  "domain": null,
  "visible_to_org": false,
  "is_paid": false,
  "user_role": "owner",
  "created_at": "2024-12-28T10:00:00Z"
}
```

### Update Last Visited Workspace

Called when user switches workspace to persist preference.

```http
PUT /users/me/last-visited-workspace
Authorization: Bearer <token>
Content-Type: application/json

{
  "workspace_id": "ws_123"
}
```

---

## 3. LLM Configuration API (BYOLLM)

> **Owner-only**: All LLM configuration endpoints require workspace owner role.

### Get LLM Config

```http
GET /workspaces/{workspace_id}/llm-config
Authorization: Bearer <token>
```

**Response:**
```json
{
  "provider": "openai",
  "model_name": "gpt-4-turbo",
  "status": "active",
  "has_custom_key": true,
  "last_verified_at": "2024-12-28T10:00:00Z",
  "last_error": null,
  "created_at": "2024-12-01T10:00:00Z",
  "updated_at": "2024-12-28T10:00:00Z"
}
```

**Note:** API keys are NEVER returned in responses. Only `has_custom_key: true/false` indicates if configured.

### Provider Options

| Provider | Value | Required Fields |
|----------|-------|-----------------|
| VibeMonitor (default) | `vibemonitor` | None |
| OpenAI | `openai` | `api_key`, `model_name` |
| Azure OpenAI | `azure_openai` | `api_key`, `azure_endpoint`, `azure_deployment_name` |
| Google Gemini | `gemini` | `api_key`, `model_name` |

### Verify LLM Credentials

Test credentials before saving.

```http
POST /workspaces/{workspace_id}/llm-config/verify
Authorization: Bearer <token>
Content-Type: application/json

{
  "provider": "openai",
  "api_key": "sk-...",
  "model_name": "gpt-4-turbo"
}
```

**Response (Success):**
```json
{
  "success": true,
  "model_info": {
    "model": "gpt-4-turbo",
    "provider": "openai"
  }
}
```

**Response (Failure):**
```json
{
  "success": false,
  "error": "Invalid API key"
}
```

### Update LLM Config

```http
PUT /workspaces/{workspace_id}/llm-config
Authorization: Bearer <token>
Content-Type: application/json

{
  "provider": "openai",
  "api_key": "sk-...",
  "model_name": "gpt-4-turbo"
}
```

**For Azure OpenAI:**
```json
{
  "provider": "azure_openai",
  "api_key": "your-azure-key",
  "azure_endpoint": "https://your-resource.openai.azure.com",
  "azure_deployment_name": "gpt-4-deployment",
  "azure_api_version": "2024-02-01"
}
```

### Reset to Default (VibeMonitor AI)

```http
DELETE /workspaces/{workspace_id}/llm-config
Authorization: Bearer <token>
```

**Response:**
```json
{
  "message": "LLM configuration reset to VibeMonitor default"
}
```

### Rate Limiting Behavior

| Provider | Rate Limits |
|----------|-------------|
| VibeMonitor | 10 RCA sessions/day (Free), 100/day (Pro) |
| OpenAI, Azure, Gemini | **Unlimited** (user pays their provider) |

---

## 4. Environments API

### List Environments

```http
GET /environments/workspace/{workspace_id}
Authorization: Bearer <token>
```

**Response:**
```json
{
  "environments": [
    {
      "id": "env_123",
      "workspace_id": "ws_123",
      "name": "production",
      "is_default": true,
      "auto_discovery_enabled": true,
      "created_at": "2024-12-01T10:00:00Z",
      "repository_configs": [
        {
          "id": "rc_1",
          "repo_full_name": "acme/api-gateway",
          "branch_name": "main",
          "is_enabled": true
        }
      ]
    },
    {
      "id": "env_456",
      "workspace_id": "ws_123",
      "name": "staging",
      "is_default": false,
      "auto_discovery_enabled": true,
      "repository_configs": []
    }
  ],
  "total": 2
}
```

### Create Environment

```http
POST /environments
Authorization: Bearer <token>
Content-Type: application/json

{
  "workspace_id": "ws_123",
  "name": "production",
  "is_default": false,
  "auto_discovery_enabled": true
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `workspace_id` | string | Yes | - | Workspace ID |
| `name` | string | Yes | - | Environment name (should match log env names) |
| `is_default` | boolean | No | `false` | Default for RCA (only one per workspace) |
| `auto_discovery_enabled` | boolean | No | `true` | Auto-add new repos when discovered |

### Set Default Environment

```http
POST /environments/{environment_id}/set-default
Authorization: Bearer <token>
```

**Note:** This automatically unsets the previous default.

### Add Repository to Environment

```http
POST /environments/{environment_id}/repositories
Authorization: Bearer <token>
Content-Type: application/json

{
  "repo_full_name": "acme/api-gateway",
  "branch_name": "main",
  "is_enabled": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repo_full_name` | string | Yes | - | Format: `owner/repo` |
| `branch_name` | string | No | null | Branch to use |
| `is_enabled` | boolean | No | `false` | Enable only after branch is set |

**Frontend Logic:**
- Show "Enable" button as disabled until `branch_name` is set
- Once branch is selected, enable the toggle

### Get Available Repositories

Lists repos from connected GitHub integration.

```http
GET /environments/{environment_id}/available-repositories
Authorization: Bearer <token>
```

**Response:**
```json
{
  "repositories": [
    {
      "full_name": "acme/api-gateway",
      "default_branch": "main",
      "is_private": true
    },
    {
      "full_name": "acme/frontend",
      "default_branch": "master",
      "is_private": false
    }
  ]
}
```

### Get Repository Branches

```http
GET /environments/workspace/{workspace_id}/repositories/{repo_full_name}/branches
Authorization: Bearer <token>
```

**Note:** `repo_full_name` should be URL-encoded (e.g., `acme%2Fapi-gateway`)

**Response:**
```json
{
  "branches": [
    { "name": "main", "is_default": true },
    { "name": "develop", "is_default": false },
    { "name": "feature/new-api", "is_default": false }
  ]
}
```

---

## 5. Services API

### List Services

```http
GET /workspaces/{workspace_id}/services
Authorization: Bearer <token>
```

**Response:**
```json
{
  "services": [
    {
      "id": "svc_123",
      "workspace_id": "ws_123",
      "name": "api-gateway",
      "repository_name": "acme/api-gateway",
      "enabled": true,
      "created_at": "2024-12-01T10:00:00Z"
    }
  ],
  "total": 1
}
```

### Get Service Count & Limits

```http
GET /workspaces/{workspace_id}/services/count
Authorization: Bearer <token>
```

**Response:**
```json
{
  "current_count": 3,
  "limit": 5,
  "can_add_more": true,
  "is_paid": false
}
```

**Frontend Logic:**
- Show progress bar: `3/5 services used`
- If `can_add_more` is `false`, show upgrade prompt

### Create Service

```http
POST /workspaces/{workspace_id}/services
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "api-gateway",
  "repository_name": "acme/api-gateway"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Service name (1-255 chars) |
| `repository_name` | string | No | Linked repo (format: owner/repo) |

**Response (201):**
```json
{
  "id": "svc_new",
  "workspace_id": "ws_123",
  "name": "api-gateway",
  "repository_name": "acme/api-gateway",
  "enabled": true
}
```

**Error (402 - Limit Exceeded):**
```json
{
  "detail": {
    "limit_type": "service",
    "current_count": 5,
    "limit": 5,
    "message": "Service limit reached. Upgrade to Pro for unlimited services.",
    "upgrade_available": true
  }
}
```

---

## 6. Billing & Subscriptions API

### Get Available Plans

```http
GET /billing/plans
```

**No authentication required.**

**Response:**
```json
{
  "plans": [
    {
      "id": "plan_free",
      "name": "Free",
      "plan_type": "FREE",
      "base_service_count": 5,
      "base_price_cents": 0,
      "additional_service_price_cents": 0,
      "rca_session_limit_daily": 10,
      "is_active": true
    },
    {
      "id": "plan_pro",
      "name": "Pro",
      "plan_type": "PRO",
      "stripe_price_id": "price_xxx",
      "base_service_count": 5,
      "base_price_cents": 3000,
      "additional_service_price_cents": 500,
      "rca_session_limit_daily": 100,
      "is_active": true
    }
  ]
}
```

### Pricing Breakdown

| Plan | Base Price | Included Services | Additional Service | RCA Sessions/Day |
|------|------------|-------------------|-------------------|------------------|
| Free | $0 | 5 | N/A | 10 |
| Pro | $30/mo | 5 | $5/mo each | 100 |

### Get Current Subscription

```http
GET /billing/workspaces/{workspace_id}/subscription
Authorization: Bearer <token>
```

**Response (Free Tier):**
```json
{
  "id": null,
  "workspace_id": "ws_123",
  "plan_id": "plan_free",
  "status": "active",
  "billable_service_count": 0,
  "plan": {
    "name": "Free",
    "plan_type": "FREE"
  }
}
```

**Response (Pro Tier):**
```json
{
  "id": "sub_123",
  "workspace_id": "ws_123",
  "plan_id": "plan_pro",
  "stripe_customer_id": "cus_xxx",
  "stripe_subscription_id": "sub_xxx",
  "status": "active",
  "current_period_start": "2024-12-01T00:00:00Z",
  "current_period_end": "2025-01-01T00:00:00Z",
  "billable_service_count": 7,
  "plan": {
    "name": "Pro",
    "plan_type": "PRO"
  }
}
```

### Get Usage Stats

```http
GET /billing/workspaces/{workspace_id}/usage
Authorization: Bearer <token>
```

**Response:**
```json
{
  "plan_name": "Free",
  "plan_type": "free",
  "is_paid": false,
  "service_count": 3,
  "service_limit": 5,
  "services_remaining": 2,
  "can_add_service": true,
  "rca_sessions_today": 4,
  "rca_session_limit_daily": 10,
  "rca_sessions_remaining": 6,
  "can_start_rca": true
}
```

### Subscribe to Pro

Initiates Stripe Checkout session.

```http
POST /billing/workspaces/{workspace_id}/subscribe/pro
Authorization: Bearer <token>
Content-Type: application/json

{
  "success_url": "https://app.vibemonitor.ai/billing/success",
  "cancel_url": "https://app.vibemonitor.ai/billing/cancel"
}
```

**Response:**
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/cs_xxx"
}
```

**Frontend Flow:**
1. Call this endpoint
2. Redirect user to `checkout_url`
3. Stripe redirects back to `success_url` or `cancel_url`
4. On success, call `/subscription/sync` to refresh state

### Open Billing Portal

For managing payment methods, viewing invoices, canceling.

```http
POST /billing/workspaces/{workspace_id}/billing-portal
Authorization: Bearer <token>
Content-Type: application/json

{
  "return_url": "https://app.vibemonitor.ai/settings/billing"
}
```

**Response:**
```json
{
  "portal_url": "https://billing.stripe.com/p/session/xxx"
}
```

### Cancel Subscription

```http
POST /billing/workspaces/{workspace_id}/subscription/cancel
Authorization: Bearer <token>
Content-Type: application/json

{
  "immediate": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `immediate` | boolean | `false` | `true` = cancel now, `false` = cancel at period end |

---

## 7. Membership & Invitations API

### Invite Member to Workspace

> **Owner-only. Team workspaces only.**

```http
POST /workspaces/{workspace_id}/invitations
Authorization: Bearer <token>
Content-Type: application/json

{
  "email": "newuser@example.com",
  "role": "user"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `email` | string | Yes | - | Email to invite |
| `role` | enum | No | `"user"` | `"owner"` or `"user"` |

**Response (201):**
```json
{
  "id": "inv_123",
  "workspace_id": "ws_123",
  "workspace_name": "Engineering Team",
  "inviter_name": "John Doe",
  "invitee_email": "newuser@example.com",
  "role": "user",
  "status": "pending",
  "expires_at": "2025-01-04T10:00:00Z",
  "created_at": "2024-12-28T10:00:00Z"
}
```

**Error (403 - Personal Workspace):**
```json
{
  "detail": "Cannot invite members to personal workspaces. Create a team workspace to collaborate."
}
```

### Role Descriptions (for helper text)

| Role | Capabilities |
|------|--------------|
| **Owner** | Invite members, configure billing, delete workspace, manage integrations, customize agent, everything User can do |
| **User** | Interact with the bot, view settings (read-only) |

### List Pending Invitations (for Workspace)

```http
GET /workspaces/{workspace_id}/invitations
Authorization: Bearer <token>
```

### Get My Pending Invitations

```http
GET /invitations
Authorization: Bearer <token>
```

**Response:**
```json
{
  "invitations": [
    {
      "id": "inv_123",
      "workspace_name": "Engineering Team",
      "inviter_name": "John Doe",
      "role": "user",
      "status": "pending",
      "expires_at": "2025-01-04T10:00:00Z"
    }
  ]
}
```

### Accept Invitation

```http
POST /invitations/{invitation_id}/accept
Authorization: Bearer <token>
```

**Response:**
```json
{
  "id": "ws_123",
  "name": "Engineering Team",
  "type": "team",
  "user_role": "user"
}
```

### Decline Invitation

```http
POST /invitations/{invitation_id}/decline
Authorization: Bearer <token>
```

### List Workspace Members

```http
GET /workspaces/{workspace_id}/members
Authorization: Bearer <token>
```

**Response:**
```json
{
  "members": [
    {
      "user_id": "user_123",
      "user_name": "John Doe",
      "user_email": "john@example.com",
      "role": "owner",
      "joined_at": "2024-01-15T10:00:00Z"
    },
    {
      "user_id": "user_456",
      "user_name": "Jane Smith",
      "user_email": "jane@example.com",
      "role": "user",
      "joined_at": "2024-12-28T10:00:00Z"
    }
  ]
}
```

### Update Member Role

```http
PATCH /workspaces/{workspace_id}/members/{member_user_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "role": "owner"
}
```

**Error (400 - Last Owner):**
```json
{
  "detail": "Cannot demote the last owner of the workspace"
}
```

### Remove Member

```http
DELETE /workspaces/{workspace_id}/members/{member_user_id}
Authorization: Bearer <token>
```

### Leave Workspace

```http
POST /workspaces/{workspace_id}/leave
Authorization: Bearer <token>
```

**Error (400 - Sole Owner):**
```json
{
  "detail": "Cannot leave workspace as sole owner. Transfer ownership first."
}
```

---

## 8. Integrations API

### List Workspace Integrations

```http
GET /integrations/workspace/{workspace_id}
Authorization: Bearer <token>
```

**Query Parameters:**
- `type` (optional): Filter by provider (github, aws, grafana, datadog, newrelic, slack)
- `status` (optional): Filter by status (active, disabled, error)

**Response:**
```json
{
  "integrations": [
    {
      "id": "int_123",
      "workspace_id": "ws_123",
      "provider": "github",
      "status": "active",
      "health_status": "healthy",
      "last_verified_at": "2024-12-28T10:00:00Z",
      "created_at": "2024-12-01T10:00:00Z"
    }
  ],
  "total": 1
}
```

### Get Available Integrations

Shows which integrations are allowed based on workspace type.

```http
GET /integrations/workspace/{workspace_id}/available
Authorization: Bearer <token>
```

**Response (Personal Workspace):**
```json
{
  "workspace_type": "personal",
  "allowed_integrations": ["github", "newrelic"],
  "restrictions": {
    "grafana": true,
    "aws": true,
    "datadog": true,
    "slack": true
  },
  "upgrade_message": "Create a team workspace to access Grafana, AWS, Datadog, and Slack integrations."
}
```

**Response (Team Workspace):**
```json
{
  "workspace_type": "team",
  "allowed_integrations": ["github", "newrelic", "grafana", "aws", "datadog", "slack"],
  "restrictions": {}
}
```

### Trigger Health Check

```http
POST /integrations/{integration_id}/health-check
Authorization: Bearer <token>
```

---

## 9. Chat API

### Create New Chat Session

```http
POST /chat/sessions
Authorization: Bearer <token>
Content-Type: application/json

{
  "workspace_id": "ws_123",
  "title": "Investigating API latency"
}
```

### List Chat Sessions

```http
GET /chat/sessions?workspace_id={workspace_id}
Authorization: Bearer <token>
```

**Response:**
```json
{
  "sessions": [
    {
      "id": "chat_123",
      "workspace_id": "ws_123",
      "title": "Investigating API latency",
      "created_at": "2024-12-28T10:00:00Z",
      "updated_at": "2024-12-28T10:30:00Z"
    }
  ]
}
```

### Send Message

```http
POST /chat/sessions/{session_id}/messages
Authorization: Bearer <token>
Content-Type: application/json

{
  "content": "Why is my API response time high?"
}
```

### Submit Feedback

```http
POST /chat/sessions/{session_id}/turns/{turn_id}/feedback
Authorization: Bearer <token>
Content-Type: application/json

{
  "rating": "thumbs_up"
}
```

| Field | Type | Values |
|-------|------|--------|
| `rating` | enum | `"thumbs_up"`, `"thumbs_down"` |

---

## Error Handling

### Standard Error Response

```json
{
  "detail": "Error message here"
}
```

### Validation Error Response

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Limit Exceeded (402)

```json
{
  "detail": {
    "limit_type": "service",
    "current_count": 5,
    "limit": 5,
    "message": "Service limit reached. Upgrade to Pro for unlimited services.",
    "upgrade_available": true
  }
}
```

### RCA Session Limit (402)

```json
{
  "detail": {
    "limit_type": "rca_session",
    "sessions_today": 10,
    "limit": 10,
    "message": "Daily RCA session limit reached. Upgrade to Pro for 100 sessions/day.",
    "upgrade_available": true,
    "resets_at": "2024-12-29T00:00:00Z"
  }
}
```

---

## Integration Restrictions

### Personal Workspace Restrictions

| Integration | Status | Alternative |
|-------------|--------|-------------|
| GitHub | Allowed | - |
| New Relic | Allowed | - |
| Grafana | Blocked | Create team workspace |
| AWS | Blocked | Create team workspace |
| Datadog | Blocked | Create team workspace |
| Slack | Blocked | Use web chat only |

### Tooltip Content for Workspace Creation

**Personal Workspace:**
> You can integrate observability and source control with your personal login. You cannot invite others to use this space.

**Team Workspace:**
> You can invite others to this workspace. You'll need admin access to observability and source control to set up access for invited members.

---

## Quick Reference: Permission Matrix

| Action | Owner | User |
|--------|-------|------|
| View workspace | Yes | Yes |
| Chat with bot | Yes | Yes |
| View integrations | Yes | Yes |
| View environments | Yes | Yes |
| View services | Yes | Yes |
| **Modify LLM config** | Yes | No |
| **Create/edit environments** | Yes | No |
| **Create/edit services** | Yes | No |
| **Manage integrations** | Yes | No |
| **Invite members** | Yes | No |
| **Manage billing** | Yes | No |
| **Delete workspace** | Yes | No |

---

## Webhooks (Backend Use Only)

Stripe webhooks are handled at:
```
POST /billing/webhooks/stripe
```

Events handled:
- `checkout.session.completed` - Subscription created
- `customer.subscription.updated` - Subscription changed
- `customer.subscription.deleted` - Subscription canceled
- `invoice.payment_succeeded` - Payment successful
- `invoice.payment_failed` - Payment failed

---

## Questions?

Contact the backend team or check the API source code in:
- `app/auth/routers/` - Authentication & Account
- `app/llm/` - BYOLLM
- `app/environments/` - Environments
- `app/billing/` - Billing & Services
- `app/onboarding/` - Membership & Invitations
- `app/integrations/` - Integrations
