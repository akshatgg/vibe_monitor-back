# Deployment Webhooks

This document explains how to integrate your CI/CD pipeline with Vibe Monitor to track deployments.

## Overview

Vibe Monitor can track which branch and commit is deployed to each environment. This enables:
- **Accurate RCA**: Root cause analysis uses the correct codebase version
- **Deployment History**: Track all deployments across environments
- **Audit Trail**: Know what was deployed, when, and by which CI/CD system

## Authentication

All webhook requests require a Workspace API Key in the `X-Workspace-Key` header.

### Creating an API Key

1. Go to **Settings > API Keys** in the Vibe Monitor dashboard
2. Click **Create API Key**
3. Give it a descriptive name (e.g., "GitHub Actions", "Jenkins CI")
4. Copy the key immediately - it won't be shown again

## Webhook Endpoint

```
POST /api/v1/deployments/webhook
```

### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `X-Workspace-Key` | Yes | Your workspace API key |
| `Content-Type` | Yes | Must be `application/json` |

### Request Body

```json
{
  "environment": "production",
  "repository": "owner/repo",
  "branch": "main",
  "commit_sha": "abc123def456789...",
  "status": "success",
  "source": "github_actions",
  "deployed_at": "2024-01-15T10:30:00Z",
  "extra_data": {
    "workflow_run_id": "12345"
  }
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `environment` | string | Yes | Environment name (e.g., "production", "staging", "dev") |
| `repository` | string | Yes | Repository full name (e.g., "owner/repo") |
| `branch` | string | No | Branch name that was deployed |
| `commit_sha` | string | No | Full commit SHA (40 characters) |
| `status` | string | No | Deployment status: `pending`, `in_progress`, `success`, `failed`, `cancelled`. Default: `success` |
| `source` | string | No | CI/CD source: `webhook`, `github_actions`, `argocd`, `jenkins`. Default: `webhook` |
| `deployed_at` | string | No | ISO 8601 timestamp. Default: current time |
| `extra_data` | object | No | Any additional metadata (stored as JSON) |

### Response

**Success (201 Created):**
```json
{
  "id": "uuid-of-deployment",
  "environment_id": "uuid-of-environment",
  "repo_full_name": "owner/repo",
  "branch": "main",
  "commit_sha": "abc123...",
  "status": "success",
  "source": "github_actions",
  "deployed_at": "2024-01-15T10:30:00Z",
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Error (401 Unauthorized):**
```json
{
  "detail": "Invalid API key"
}
```

---

## CI/CD Integration Examples

### GitHub Actions

Add this step to your deployment workflow:

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # ... your deployment steps ...

      - name: Report Deployment to Vibe Monitor
        if: success()
        run: |
          curl -X POST "${{ secrets.VM_API_URL }}/api/v1/deployments/webhook" \
            -H "X-Workspace-Key: ${{ secrets.VM_WORKSPACE_KEY }}" \
            -H "Content-Type: application/json" \
            -d '{
              "environment": "production",
              "repository": "${{ github.repository }}",
              "branch": "${{ github.ref_name }}",
              "commit_sha": "${{ github.sha }}",
              "status": "success",
              "source": "github_actions",
              "extra_data": {
                "workflow_run_id": "${{ github.run_id }}",
                "actor": "${{ github.actor }}"
              }
            }'
```

**Required Secrets:**
- `VM_API_URL`: Your Vibe Monitor API URL (e.g., `https://api.vibemonitor.com`)
- `VM_WORKSPACE_KEY`: Your workspace API key

### Generic Shell Script

```bash
#!/bin/bash

# Configuration
VM_API_URL="${VM_API_URL:-https://api.vibemonitor.com}"
VM_WORKSPACE_KEY="${VM_WORKSPACE_KEY}"
ENVIRONMENT="${ENVIRONMENT:-production}"
REPOSITORY="${REPOSITORY}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
COMMIT_SHA="${COMMIT_SHA:-$(git rev-parse HEAD)}"

# Report deployment
curl -X POST "${VM_API_URL}/api/v1/deployments/webhook" \
  -H "X-Workspace-Key: ${VM_WORKSPACE_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"environment\": \"${ENVIRONMENT}\",
    \"repository\": \"${REPOSITORY}\",
    \"branch\": \"${BRANCH}\",
    \"commit_sha\": \"${COMMIT_SHA}\",
    \"status\": \"success\",
    \"source\": \"webhook\"
  }"
```

### Jenkins Pipeline

