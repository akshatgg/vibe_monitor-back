# main.py - /home/irohanrajput/Desktop/work/vm-api/app/main.py
from fastapi import FastAPI, Request, BackgroundTasks
from datetime import datetime
import json
import os
import re
from app.services.rca import process_error


app = FastAPI()


# File paths (they'll be created if not present)
LOGS_FILE = "data/logs.jsonl"
TRACES_FILE = "data/traces.jsonl"
METRICS_FILE = "data/metrics.jsonl"

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# Ensure files exist
for f in [LOGS_FILE, TRACES_FILE, METRICS_FILE]:
    if not os.path.exists(f):
        open(f, "w").close()


def append_to_file(filepath: str, entry: dict):
    """Helper to append a JSON line to a file."""
    with open(filepath, "a") as f:
        f.write(json.dumps(entry) + "\n")


def extract_status_code(log_message):
    """Extract HTTP status code from Morgan log message"""
    pattern = r'\w+ /\S* (\d{3}) \d+ - [\d.]+ ms'
    match = re.search(pattern, log_message)
    return int(match.group(1)) if match else None

@app.get("/health")
async def health_check():
    return ("FastAPI backend is running!")


@app.post("/v1/traces")
async def collect_traces(request: Request):
    body = await request.body()
    now = datetime.utcnow().isoformat()

    trace_entry = {"timestamp": now, "raw": body.hex()}
    append_to_file(TRACES_FILE, trace_entry)

    print(f"Stored trace (size={len(body)} bytes)")
    return {"status": "ok"}


@app.post("/v1/metrics")
async def collect_metrics(request: Request):
    body = await request.body()
    now = datetime.utcnow().isoformat()

    metric_entry = {"timestamp": now, "raw": body.hex()}
    append_to_file(METRICS_FILE, metric_entry)

    print(f"Stored metric (size={len(body)} bytes)")
    return {"status": "ok"}


@app.post("/v1/logs")
async def collect_logs(request: Request):
    body = await request.body()
    now = datetime.utcnow().isoformat()

    # Store the log entry
    log_entry = {"timestamp": now, "raw": body.hex()}
    append_to_file(LOGS_FILE, log_entry)

    # Decode and check for errors
    try:
        log_bytes = bytes.fromhex(log_entry["raw"])
        log_data = json.loads(log_bytes.decode('utf-8'))
        
        if "message" in log_data:
            status_code = extract_status_code(log_data["message"])
            
            if status_code and status_code >= 400 and status_code !=404:
                print("🚨 Error detected! Initiating RCA Service:main.py")
                # print(f"ERROR DETECTED: Status {status_code}")
                
                # Call RCA service to handle error processing
                process_error(log_data)
            else:
                print(f"Stored log (size={len(body)} bytes)")
        else:
            print(f"Stored log (size={len(body)} bytes)")
        
    except Exception as e:
        print(f"Failed to parse log for error detection: {e}")
        print(f"Stored log (size={len(body)} bytes)")

    return {"status": "ok"}