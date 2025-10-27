#!/bin/sh
set -e

echo "🔄 Running database migrations..."
start_time=$(date +%s)

if alembic upgrade head; then
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    echo "✅ Migrations completed successfully in ${duration}s"
else
    echo "❌ Migration failed! Check logs for details."
    echo "   Database may be unreachable or migration has errors."
    exit 1
fi

echo "🚀 Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