```groovy
pipeline {
    agent any

    environment {
        VM_API_URL = credentials('vm-api-url')
        VM_WORKSPACE_KEY = credentials('vm-workspace-key')
    }

    stages {
        stage('Deploy') {
            steps {
                // ... your deployment steps ...
            }
        }

        stage('Report Deployment') {
            steps {
                script {
                    def response = httpRequest(
                        url: "${VM_API_URL}/api/v1/deployments/webhook",
                        httpMode: 'POST',
                        contentType: 'APPLICATION_JSON',
                        customHeaders: [[name: 'X-Workspace-Key', value: VM_WORKSPACE_KEY]],
                        requestBody: """{
                            "environment": "production",
                            "repository": "${env.GIT_URL.replaceAll('.git$', '').split('/')[-2..-1].join('/')}",
                            "branch": "${env.GIT_BRANCH}",
                            "commit_sha": "${env.GIT_COMMIT}",
                            "status": "success",
                            "source": "jenkins",
                            "extra_data": {
                                "build_number": "${env.BUILD_NUMBER}",
                                "job_name": "${env.JOB_NAME}"
                            }
                        }"""
                    )
                    echo "Deployment reported: ${response.status}"
                }
            }
        }
    }
}
```

### ArgoCD

Create a resource hook that runs after sync:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: report-deployment
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: report
        image: curlimages/curl:latest
        env:
        - name: VM_API_URL
          valueFrom:
            secretKeyRef:
              name: vibe-monitor
              key: api-url
        - name: VM_WORKSPACE_KEY
          valueFrom:
            secretKeyRef:
              name: vibe-monitor
              key: workspace-key
        command:
        - sh
        - -c
        - |
          curl -X POST "${VM_API_URL}/api/v1/deployments/webhook" \
            -H "X-Workspace-Key: ${VM_WORKSPACE_KEY}" \
            -H "Content-Type: application/json" \
            -d '{
              "environment": "production",
              "repository": "your-org/your-repo",
              "branch": "main",
              "status": "success",
              "source": "argocd"
            }'
      restartPolicy: Never
```

### GitLab CI

```yaml
stages:
  - deploy
  - notify

deploy:
  stage: deploy
  script:
    # ... your deployment steps ...

report_deployment:
  stage: notify
  script:
    - |
      curl -X POST "${VM_API_URL}/api/v1/deployments/webhook" \
        -H "X-Workspace-Key: ${VM_WORKSPACE_KEY}" \
        -H "Content-Type: application/json" \
        -d "{
          \"environment\": \"production\",
          \"repository\": \"${CI_PROJECT_PATH}\",
          \"branch\": \"${CI_COMMIT_BRANCH}\",
          \"commit_sha\": \"${CI_COMMIT_SHA}\",
          \"status\": \"success\",
          \"source\": \"webhook\",
          \"extra_data\": {
            \"pipeline_id\": \"${CI_PIPELINE_ID}\"
          }
        }"
  when: on_success
```

---

## Deployment Statuses

Report the appropriate status based on your deployment outcome:

| Status | Description |
|--------|-------------|
| `pending` | Deployment is queued but not started |
| `in_progress` | Deployment is currently running |
| `success` | Deployment completed successfully |
| `failed` | Deployment failed |
| `cancelled` | Deployment was cancelled |

**Example: Reporting deployment progress**

```bash
# Report start
curl -X POST ... -d '{"status": "in_progress", ...}'

# After deployment completes
curl -X POST ... -d '{"status": "success", ...}'

# Or if it fails
curl -X POST ... -d '{"status": "failed", ...}'
```

---

## Troubleshooting

### 401 Unauthorized
- Verify your API key is correct
- Ensure the key hasn't been deleted
- Check that the key belongs to the correct workspace

### 404 Not Found
- Verify the environment name matches one configured in Vibe Monitor
- Environment names are case-sensitive

### 422 Validation Error
- Check that `environment` and `repository` fields are provided
- Ensure `commit_sha` is a valid SHA (40 hex characters) if provided
- Verify `deployed_at` is a valid ISO 8601 timestamp if provided

---

## Best Practices

1. **Always report on success**: Only report `success` status after deployment is verified
2. **Include commit SHA**: This enables precise code matching during RCA
3. **Use descriptive API key names**: Makes it easy to identify which CI/CD system is using which key
4. **Store secrets securely**: Never hardcode API keys in your CI/CD configuration
5. **Handle failures gracefully**: Don't fail your deployment if the webhook fails
