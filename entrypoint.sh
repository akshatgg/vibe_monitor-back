#!/bin/sh
set -e

echo "=== Container starting ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Python: $(python --version 2>&1)"
echo "Alembic: $(alembic --version 2>&1 | head -1)"

echo ""
echo "🔄 Running database migrations..."
start_time=$(date +%s)

# Show current database state first
echo "Checking current alembic state..."
alembic current 2>&1 || echo "Warning: Could not get current alembic state"

echo ""
echo "Running: alembic upgrade head"
if alembic upgrade head 2>&1; then
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    echo "✅ Migrations completed successfully in ${duration}s"
else
    exit_code=$?
    echo "❌ Migration failed with exit code: $exit_code"
    echo "   Database may be unreachable or migration has errors."
    echo ""
    echo "Attempting to show alembic history for debugging..."
    alembic history --verbose 2>&1 | tail -20 || true
    exit 1
fi

echo "🚀 Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
