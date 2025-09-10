# convert.py - /home/irohanrajput/Desktop/work/vm-api/convert.py
import json
import os
from datetime import datetime
from collections import defaultdict
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

def parse_timestamp(timestamp_str):
    """Parse ISO timestamp for grouping (round to nearest second)"""
    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    return dt.replace(microsecond=0).isoformat()

def main():
    # Input files
    TRACES_FILE = "data/traces.jsonl"
    METRICS_FILE = "data/metrics.jsonl" 
    LOGS_FILE = "data/logs.jsonl"
    
    # Group data by timestamp (rounded to seconds)
    grouped_data = defaultdict(lambda: {"logs": [], "traces": [], "metrics": []})
    
    # Process logs
    if os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, "r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    hex_data = obj["raw"]
                    log_bytes = bytes.fromhex(hex_data)
                    log_data = json.loads(log_bytes.decode('utf-8'))
                    
                    timestamp_key = parse_timestamp(obj["timestamp"])
                    grouped_data[timestamp_key]["logs"].append(log_data)
                except Exception as e:
                    print(f"Failed to parse log: {e}")
    
    # Process traces
    if os.path.exists(TRACES_FILE):
        with open(TRACES_FILE, "r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    hex_data = obj["raw"]
                    proto_bytes = bytes.fromhex(hex_data)
                    
                    request = ExportTraceServiceRequest()
                    request.ParseFromString(proto_bytes)
                    
                    readable_dict = MessageToDict(request)
                    timestamp_key = parse_timestamp(obj["timestamp"])
                    grouped_data[timestamp_key]["traces"].append(readable_dict)
                except Exception as e:
                    print(f"Failed to parse trace: {e}")
    
    # Process metrics  
    if os.path.exists(METRICS_FILE):
        with open(METRICS_FILE, "r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    hex_data = obj["raw"]
                    proto_bytes = bytes.fromhex(hex_data)
                    
                    request = ExportMetricsServiceRequest()
                    request.ParseFromString(proto_bytes)
                    
                    readable_dict = MessageToDict(request)
                    timestamp_key = parse_timestamp(obj["timestamp"])
                    grouped_data[timestamp_key]["metrics"].append(readable_dict)
                except Exception as e:
                    print(f"Failed to parse metric: {e}")
    
    # Write grouped entries
    with open("data/readable.jsonl", "w") as f:
        for timestamp in sorted(grouped_data.keys()):
            entry = {
                "timestamp": timestamp,
                "logs": grouped_data[timestamp]["logs"],
                "traces": grouped_data[timestamp]["traces"],
                "metrics": grouped_data[timestamp]["metrics"]
            }
            f.write(json.dumps(entry) + "\n")
    
    print(f"Created data/readable.jsonl with {len(grouped_data)} timestamp groups")

if __name__ == "__main__":
    main()