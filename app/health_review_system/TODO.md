# Health Review System - Implementation TODOs

## Overview
This file tracks remaining implementation work for the Health Review System.

---

## Completed ✅

### 1. HealthReviewWorker
- [x] Created `app/workers/health_review_worker.py`
- [x] SQS client for health review queue
- [x] Worker class with message processing
- [x] `publish_health_review_job()` helper function
- [x] Added `HEALTH_REVIEW_QUEUE_URL` to config

### 2. CodebaseSync GitHub Integration
- [x] Integrated `get_branch_recent_commits` for HEAD SHA
- [x] Created `tools.py` with helper functions for LLMAnalyzer:
  - `read_file()`, `search_in_code()`, `get_file_tree()`
  - `list_functions_from_parsed()`, `find_function_by_name()`

### 3. DataCollector with Observability Tools
- [x] Integrated with `IntegrationCapabilityResolver`
- [x] Grafana/Loki log collection via `logs_service`
- [x] Grafana/Prometheus metrics collection via `metrics_service`
- [x] Error aggregation with fingerprinting from logs

---

## Completed ✅

### 4. LLMAnalyzer with LangGraph
- [x] Create provider pattern (Groq, Gemini) - `providers.py`
- [x] Design prompts for gap detection - `prompts.py`
- [x] Implement LangGraph multi-node pipeline - `agent.py`
  - analyze_errors → find_logging_gaps → find_metrics_gaps → generate_summary
- [x] Add prompt templates for error analysis, logging gaps, metrics gaps
- [x] Update service to use real LLM via `USE_MOCK_LLM_ANALYZER` config flag
- [x] Added config settings: `USE_MOCK_LLM_ANALYZER`, `HEALTH_REVIEW_LLM_TEMPERATURE`, `HEALTH_REVIEW_LLM_MAX_TOKENS`

### 5. Orchestrator Parallel Execution
- [x] Run CodebaseSync + DataCollector in parallel (Phase 1)
- [x] Run HealthScorer + SLIIndicator in parallel (Phase 3)
- [x] Added detailed logging for each phase
- [x] Using `asyncio.gather()` for parallel execution

---

## Pending 📋

### 6. DataCollector - Additional Integrations
**Context**: The architecture supports multiple integrations, but only Grafana is fully implemented.

#### Datadog Integration
- [ ] `_collect_datadog_logs()` - Use Datadog Logs API
  - File: `app/health_review_system/data_collector/service.py`
  - Reference: `app/services/rca/tools/datadog/tools.py`
  - Query: `search_datadog_logs_tool()` returns formatted string, need raw data

#### NewRelic Integration
- [ ] `_collect_newrelic_logs()` - Use NewRelic Logs API
  - File: `app/health_review_system/data_collector/service.py`
  - Reference: `app/services/rca/tools/newrelic/tools.py`
  - Query: `search_newrelic_logs_tool()` returns formatted string, need raw data

#### CloudWatch Integration
- [ ] `_collect_cloudwatch_logs()` - Use CloudWatch Logs API
  - File: `app/health_review_system/data_collector/service.py`
  - Reference: `app/services/rca/tools/cloudwatch/tools.py`
  - Query: `filter_cloudwatch_log_events_tool()` returns formatted string

#### Metrics for Each Integration
- [ ] `_collect_datadog_metrics()` - Datadog metrics
- [ ] `_collect_newrelic_metrics()` - NewRelic metrics
- [ ] `_collect_cloudwatch_metrics()` - CloudWatch metrics

### 7. Code Parser Integration
- [ ] Merge tree-sitter implementation from `tushar-code-parser` branch
- [ ] Update `CodebaseSyncService` to use real parser
- [ ] Parse functions, classes, imports with location info

### 8. API Endpoints
- [ ] `POST /api/v1/services/{service_id}/reviews` - Trigger review
- [ ] `GET /api/v1/services/{service_id}/reviews` - List reviews
- [ ] `GET /api/v1/reviews/{review_id}` - Get review details

### 9. Scheduler
- [ ] Create cron job to check `ReviewSchedule` table
- [ ] Trigger reviews for services with `next_scheduled_at <= now()`
- [ ] Update `next_scheduled_at` after triggering

---

## Architecture Notes

### Data Flow
```
Trigger → SQS → Worker → Orchestrator
                              │
              ┌───────────────┴───────────────┐
              │                               │
        CodebaseSync                    DataCollector
        (GitHub tools)                  (Grafana/DD/NR/CW)
              │                               │
              └───────────────┬───────────────┘
                              │
                        LLMAnalyzer
                        (LangGraph)
                              │
              ┌───────────────┴───────────────┐
              │                               │
        HealthScorer                    SLIIndicator
              │                               │
              └───────────────┬───────────────┘
                              │
                        [DB Save]
```

### LLMAnalyzer Provider Pattern
```python
# Planned structure
class BaseLLMProvider(ABC):
    @abstractmethod
    async def analyze(self, prompt: str, tools: list) -> str: ...

class AnthropicProvider(BaseLLMProvider): ...
class OpenAIProvider(BaseLLMProvider): ...
class GeminiProvider(BaseLLMProvider): ...
```

### LLMAnalyzer Prompts (To Design)
1. **Error Analysis Prompt**: Correlate errors with code locations
2. **Logging Gap Prompt**: Compare code structure with log statements
3. **Metrics Gap Prompt**: Identify missing instrumentation points
4. **Summary Prompt**: Generate health summary and recommendations

---

## Configuration Flags Needed
- `LLM_PROVIDER`: "anthropic" | "openai" | "gemini"
- `LLM_MODEL`: Model name for the provider
- `LLM_API_KEY`: API key (or use existing config)
- `USE_MOCK_LLM`: Boolean to use mock for testing

---

Last updated: During implementation session
