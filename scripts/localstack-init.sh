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

echo "🎉 LocalStack initialization complete!"