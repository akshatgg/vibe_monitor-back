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

    # List queues to confirm
    echo "📄 Available queues:"
    awslocal sqs list-queues
else
    echo "❌ Failed to create SQS queue '$QUEUE_NAME'"
fi

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