#!/bin/bash

echo "🚀 Starting VM API Log Ingestion System"
echo "======================================="

# Start the application with all services
export CLICKHOUSE_HOST=lbag3nv175.us-west-2.aws.clickhouse.cloud
export CLICKHOUSE_PORT=8443
export CLICKHOUSE_USER=default
export CLICKHOUSE_PASSWORD=3_Y_fBHt3aJc3
export CLICKHOUSE_DATABASE=default
export CLICKHOUSE_SECURE=true
export OTEL_GRPC_PORT=4317
export OTEL_HTTP_PORT=4318
export LOG_BATCH_SIZE=2
export LOG_BATCH_TIMEOUT=30

echo "📋 Environment Configuration:"
echo "  ClickHouse Host: $CLICKHOUSE_HOST:$CLICKHOUSE_PORT"
echo "  Database: $CLICKHOUSE_DATABASE"
echo "  OTEL gRPC Port: $OTEL_GRPC_PORT"
echo "  Batch Size: $LOG_BATCH_SIZE"
echo ""

echo "🌟 Starting FastAPI application..."
echo "   - REST API: http://localhost:8080"
echo "   - Interactive Docs: http://localhost:8080/docs"
echo "   - OpenTelemetry gRPC Collector: localhost:4317"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload