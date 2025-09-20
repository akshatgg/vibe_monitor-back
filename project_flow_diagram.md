# VM API Project Flow Diagram

## Overview
The VM API is a log ingestion and observability system that receives OpenTelemetry logs via gRPC, processes them in batches, and stores them in ClickHouse for querying.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                VM API SYSTEM                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────┐
│   Client Apps   │    │  OTEL Collector  │    │ Batch Processor │    │  ClickHouse  │
│   (External)    │    │   (gRPC Server)  │    │                 │    │  Database    │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └──────────────┘
         │                        │                       │                      │
         │  OTLP/gRPC             │   LogEntry Objects    │   Batched Writes    │
         │  Port 4317             │                       │                     │
         └────────────────────────┼───────────────────────┼─────────────────────┘
                                 │                       │
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Backend                                      │
│                                                                                 │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐                │
│  │   Main App      │  │  Ingestion API   │  │   Health Check  │                │
│  │   (main.py)     │  │   (router.py)    │  │                 │                │
│  │                 │  │                  │  │                 │                │
│  │ • Startup       │  │ • Query logs     │  │ • System stats  │                │
│  │ • Lifespan      │  │ • Search logs    │  │ • Health status │                │
│  │ • Shutdown      │  │ • Time range     │  │                 │                │
│  └─────────────────┘  └──────────────────┘  └─────────────────┘                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Detailed Component Flow

### 1. Application Startup (main.py)
```
FastAPI App Startup
├── lifespan context manager starts
├── Line 19: batch_processor.start()
│   └── Starts background batch processing task
├── Line 22: otel_collector_server.start()
│   ├── Creates gRPC server instance
│   ├── Registers OTelLogCollectorService
│   ├── Binds to port 4317 (OTEL_GRPC_PORT)
│   └── Starts listening for OTLP requests
└── Line 52: Include ingestion router (/api/v1/ingestion/*)
```

### 2. OTEL Collector Service (otel_collector.py)

#### Connection Point
**Line 22 in main.py: `await otel_collector_server.start()`**

#### gRPC Server Setup (Lines 173-185)
```python
OTelCollectorServer.start():
├── Line 175: Create aio_grpc.server()
├── Line 177-179: Register OTelLogCollectorService
├── Line 181: Bind to [::]:{OTEL_GRPC_PORT} (default 4317)
├── Line 182: Add insecure port
└── Line 184: Start server
```

#### Log Processing Flow (Lines 25-63)
```
OTLP gRPC Request (Export method)
├── Line 30-50: Parse resource_logs
│   ├── Extract workspace_id, client_id, service_name
│   ├── Process scope_logs and log_records
│   └── Convert to LogEntry objects
├── Line 52-53: Send to batch_processor.add_log()
└── Line 55-59: Return ExportLogsServiceResponse
```

### 3. Batch Processor (batch_processor.py)

#### Initialization & Startup
```
LogBatchProcessor
├── Line 17: batches: Dict[workspace:client, List[LogEntry]]
├── Line 18: batch_timestamps: Dict[str, float]
├── Line 23-29: start() method
│   ├── Set running = True
│   ├── Create background processing task
│   └── Start _background_processor()
└── Configuration from settings:
    ├── LOG_BATCH_SIZE (default: 1000)
    └── LOG_BATCH_TIMEOUT (default: 2 seconds)
```

#### Log Processing (Lines 43-54)
```
add_log(log_entry):
├── Line 45: Create batch_key = "{workspace_id}:{client_id}"
├── Line 47-48: Track batch timestamp if new
├── Line 50: Add log to batch
└── Line 52-53: Flush batch if size >= LOG_BATCH_SIZE
```

#### Background Processing (Lines 55-76)
```
_background_processor() (runs every 5 seconds):
├── Line 64-67: Check batch ages
├── Line 65: If age >= LOG_BATCH_TIMEOUT
└── Line 70: Flush expired batches
```

#### Batch Flushing (Lines 77-97)
```
_flush_batch():
├── Line 81-83: Copy logs, clear batch, remove timestamp
├── Line 86: clickhouse_service.store_logs_batch()
├── Success: Line 88 - Log success message
└── Failure: Line 91-96 - Re-queue logs with new timestamp
```

### 4. ClickHouse Integration

#### Service Layer (clickhouse/service.py)
```
ClickHouse Service
├── Connection management
├── Batch storage operations
├── Log querying capabilities
└── Health check functionality
```

#### Models (clickhouse/models.py)
```python
LogEntry:
├── workspace_id: str
├── client_id: str
├── timestamp_ms: int
├── severity_text: str
├── severity_number: int
├── body: str
├── resource_attributes: Dict
├── log_attributes: Dict
├── trace_id: str
├── span_id: str
├── endpoint: str
├── service_name: str
└── service_version: str
```

### 5. FastAPI REST API (router.py)

#### Available Endpoints
```
/api/v1/ingestion/
├── POST /query - Advanced log querying
├── GET /query/time-range - Time-based queries
├── GET /search - Text search in logs
├── GET /logs/sorted - Sorted log retrieval
├── GET /stats - Ingestion statistics
└── GET /health - System health check
```

#### Query Capabilities
```
Log Query Features:
├── Time range filtering (start_time_ms, end_time_ms)
├── Severity level filtering
├── Text search in log body
├── Client ID filtering
├── Endpoint filtering
├── Pagination (limit, offset)
├── Sorting (asc/desc by timestamp)
└── Workspace isolation
```

### 6. Configuration (config.py)

#### Environment Variables
```python
Settings:
├── CLICKHOUSE_HOST/PORT/USER/PASSWORD/DATABASE/SECURE
├── OTEL_GRPC_PORT: 4317 (gRPC collector port)
├── OTEL_HTTP_PORT: 4318 (HTTP collector port - unused)
├── LOG_BATCH_SIZE: 1000 (max logs per batch)
├── LOG_BATCH_TIMEOUT: 2 (seconds before force flush)
└── API_V1_PREFIX: "/api/v1"
```

## Data Flow Sequence

```
1. External Client App
   ├── Sends OTLP logs via gRPC to port 4317
   └── Uses OpenTelemetry SDK

2. OTEL Collector (otel_collector.py:25)
   ├── Receives gRPC Export request
   ├── Parses OTLP protobuf data
   ├── Extracts resource & log attributes
   ├── Creates LogEntry objects
   └── Sends to batch processor

3. Batch Processor (batch_processor.py:43)
   ├── Groups logs by workspace_id:client_id
   ├── Accumulates until batch_size OR timeout
   ├── Background task checks every 5 seconds
   └── Flushes batches to ClickHouse

4. ClickHouse Storage
   ├── Receives batched log entries
   ├── Stores in structured format
   └── Provides querying capabilities

5. FastAPI REST API (router.py)
   ├── Provides HTTP endpoints for log queries
   ├── Supports filtering, searching, pagination
   ├── Returns structured responses
   └── Includes health/stats monitoring
```

## Key Integration Points

### OTEL Collector → FastAPI Connection
- **File**: `app/main.py`
- **Line**: 22 - `await otel_collector_server.start()`
- **Port**: 4317 (configurable via OTEL_GRPC_PORT)
- **Protocol**: gRPC with OTLP (OpenTelemetry Protocol)

### Batch Processor Integration
- **File**: `app/main.py`
- **Line**: 19 - `await batch_processor.start()`
- **Connection**: Line 53 in otel_collector.py - `await batch_processor.add_log(log_entry)`

### ClickHouse Integration
- **File**: `app/ingestion/batch_processor.py`
- **Line**: 86 - `await clickhouse_service.store_logs_batch(logs_to_process)`
## Application Lifecycle

### Startup Sequence
1. FastAPI app initialization
2. Batch processor starts background task
3. OTEL collector gRPC server starts on port 4317
4. Ingestion router mounts at /api/v1/ingestion
5. Health endpoint available at /health

### Shutdown Sequence
1. OTEL collector server stops (30s grace period)
2. Batch processor stops and flushes remaining batches
3. Background tasks cancelled
4. Database connections closed

## Monitoring & Health

### Health Checks Available
- `/health` - Main application health
- `/api/v1/ingestion/health` - Detailed ingestion health
- `/api/v1/ingestion/stats` - Processing statistics

### Metrics Tracked
- Batch processor status (running/stopped)
- Pending log counts per batch
- ClickHouse connection health
- OTEL collector status
- Processing statistics and timing

## External Dependencies

### Required Services
- **ClickHouse**: Database for log storage
- **Client Applications**: Send OTLP data via gRPC

### Optional Configurations
- Environment variables for all settings
- Docker deployment ready
- Cloud-ready configuration options