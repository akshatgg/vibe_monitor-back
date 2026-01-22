#!/bin/bash
set -e

# Debug ECS Deployment Helper Script
# Usage: ./scripts/debug-deployment.sh [dev|prod] [task-id]
#
# If no task-id is provided, shows recent tasks and their logs
# If task-id is provided, shows detailed logs for that specific task

ENVIRONMENT=${1:-dev}
TASK_ID=$2

CLUSTER="vm-api-cluster-${ENVIRONMENT}"
SERVICE="vm-api-svc-${ENVIRONMENT}"
LOG_GROUP="/ecs/vm-api-logs-${ENVIRONMENT}"
REGION="us-west-1"

if [ -z "$TASK_ID" ]; then
  echo "================================================"
  echo "🔍 Recent Tasks Started by Deployment"
  echo "================================================"
  echo ""

  # Get recent task starts with timestamps
  echo "📋 Tasks started in the last hour:"
  aws ecs describe-services \
    --cluster $CLUSTER \
    --services $SERVICE \
    --region $REGION \
    --output json | \
    jq -r '.services[0].events[] | select(.message | contains("has started 1 tasks")) | "\(.createdAt) - \(.message)"' | \
    head -10

  echo ""
  echo "================================================"
  echo "💡 To see logs for a specific task, run:"
  echo "  ./scripts/debug-deployment.sh $ENVIRONMENT TASK_ID"
  echo "================================================"
  exit 0
fi

echo "================================================"
echo "📦 Task Details: $TASK_ID"
echo "================================================"
echo ""

# Get task details
TASK_INFO=$(aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ID \
  --region $REGION \
  --output json)

IMAGE=$(echo "$TASK_INFO" | jq -r '.tasks[0].containers[0].image // "unknown"')
TASKDEF=$(echo "$TASK_INFO" | jq -r '.tasks[0].taskDefinitionArn // "unknown"' | rev | cut -d'/' -f1 | rev)
STATUS=$(echo "$TASK_INFO" | jq -r '.tasks[0].lastStatus // "unknown"')
STARTED=$(echo "$TASK_INFO" | jq -r '.tasks[0].startedAt // "N/A"')
STOPPED=$(echo "$TASK_INFO" | jq -r '.tasks[0].stoppedAt // "N/A"')
STOPPED_REASON=$(echo "$TASK_INFO" | jq -r '.tasks[0].stoppedReason // "N/A"')
EXIT_CODE=$(echo "$TASK_INFO" | jq -r '.tasks[0].containers[0].exitCode // "N/A"')

echo "🏷️  Task Definition: $TASKDEF"
echo "📦 Image: $IMAGE"
echo "📊 Status: $STATUS"
echo "🕐 Started: $STARTED"
if [ "$STOPPED" != "N/A" ]; then
  echo "🛑 Stopped: $STOPPED"
  echo "❌ Stopped Reason: $STOPPED_REASON"
  echo "🔢 Exit Code: $EXIT_CODE"
fi
echo ""

echo "================================================"
echo "📝 Container Logs"
echo "================================================"
echo ""

LOG_STREAM="ecs/app/${TASK_ID}"
echo "Log Stream: $LOG_STREAM"
echo ""

# Get logs
if aws logs get-log-events \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$LOG_STREAM" \
  --region $REGION \
  --limit 200 \
  --output json 2>/dev/null | jq -r '.events[].message'; then
  echo ""
else
  echo "⚠️  No logs found for this task"
  echo ""
  echo "This could mean:"
  echo "  - Task hasn't started logging yet"
  echo "  - Task ID is incorrect"
  echo "  - Log stream doesn't exist"
fi

echo "================================================"
echo "💡 To follow logs in real-time:"
echo "  aws logs tail $LOG_GROUP --log-stream-names $LOG_STREAM --follow --region $REGION --format short"
echo "================================================"
