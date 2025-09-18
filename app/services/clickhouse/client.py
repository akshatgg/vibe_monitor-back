import clickhouse_connect
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class ClickHouseClient:
    def __init__(self):
        self.connection_params = None
        self.connected = False
        self._setup_connection_params()

    def _setup_connection_params(self):
        """Setup connection parameters for reuse."""
        self.connection_params = {
            "host": settings.CLICKHOUSE_HOST,
            "port": settings.CLICKHOUSE_PORT,
            "username": settings.CLICKHOUSE_USER,
            "password": settings.CLICKHOUSE_PASSWORD,
            "database": settings.CLICKHOUSE_DATABASE,
        }

        # Add secure connection for ClickHouse Cloud
        if settings.CLICKHOUSE_SECURE:
            self.connection_params["secure"] = True

    def get_client(self):
        """Get a new ClickHouse client connection for each operation."""
        try:
            client = clickhouse_connect.get_client(**self.connection_params)
            if not self.connected:
                self.connected = True
                logger.info(f"Connected to ClickHouse successfully (secure={settings.CLICKHOUSE_SECURE})")
            return client
        except Exception as e:
            logger.warning(f"Failed to connect to ClickHouse: {e}")
            self.connected = False
            raise Exception("ClickHouse is not available")

    def connect(self):
        """Test connection - for backward compatibility."""
        try:
            client = self.get_client()
            client.query("SELECT 1")
            self.connected = True
        except Exception as e:
            logger.warning(f"Failed to connect to ClickHouse: {e}")
            self.connected = False

    def ensure_connected(self):
        if not self.connected:
            self.connect()
        if not self.connected:
            raise Exception("ClickHouse is not available")

    def create_logs_table(self):
        self.ensure_connected()
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS logs (
            id UInt64,
            workspace_id String,
            client_id String,
            timestamp_ms UInt64,
            timestamp DateTime64(3) MATERIALIZED fromUnixTimestamp64Milli(timestamp_ms),
            severity_text String,
            severity_number UInt8,
            body String,
            resource_attributes Map(String, String),
            log_attributes Map(String, String),
            trace_id String,
            span_id String,
            endpoint String,
            service_name String,
            service_version String,
            ingested_at DateTime64(3) DEFAULT now64()
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(timestamp)
        ORDER BY (workspace_id, client_id, timestamp_ms, id)
        TTL toDateTime(timestamp) + INTERVAL 90 DAY
        """
        try:
            client = self.get_client()
            client.command(create_table_sql)
            logger.info("Logs table created successfully")
        except Exception as e:
            logger.error(f"Failed to create logs table: {e}")
            raise

    def insert_logs_batch(self, logs: List[Dict[str, Any]]) -> bool:
        if not logs:
            return True

        self.ensure_connected()
        try:
            client = self.get_client()

            # Build INSERT statement manually to avoid clickhouse-connect issues with Map columns
            values_list = []
            for log in logs:
                # Escape strings for SQL
                def escape_sql_string(s):
                    return s.replace("'", "\\'").replace("\\", "\\\\") if s else ""

                # Convert maps to ClickHouse format
                resource_attrs = "{" + ",".join([f"'{k}':'{escape_sql_string(str(v))}'" for k, v in log.get("resource_attributes", {}).items()]) + "}"
                log_attrs = "{" + ",".join([f"'{k}':'{escape_sql_string(str(v))}'" for k, v in log.get("log_attributes", {}).items()]) + "}"

                values = f"""({log['id']}, '{escape_sql_string(log['workspace_id'])}', '{escape_sql_string(log['client_id'])}',
                          {log['timestamp_ms']}, '{escape_sql_string(log['severity_text'])}', {log['severity_number']},
                          '{escape_sql_string(log['body'])}', {resource_attrs}, {log_attrs},
                          '{escape_sql_string(log.get('trace_id', ''))}', '{escape_sql_string(log.get('span_id', ''))}',
                          '{escape_sql_string(log.get('endpoint', ''))}', '{escape_sql_string(log.get('service_name', ''))}',
                          '{escape_sql_string(log.get('service_version', ''))}')"""
                values_list.append(values)

            insert_query = """
            INSERT INTO logs (id, workspace_id, client_id, timestamp_ms, severity_text,
                             severity_number, body, resource_attributes, log_attributes,
                             trace_id, span_id, endpoint, service_name, service_version)
            VALUES """ + ",".join(values_list)

            client.command(insert_query)
            logger.info(f"Inserted {len(logs)} logs successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to insert logs batch. Error: {e}")
            logger.error(f"Log data sample: {logs[0] if logs else 'No logs'}")
            return False

    def query_logs(
        self,
        workspace_id: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        severity_filter: Optional[List[str]] = None,
        search_query: Optional[str] = None,
        client_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        sort_order: str = "desc"
    ) -> List[Dict[str, Any]]:
        where_clauses = [f"workspace_id = '{workspace_id}'"]

        if start_time_ms:
            where_clauses.append(f"timestamp_ms >= {start_time_ms}")
        if end_time_ms:
            where_clauses.append(f"timestamp_ms <= {end_time_ms}")
        if severity_filter:
            severity_list = "','".join(severity_filter)
            where_clauses.append(f"severity_text IN ('{severity_list}')")
        if search_query:
            escaped_query = search_query.replace("'", "\\'")
            where_clauses.append(f"body LIKE '%{escaped_query}%'")
        if client_id:
            where_clauses.append(f"client_id = '{client_id}'")
        if endpoint:
            where_clauses.append(f"endpoint = '{endpoint}'")

        where_clause = " AND ".join(where_clauses)
        order_clause = f"ORDER BY timestamp_ms {sort_order.upper()}"

        query = f"""
        SELECT
            id,
            workspace_id,
            client_id,
            timestamp_ms,
            timestamp,
            severity_text,
            severity_number,
            body,
            resource_attributes,
            log_attributes,
            trace_id,
            span_id,
            endpoint,
            service_name,
            service_version,
            ingested_at
        FROM logs
        WHERE {where_clause}
        {order_clause}
        LIMIT {limit} OFFSET {offset}
        """

        self.ensure_connected()
        try:
            client = self.get_client()
            result = client.query(query)
            return [dict(zip(result.column_names, row)) for row in result.result_rows]
        except Exception as e:
            logger.error(f"Failed to query logs: {e}")
            raise

    def count_logs(
        self,
        workspace_id: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        severity_filter: Optional[List[str]] = None,
        search_query: Optional[str] = None,
        client_id: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> int:
        where_clauses = [f"workspace_id = '{workspace_id}'"]

        if start_time_ms:
            where_clauses.append(f"timestamp_ms >= {start_time_ms}")
        if end_time_ms:
            where_clauses.append(f"timestamp_ms <= {end_time_ms}")
        if severity_filter:
            severity_list = "','".join(severity_filter)
            where_clauses.append(f"severity_text IN ('{severity_list}')")
        if search_query:
            escaped_query = search_query.replace("'", "\\'")
            where_clauses.append(f"body LIKE '%{escaped_query}%'")
        if client_id:
            where_clauses.append(f"client_id = '{client_id}'")
        if endpoint:
            where_clauses.append(f"endpoint = '{endpoint}'")

        where_clause = " AND ".join(where_clauses)
        query = f"SELECT COUNT(*) as count FROM logs WHERE {where_clause}"

        self.ensure_connected()
        try:
            client = self.get_client()
            result = client.query(query)
            return result.first_row[0] if result.first_row else 0
        except Exception as e:
            logger.error(f"Failed to count logs: {e}")
            return 0

    def health_check(self) -> bool:
        try:
            self.ensure_connected()
            client = self.get_client()
            result = client.query("SELECT 1")
            return result.first_row[0] == 1
        except Exception as e:
            logger.error(f"ClickHouse health check failed: {e}")
            return False