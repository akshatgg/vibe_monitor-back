# Web Chat Frontend Integration Guide

> **Version**: 1.0
> **Last Updated**: 2025-12-27
> **Backend Branch**: `ankesh/vib-272-create-backend-for-webchat`

This document provides complete specifications for integrating with the VibeMonitor Web Chat API. It covers authentication, all endpoints, SSE streaming, data models, and implementation patterns.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication](#2-authentication)
3. [Base URL & Headers](#3-base-url--headers)
4. [Data Models](#4-data-models)
5. [API Endpoints](#5-api-endpoints)
6. [SSE Streaming Protocol](#6-sse-streaming-protocol)
7. [Complete Integration Flows](#7-complete-integration-flows)
8. [Error Handling](#8-error-handling)
9. [Best Practices](#9-best-practices)
10. [TypeScript Type Definitions](#10-typescript-type-definitions)

---

## 1. Overview

The Web Chat API enables real-time conversational interactions with VibeMonitor's Root Cause Analysis (RCA) engine. Users can ask questions about their infrastructure, and the system analyzes logs, metrics, and code to provide insights.

### Architecture

```
┌─────────────┐     POST /chat      ┌─────────────┐
│   Frontend  │ ─────────────────►  │   Backend   │
│             │                     │   (FastAPI) │
│             │  GET /turns/{id}/   │             │
│             │      stream         │             │
│             │ ◄─────────────────  │             │
│   (React)   │      SSE Events     │             │
└─────────────┘                     └──────┬──────┘
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │    Redis    │
                                    │  (Pub/Sub)  │
                                    └──────┬──────┘
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │   Worker    │
                                    │  (RCA Job)  │
                                    └─────────────┘
```

### Flow Summary

1. User sends a message via `POST /chat`
2. Backend creates a session (if new) and a turn, returns `turn_id` and `session_id`
3. Frontend connects to `GET /turns/{turn_id}/stream` for SSE updates
4. Worker processes the RCA job and publishes events to Redis
5. SSE endpoint streams events to frontend in real-time
6. On completion, the `complete` event contains the final AI response

---

## 2. Authentication

All chat endpoints require authentication via JWT Bearer tokens.

### Obtaining Tokens

Tokens are obtained through Google OAuth 2.0 flow:

```
POST /api/v1/auth/google/callback
```

### Token Format

```
Authorization: Bearer <access_token>
```

### Token Payload Structure

```json
{
  "sub": "user_uuid",
  "email": "user@example.com",
  "type": "access",
  "exp": 1703721600
}
```

### Token Expiration

| Token Type | Expiration |
|------------|------------|
| Access Token | 30 minutes |
| Refresh Token | 7 days |

### Refreshing Tokens

```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "your_refresh_token"
}
```

**Response:**
```json
{
  "access_token": "new_access_token",
  "token_type": "bearer"
}
```

### Authentication Errors

| Status | Error | Action |
|--------|-------|--------|
| 401 | `Could not validate credentials` | Token invalid or expired - redirect to login |
| 401 | `User not found` | User deleted - redirect to login |

---

## 3. Base URL & Headers

### Base URLs

| Environment | Base URL |
|-------------|----------|
| Local | `http://localhost:8000/api/v1` |
| Development | `https://dev.vibemonitor.ai/api/v1` |
| Production | `https://api.vibemonitor.ai/api/v1` |

### Required Headers

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

### SSE-Specific Headers

For SSE endpoints, the response includes:

```http
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

---

## 4. Data Models

### Enums

#### TurnStatus

| Value | Description |
|-------|-------------|
| `pending` | Turn created, waiting for processing |
| `processing` | RCA engine is analyzing |
| `completed` | Analysis complete, final response available |
| `failed` | Processing failed |

#### StepType

| Value | Description |
|-------|-------------|
| `tool_call` | Execution of an RCA tool (logs, metrics, etc.) |
| `thinking` | Agent reasoning/thinking step |
| `status` | General status update |

#### StepStatus

| Value | Description |
|-------|-------------|
| `pending` | Step not started |
| `running` | Step in progress |
| `completed` | Step finished successfully |
| `failed` | Step failed |

### Core Models

#### ChatSession

```json
{
  "id": "uuid",
  "workspace_id": "uuid",
  "user_id": "uuid",
  "title": "Why is my API slow?",
  "created_at": "2025-12-27T10:00:00Z",
  "updated_at": "2025-12-27T10:05:00Z",
  "turns": []  // Array of ChatTurnSummary
}
```

#### ChatTurn

```json
{
  "id": "uuid",
  "session_id": "uuid",
  "user_message": "Why is my API returning 500 errors?",
  "final_response": "Based on my analysis...",
  "status": "completed",
  "job_id": "uuid",
  "feedback_score": 5,
  "feedback_comment": "Very helpful!",
  "created_at": "2025-12-27T10:00:00Z",
  "updated_at": "2025-12-27T10:01:30Z",
  "steps": []  // Array of TurnStep
}
```

#### TurnStep

```json
{
  "id": "uuid",
  "step_type": "tool_call",
  "tool_name": "Searching CloudWatch logs...",
  "content": "Found 15 error entries in the last hour",
  "status": "completed",
  "sequence": 1,
  "created_at": "2025-12-27T10:00:05Z"
}
```

---

## 5. API Endpoints

All endpoints are prefixed with `/api/v1/workspaces/{workspace_id}`.

### 5.1 Send Message

Start a new conversation or continue an existing one.

```http
POST /workspaces/{workspace_id}/chat
```

#### Request Body

```json
{
  "message": "Why is my API returning 500 errors?",
  "session_id": null  // Optional: omit for new conversation
}
```

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `message` | string | Yes | 1-10,000 chars | User's question |
| `session_id` | string | No | Valid UUID | Existing session ID for continuation |

#### Response (200 OK)

```json
{
  "turn_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "message": "Message received. Connect to SSE endpoint to stream response."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `turn_id` | string | UUID for this turn - use for SSE streaming |
| `session_id` | string | Session UUID - use for subsequent messages |
| `message` | string | Confirmation message |

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 400 | Validation error | Message empty or too long |
| 401 | Authentication error | Invalid/expired token |
| 500 | `Failed to process message` | Internal error |

---

### 5.2 Stream Turn Updates (SSE)

Connect to receive real-time processing updates.

```http
GET /workspaces/{workspace_id}/turns/{turn_id}/stream
```

#### Headers

```http
Authorization: Bearer <access_token>
Accept: text/event-stream
```

#### Response

Server-Sent Events stream with `text/event-stream` content type.

**See [Section 6: SSE Streaming Protocol](#6-sse-streaming-protocol) for complete event specifications.**

#### Connection Behavior

| Turn Status | Behavior |
|-------------|----------|
| `pending` or `processing` | Subscribes to Redis, streams live events |
| `completed` | Returns all steps + completion event immediately |
| `failed` | Returns error event immediately |

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 404 | `Turn not found` | Invalid turn_id or no access |
| 401 | Authentication error | Invalid/expired token |

---

### 5.3 List Sessions

Get all chat sessions for the current user.

```http
GET /workspaces/{workspace_id}/sessions?limit=50&offset=0
```

#### Query Parameters

| Parameter | Type | Default | Max | Description |
|-----------|------|---------|-----|-------------|
| `limit` | integer | 50 | 250 | Number of sessions to return |
| `offset` | integer | 0 | - | Pagination offset |

#### Response (200 OK)

```json
[
  {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "title": "Why is my API slow?",
    "created_at": "2025-12-27T10:00:00Z",
    "updated_at": "2025-12-27T10:05:00Z",
    "turn_count": 3,
    "last_message_preview": "The latency issues appear to be caused by..."
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Session UUID |
| `title` | string \| null | Auto-generated from first message (max 50 chars) |
| `created_at` | string | ISO-8601 timestamp |
| `updated_at` | string \| null | ISO-8601 timestamp of last activity |
| `turn_count` | integer | Number of turns in session |
| `last_message_preview` | string \| null | Truncated last message (max 100 chars + "...") |

**Note:** Sessions are sorted by `updated_at` descending (most recent first).

---

### 5.4 Get Session

Get a specific session with all its turns.

```http
GET /workspaces/{workspace_id}/sessions/{session_id}
```

#### Response (200 OK)

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "workspace_id": "770e8400-e29b-41d4-a716-446655440002",
  "user_id": "880e8400-e29b-41d4-a716-446655440003",
  "title": "Why is my API slow?",
  "created_at": "2025-12-27T10:00:00Z",
  "updated_at": "2025-12-27T10:05:00Z",
  "turns": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "user_message": "Why is my API returning 500 errors?",
      "final_response": "Based on my analysis of your CloudWatch logs...",
      "status": "completed",
      "feedback_score": 5,
      "created_at": "2025-12-27T10:00:00Z"
    }
  ]
}
```

**Note:** Turns in the response are `ChatTurnSummary` objects (without steps). Use the Get Turn endpoint for full step details.

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 404 | `Session not found` | Invalid session_id or no access |

---

### 5.5 Update Session

Rename a session.

```http
PATCH /workspaces/{workspace_id}/sessions/{session_id}
```

#### Request Body

```json
{
  "title": "API Performance Investigation"
}
```

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `title` | string | Yes | 1-255 chars | New session title |

#### Response (200 OK)

Returns the updated `ChatSessionResponse` object.

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 400 | Validation error | Title empty or too long |
| 404 | `Session not found` | Invalid session_id or no access |

---

### 5.6 Delete Session

Delete a session and all its turns.

```http
DELETE /workspaces/{workspace_id}/sessions/{session_id}
```

#### Response

```
204 No Content
```

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 404 | `Session not found` | Invalid session_id or no access |

**Warning:** This action is irreversible. All turns and steps within the session are permanently deleted.

---

### 5.7 Get Turn

Get a specific turn with all processing steps.

```http
GET /workspaces/{workspace_id}/turns/{turn_id}
```

#### Response (200 OK)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660e8400-e29b-41d4-a716-446655440001",
  "user_message": "Why is my API returning 500 errors?",
  "final_response": "Based on my analysis...",
  "status": "completed",
  "job_id": "990e8400-e29b-41d4-a716-446655440004",
  "feedback_score": null,
  "feedback_comment": null,
  "created_at": "2025-12-27T10:00:00Z",
  "updated_at": "2025-12-27T10:01:30Z",
  "steps": [
    {
      "id": "aa0e8400-e29b-41d4-a716-446655440005",
      "step_type": "status",
      "tool_name": null,
      "content": "Starting analysis...",
      "status": "completed",
      "sequence": 1,
      "created_at": "2025-12-27T10:00:01Z"
    },
    {
      "id": "bb0e8400-e29b-41d4-a716-446655440006",
      "step_type": "tool_call",
      "tool_name": "Searching CloudWatch logs...",
      "content": "Found 15 error entries",
      "status": "completed",
      "sequence": 2,
      "created_at": "2025-12-27T10:00:05Z"
    }
  ]
}
```

**Note:** Steps are sorted by `sequence` (chronological order).

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 404 | `Turn not found` | Invalid turn_id or no access |

---

### 5.8 Submit Feedback

Submit user feedback for a turn.

```http
POST /workspaces/{workspace_id}/turns/{turn_id}/feedback
```

#### Request Body

```json
{
  "score": 5,
  "comment": "Very helpful analysis!"
}
```

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `score` | integer | Yes | 1-5 | 1 = thumbs down, 5 = thumbs up |
| `comment` | string | No | Max 1000 chars | Optional text feedback |

#### Response (200 OK)

```json
{
  "turn_id": "550e8400-e29b-41d4-a716-446655440000",
  "score": 5,
  "comment": "Very helpful analysis!",
  "message": "Feedback submitted successfully."
}
```

#### Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 400 | Validation error | Score out of range |
| 404 | `Turn not found` | Invalid turn_id or no access |

**Note:** Feedback can be submitted multiple times (overwrites previous feedback).

---

## 6. SSE Streaming Protocol

### Connection Setup

```javascript
const eventSource = new EventSource(
  `${BASE_URL}/workspaces/${workspaceId}/turns/${turnId}/stream`,
  {
    headers: {
      'Authorization': `Bearer ${accessToken}`
    }
  }
);
```

**Important:** Native `EventSource` does not support custom headers. Use a library like `@microsoft/fetch-event-source` or implement with `fetch()`:

```javascript
import { fetchEventSource } from '@microsoft/fetch-event-source';

await fetchEventSource(
  `${BASE_URL}/workspaces/${workspaceId}/turns/${turnId}/stream`,
  {
    headers: {
      'Authorization': `Bearer ${accessToken}`,
    },
    onmessage(event) {
      const data = JSON.parse(event.data);
      handleEvent(data);
    },
    onerror(err) {
      // Handle error
    }
  }
);
```

### Event Format

All events follow this format:

```
data: {"event": "event_type", ...payload}\n\n
```

### Event Types

#### 1. `status` - Status Update

General status message about the analysis progress.

```json
{
  "event": "status",
  "content": "Starting analysis..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Always `"status"` |
| `content` | string | Human-readable status message |

**When to display:** Show as a subtle status indicator or progress message.

---

#### 2. `tool_start` - Tool Execution Started

An RCA tool has started executing.

```json
{
  "event": "tool_start",
  "tool_name": "Searching CloudWatch logs...",
  "step_id": "step_1"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Always `"tool_start"` |
| `tool_name` | string | User-friendly tool description |
| `step_id` | string | Unique step identifier |

**Available Tool Names:**

| Category | Tool Names |
|----------|------------|
| Logs | `Checking error logs...`, `Fetching logs...` |
| Metrics | `Analyzing CPU metrics...`, `Analyzing memory usage...`, `Checking HTTP latency...`, `Fetching metrics...` |
| GitHub | `Listing GitHub repositories...`, `Discovering all services in workspace...`, `Reading code file...`, `Searching codebase...`, `Checking recent commits...`, `Reviewing pull requests...` |
| CloudWatch | `Listing CloudWatch log groups...`, `Filtering CloudWatch log events...`, `Searching CloudWatch logs...`, `Running CloudWatch Insights query...`, `Fetching CloudWatch metric statistics...` |
| Datadog | `Searching Datadog logs...`, `Listing Datadog logs...`, `Querying Datadog metrics...`, `Fetching Datadog time series...` |
| New Relic | `Querying New Relic logs...`, `Searching New Relic logs...`, `Querying New Relic metrics...`, `Fetching New Relic time series...` |
| Grafana | `Discovering datasources...`, `Discovering available labels...`, `Fetching label values...` |

**When to display:** Show a spinner/loading indicator with the tool name.

---

#### 3. `tool_end` - Tool Execution Completed

A tool has finished executing.

```json
{
  "event": "tool_end",
  "tool_name": "Searching CloudWatch logs...",
  "status": "completed",
  "content": "Found 15 error entries in the last hour"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Always `"tool_end"` |
| `tool_name` | string | Tool that completed |
| `status` | string | `"completed"` or `"failed"` |
| `content` | string \| null | Result summary (max 500 chars) |

**When to display:** Update the tool step to show completion. Optionally show content as a collapsible detail.

---

#### 4. `thinking` - Agent Reasoning

The AI agent is thinking/reasoning about the problem.

```json
{
  "event": "thinking",
  "content": "The error pattern suggests a database connection timeout..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Always `"thinking"` |
| `content` | string | Agent's reasoning (max 500 chars) |

**When to display:** Optional. Can show as italicized "thinking" text or skip entirely.

---

#### 5. `complete` - Processing Complete

Analysis is finished. Contains the final AI response.

```json
{
  "event": "complete",
  "final_response": "## Analysis Summary\n\nBased on my investigation of your CloudWatch logs and metrics, I found that..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Always `"complete"` |
| `final_response` | string | Complete AI response (Markdown formatted) |

**When to display:** Render as the main response. Parse Markdown for rich formatting.

**Important:** Close the SSE connection after receiving this event.

---

#### 6. `error` - Processing Error

An error occurred during processing.

```json
{
  "event": "error",
  "message": "Failed to connect to CloudWatch"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | Always `"error"` |
| `message` | string | Error description |

**When to display:** Show error message to user. Allow retry.

**Important:** Close the SSE connection after receiving this event.

---

### Event Sequence

Typical event sequence for a successful analysis:

```
1. status: "Starting analysis..."
2. tool_start: "Listing CloudWatch log groups..."
3. tool_end: "Listing CloudWatch log groups..." (completed)
4. tool_start: "Searching CloudWatch logs..."
5. tool_end: "Searching CloudWatch logs..." (completed)
6. thinking: "The errors seem to correlate with..."
7. tool_start: "Checking recent commits..."
8. tool_end: "Checking recent commits..." (completed)
9. complete: "## Analysis Summary\n\n..."
```

### Reconnection Handling

If the connection drops:

1. Reconnect to the same `GET /turns/{turn_id}/stream` endpoint
2. The backend will:
   - First replay any existing steps from the database
   - Then subscribe to Redis for new events
3. Duplicate events may occur - deduplicate by `step_id` or `sequence`

---

## 7. Complete Integration Flows

### 7.1 New Conversation

```
User types message → POST /chat (no session_id)
                         ↓
              Receive turn_id + session_id
                         ↓
         Connect to GET /turns/{turn_id}/stream
                         ↓
              Handle SSE events until 'complete'
                         ↓
              Display final response
                         ↓
         Store session_id for follow-up messages
```

**Code Example:**

```typescript
async function startNewConversation(workspaceId: string, message: string) {
  // 1. Send message
  const response = await fetch(`${BASE_URL}/workspaces/${workspaceId}/chat`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
  });

  const { turn_id, session_id } = await response.json();

  // 2. Store session for follow-ups
  setCurrentSessionId(session_id);

  // 3. Stream response
  await streamTurnResponse(workspaceId, turn_id);
}
```

### 7.2 Continue Conversation

```
User types follow-up → POST /chat (with session_id)
                            ↓
                 Receive new turn_id
                            ↓
            Connect to GET /turns/{turn_id}/stream
                            ↓
                 Handle SSE events until 'complete'
```

**Code Example:**

```typescript
async function continueConversation(
  workspaceId: string,
  sessionId: string,
  message: string
) {
  const response = await fetch(`${BASE_URL}/workspaces/${workspaceId}/chat`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,  // Include session_id
    }),
  });

  const { turn_id } = await response.json();
  await streamTurnResponse(workspaceId, turn_id);
}
```

### 7.3 Load Existing Session

```
User clicks session → GET /sessions/{session_id}
                           ↓
                Display all turns with responses
                           ↓
       Check if any turn is 'processing'
                           ↓
   If processing: Connect to that turn's SSE stream
```

**Code Example:**

```typescript
async function loadSession(workspaceId: string, sessionId: string) {
  const response = await fetch(
    `${BASE_URL}/workspaces/${workspaceId}/sessions/${sessionId}`,
    {
      headers: { 'Authorization': `Bearer ${accessToken}` },
    }
  );

  const session = await response.json();

  // Display existing turns
  session.turns.forEach(displayTurn);

  // Check for in-progress turn
  const processingTurn = session.turns.find(
    t => t.status === 'processing' || t.status === 'pending'
  );

  if (processingTurn) {
    // Resume streaming
    await streamTurnResponse(workspaceId, processingTurn.id);
  }
}
```

### 7.4 SSE Streaming Implementation

```typescript
import { fetchEventSource } from '@microsoft/fetch-event-source';

async function streamTurnResponse(workspaceId: string, turnId: string) {
  const steps: Map<string, Step> = new Map();

  await fetchEventSource(
    `${BASE_URL}/workspaces/${workspaceId}/turns/${turnId}/stream`,
    {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
      },

      onmessage(event) {
        const data = JSON.parse(event.data);

        switch (data.event) {
          case 'status':
            updateStatus(data.content);
            break;

          case 'tool_start':
            steps.set(data.step_id, {
              id: data.step_id,
              name: data.tool_name,
              status: 'running',
            });
            renderSteps(steps);
            break;

          case 'tool_end':
            // Find and update the step
            for (const [id, step] of steps) {
              if (step.name === data.tool_name && step.status === 'running') {
                step.status = data.status;
                step.content = data.content;
                break;
              }
            }
            renderSteps(steps);
            break;

          case 'thinking':
            showThinking(data.content);
            break;

          case 'complete':
            hideLoading();
            renderFinalResponse(data.final_response);
            break;

          case 'error':
            hideLoading();
            showError(data.message);
            break;
        }
      },

      onerror(err) {
        console.error('SSE error:', err);
        // Implement retry logic
      },
    }
  );
}
```

---

## 8. Error Handling

### HTTP Error Responses

All errors follow this format:

```json
{
  "detail": "Error message here"
}
```

### Error Status Codes

| Status | Meaning | Action |
|--------|---------|--------|
| 400 | Bad Request | Validation failed - check request body |
| 401 | Unauthorized | Token expired - refresh or re-login |
| 403 | Forbidden | No access to resource |
| 404 | Not Found | Resource doesn't exist or no access |
| 422 | Unprocessable Entity | Request validation failed |
| 500 | Internal Server Error | Retry or contact support |

### SSE Error Handling

```typescript
await fetchEventSource(url, {
  // ...
  onerror(err) {
    if (err instanceof Response) {
      if (err.status === 401) {
        // Token expired - refresh and retry
        await refreshToken();
        return; // Retry automatically
      }
      if (err.status === 404) {
        // Turn not found
        showError('Conversation not found');
        throw err; // Stop retrying
      }
    }
    // Network error - retry automatically
    console.error('Connection error, retrying...');
  },
  openWhenHidden: true, // Keep connection when tab is hidden
});
```

### Retry Strategy

For transient errors, implement exponential backoff:

```typescript
const MAX_RETRIES = 3;
const BASE_DELAY = 1000;

async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  let lastError: Error;

  for (let i = 0; i < MAX_RETRIES; i++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (i < MAX_RETRIES - 1) {
        await sleep(BASE_DELAY * Math.pow(2, i));
      }
    }
  }

  throw lastError;
}
```

---

## 9. Best Practices

### 9.1 Session Management

- **Store session_id** after creating a new conversation
- **Display session list** ordered by `updated_at` (most recent first)
- **Auto-generate titles** from first message (backend handles this)
- **Allow renaming** sessions for user organization

### 9.2 Message Input

- **Disable send button** while processing
- **Clear input** after successful send
- **Show character count** (max 10,000)
- **Prevent empty messages**

### 9.3 Response Display

- **Parse Markdown** in final responses (code blocks, lists, headers)
- **Syntax highlight** code blocks
- **Show copy button** for code snippets
- **Render links** as clickable

### 9.4 Progress Indication

- **Show skeleton/loading** immediately after sending
- **Display tool steps** as they execute
- **Use animations** for running steps (spinner, pulse)
- **Collapse completed steps** to reduce visual noise

### 9.5 Error Recovery

- **Show retry button** on errors
- **Preserve user input** on failure
- **Auto-reconnect** SSE on network issues
- **Clear error state** on retry

### 9.6 Performance

- **Virtualize long session lists**
- **Lazy load session history**
- **Debounce input validation**
- **Cancel pending requests** on component unmount

### 9.7 Accessibility

- **Announce new messages** to screen readers
- **Keyboard navigation** for session list
- **Focus management** after actions
- **Loading state announcements**

---

## 10. TypeScript Type Definitions

```typescript
// ============================================================
// Enums
// ============================================================

export enum TurnStatus {
  PENDING = 'pending',
  PROCESSING = 'processing',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

export enum StepType {
  TOOL_CALL = 'tool_call',
  THINKING = 'thinking',
  STATUS = 'status',
}

export enum StepStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

// ============================================================
// Request Types
// ============================================================

export interface SendMessageRequest {
  message: string;           // 1-10,000 characters
  session_id?: string;       // UUID, optional
}

export interface UpdateSessionRequest {
  title: string;             // 1-255 characters
}

export interface SubmitFeedbackRequest {
  score: 1 | 2 | 3 | 4 | 5;  // 1=thumbs down, 5=thumbs up
  comment?: string;          // Max 1000 characters
}

// ============================================================
// Response Types
// ============================================================

export interface SendMessageResponse {
  turn_id: string;
  session_id: string;
  message: string;
}

export interface FeedbackResponse {
  turn_id: string;
  score: number;
  comment: string | null;
  message: string;
}

export interface TurnStepResponse {
  id: string;
  step_type: StepType;
  tool_name: string | null;
  content: string | null;
  status: StepStatus;
  sequence: number;
  created_at: string;        // ISO-8601
}

export interface ChatTurnResponse {
  id: string;
  session_id: string;
  user_message: string;
  final_response: string | null;
  status: TurnStatus;
  job_id: string | null;
  feedback_score: number | null;
  feedback_comment: string | null;
  created_at: string;        // ISO-8601
  updated_at: string | null; // ISO-8601
  steps: TurnStepResponse[];
}

export interface ChatTurnSummary {
  id: string;
  user_message: string;
  final_response: string | null;
  status: TurnStatus;
  feedback_score: number | null;
  created_at: string;        // ISO-8601
}

export interface ChatSessionResponse {
  id: string;
  workspace_id: string;
  user_id: string;
  title: string | null;
  created_at: string;        // ISO-8601
  updated_at: string | null; // ISO-8601
  turns: ChatTurnSummary[];
}

export interface ChatSessionSummary {
  id: string;
  title: string | null;
  created_at: string;        // ISO-8601
  updated_at: string | null; // ISO-8601
  turn_count: number;
  last_message_preview: string | null;
}

// ============================================================
// SSE Event Types
// ============================================================

export interface SSEStatusEvent {
  event: 'status';
  content: string;
}

export interface SSEToolStartEvent {
  event: 'tool_start';
  tool_name: string;
  step_id: string;
}

export interface SSEToolEndEvent {
  event: 'tool_end';
  tool_name: string;
  status: 'completed' | 'failed';
  content: string | null;
}

export interface SSEThinkingEvent {
  event: 'thinking';
  content: string;
}

export interface SSECompleteEvent {
  event: 'complete';
  final_response: string;
}

export interface SSEErrorEvent {
  event: 'error';
  message: string;
}

export type SSEEvent =
  | SSEStatusEvent
  | SSEToolStartEvent
  | SSEToolEndEvent
  | SSEThinkingEvent
  | SSECompleteEvent
  | SSEErrorEvent;

// ============================================================
// API Client Interface
// ============================================================

export interface ChatAPI {
  // Messages
  sendMessage(
    workspaceId: string,
    request: SendMessageRequest
  ): Promise<SendMessageResponse>;

  streamTurn(
    workspaceId: string,
    turnId: string,
    handlers: {
      onStatus?: (event: SSEStatusEvent) => void;
      onToolStart?: (event: SSEToolStartEvent) => void;
      onToolEnd?: (event: SSEToolEndEvent) => void;
      onThinking?: (event: SSEThinkingEvent) => void;
      onComplete?: (event: SSECompleteEvent) => void;
      onError?: (event: SSEErrorEvent) => void;
    }
  ): Promise<void>;

  // Sessions
  listSessions(
    workspaceId: string,
    options?: { limit?: number; offset?: number }
  ): Promise<ChatSessionSummary[]>;

  getSession(
    workspaceId: string,
    sessionId: string
  ): Promise<ChatSessionResponse>;

  updateSession(
    workspaceId: string,
    sessionId: string,
    request: UpdateSessionRequest
  ): Promise<ChatSessionResponse>;

  deleteSession(
    workspaceId: string,
    sessionId: string
  ): Promise<void>;

  // Turns
  getTurn(
    workspaceId: string,
    turnId: string
  ): Promise<ChatTurnResponse>;

  submitFeedback(
    workspaceId: string,
    turnId: string,
    request: SubmitFeedbackRequest
  ): Promise<FeedbackResponse>;
}
```

---

## Appendix A: Quick Reference Card

### Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/workspaces/{wid}/chat` | Send message |
| `GET` | `/workspaces/{wid}/turns/{tid}/stream` | SSE stream |
| `GET` | `/workspaces/{wid}/sessions` | List sessions |
| `GET` | `/workspaces/{wid}/sessions/{sid}` | Get session |
| `PATCH` | `/workspaces/{wid}/sessions/{sid}` | Update session |
| `DELETE` | `/workspaces/{wid}/sessions/{sid}` | Delete session |
| `GET` | `/workspaces/{wid}/turns/{tid}` | Get turn |
| `POST` | `/workspaces/{wid}/turns/{tid}/feedback` | Submit feedback |

### SSE Events Summary

| Event | Fields | Terminal? |
|-------|--------|-----------|
| `status` | `content` | No |
| `tool_start` | `tool_name`, `step_id` | No |
| `tool_end` | `tool_name`, `status`, `content` | No |
| `thinking` | `content` | No |
| `complete` | `final_response` | **Yes** |
| `error` | `message` | **Yes** |

---

## Appendix B: Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-27 | Initial release |

---

*For questions or issues, contact the backend team or file an issue in the repository.*
