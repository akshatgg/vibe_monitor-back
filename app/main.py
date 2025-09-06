from fastapi import FastAPI, Request
from datetime import datetime
import json
import os
from app.services.slack.client import app as slack_app


app = FastAPI()
app.mount("/slack", slack_app)
# File paths (they’ll be created if not present)
LOGS_FILE = "data/logs.jsonl"
TRACES_FILE = "data/traces.jsonl"
METRICS_FILE = "data/metrics.jsonl"

# Ensure files exist
for f in [LOGS_FILE, TRACES_FILE, METRICS_FILE]:
    if not os.path.exists(f):
        open(f, "w").close()


def append_to_file(filepath: str, entry: dict):
    """Helper to append a JSON line to a file."""
    with open(filepath, "a") as f:
        f.write(json.dumps(entry) + "\n")


@app.post("/v1/traces")
async def collect_traces(request: Request):
    body = await request.body()
    now = datetime.utcnow().isoformat()

    trace_entry = {"timestamp": now, "raw": body.hex()[:200]}
    append_to_file(TRACES_FILE, trace_entry)

    print(f"📩 Stored trace (size={len(body)} bytes)")
    return {"status": "ok"}


@app.post("/v1/metrics")
async def collect_metrics(request: Request):
    body = await request.body()
    now = datetime.utcnow().isoformat()

    metric_entry = {"timestamp": now, "raw": body.hex()[:200]}
    append_to_file(METRICS_FILE, metric_entry)

    print(f"📊 Stored metric (size={len(body)} bytes)")
    return {"status": "ok"}


@app.post("/v1/logs")
async def collect_logs(request: Request):
    body = await request.body()
    now = datetime.utcnow().isoformat()

    log_entry = {"timestamp": now, "raw": body.hex()[:200]}
    append_to_file(LOGS_FILE, log_entry)

    print(f"📝 Stored log (size={len(body)} bytes)")
    return {"status": "ok"}
