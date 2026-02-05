#!/bin/bash

echo "🚀 Initializing LocalStack SQS queue..."

# Wait for LocalStack to be ready
max_retries=${LOCALSTACK_MAX_RETRIES:-30}
retry_count=0

awslocal sqs list-queues > /dev/null 2>&1
while [ $? -ne 0 ]; do
    echo "⏳ Waiting for LocalStack SQS to be ready..."
    sleep 2
    retry_count=$((retry_count + 1))

    if [ $retry_count -ge $max_retries ]; then
        echo "❌ Failed to connect to LocalStack after $max_retries attempts. Exiting..."
        exit 1
    fi

    awslocal sqs list-queues > /dev/null 2>&1
done

# Create the SQS queue
QUEUE_NAME="vm-api-queue"
echo "📋 Creating SQS queue: $QUEUE_NAME"

awslocal sqs create-queue \
    --queue-name $QUEUE_NAME \
    --attributes VisibilityTimeoutSeconds=300,MessageRetentionPeriod=1209600

if [ $? -eq 0 ]; then
    echo "✅ SQS queue '$QUEUE_NAME' created successfully"
else
    echo "❌ Failed to create SQS queue '$QUEUE_NAME'"
fi

# Create health review DLQ first (needed for redrive policy)
HEALTH_DLQ_NAME="health-review-dlq"
echo "📋 Creating SQS dead letter queue: $HEALTH_DLQ_NAME"

awslocal sqs create-queue \
    --queue-name $HEALTH_DLQ_NAME \
    --attributes VisibilityTimeoutSeconds=600,MessageRetentionPeriod=1209600

if [ $? -eq 0 ]; then
    echo "✅ SQS queue '$HEALTH_DLQ_NAME' created successfully"
else
    echo "❌ Failed to create SQS queue '$HEALTH_DLQ_NAME'"
fi

# Get DLQ ARN for redrive policy
HEALTH_DLQ_ARN=$(awslocal sqs get-queue-attributes \
    --queue-url "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/$HEALTH_DLQ_NAME" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text)

# Create health review queue with redrive policy to DLQ
HEALTH_QUEUE_NAME="health-review-queue"
echo "📋 Creating SQS queue: $HEALTH_QUEUE_NAME (with DLQ redrive after 3 failures)"

awslocal sqs create-queue \
    --queue-name $HEALTH_QUEUE_NAME \
    --attributes "{\"VisibilityTimeoutSeconds\":\"600\",\"MessageRetentionPeriod\":\"1209600\",\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$HEALTH_DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}"

if [ $? -eq 0 ]; then
    echo "✅ SQS queue '$HEALTH_QUEUE_NAME' created successfully with DLQ"
else
    echo "❌ Failed to create SQS queue '$HEALTH_QUEUE_NAME'"
fi

# List queues to confirm
echo "📄 Available queues:"
awslocal sqs list-queues

# Create S3 bucket for chat file uploads
BUCKET_NAME="vibe-monitor-chat-files-local"
echo "📦 Creating S3 bucket: $BUCKET_NAME"

awslocal s3 mb s3://$BUCKET_NAME 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✅ S3 bucket '$BUCKET_NAME' created successfully"
else
    echo "ℹ️  S3 bucket '$BUCKET_NAME' may already exist"
fi

# Configure CORS for the S3 bucket (required for browser downloads via presigned URLs)
echo "🔧 Configuring CORS for S3 bucket..."
awslocal s3api put-bucket-cors --bucket $BUCKET_NAME --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
      "AllowedOrigins": ["http://localhost:3000", "http://localhost:3001", "https://*.vercel.app", "https://vibemonitor.ai", "https://*.vibemonitor.ai"],
      "ExposeHeaders": ["Content-Length", "Content-Type", "Content-Disposition"],
      "MaxAgeSeconds": 3600
    }
  ]
}'
echo "✅ CORS configured for '$BUCKET_NAME'"

echo "🎉 LocalStack initialization complete!"