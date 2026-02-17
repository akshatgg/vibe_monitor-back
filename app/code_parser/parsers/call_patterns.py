"""
Centralized pattern matching for logging, metrics, and I/O calls across all languages.

Used by Tree-sitter parsers to classify call expressions into fact types.
"""

# Object/package names that indicate logging
LOGGING_OBJECTS = {
    "python": {"logger", "logging", "log", "LOGGER", "LOG"},
    "javascript": {"console", "logger", "winston", "bunyan", "pino", "log"},
    "typescript": {"console", "logger", "winston", "bunyan", "pino", "log"},
    "go": {"log", "logger", "slog", "logrus", "zap", "zerolog", "klog"},
    "java": {"log", "logger", "LOG", "LOGGER"},
}

# Method names that indicate logging (used with objects above)
LOGGING_METHODS = {
    "python": {"debug", "info", "warning", "warn", "error", "critical", "exception", "fatal", "log"},
    "javascript": {"log", "info", "warn", "error", "debug", "trace"},
    "typescript": {"log", "info", "warn", "error", "debug", "trace"},
    "go": {
        "Print", "Println", "Printf", "Fatal", "Fatalf", "Fatalln",
        "Panic", "Panicf", "Panicln", "Info", "Infof", "Infow", "Infoln",
        "Debug", "Debugf", "Debugw", "Debugln", "Warn", "Warnf", "Warnw", "Warnln",
        "Error", "Errorf", "Errorw", "Errorln", "With", "WithField", "WithFields",
    },
    "java": {"debug", "info", "warn", "error", "trace", "fatal", "log"},
}

# Standalone logging functions (no object prefix)
LOGGING_FUNCTIONS = {
    "python": {"print"},
    "javascript": set(),
    "typescript": set(),
    "go": set(),
    "java": set(),
}

# Java-specific: System.out / System.err method calls
JAVA_SYSTEM_LOGGING = {"println", "print", "printf"}

# Object/package names that indicate metrics instrumentation
METRICS_OBJECTS = {
    "python": {"Counter", "Histogram", "Gauge", "Summary", "statsd", "metrics", "dd_metrics", "dogstatsd"},
    "javascript": {"prometheus", "metrics", "statsd", "datadog", "newrelic", "client"},
    "typescript": {"prometheus", "metrics", "statsd", "datadog", "newrelic", "client"},
    "go": {"prometheus", "promauto", "metrics", "statsd"},
    "java": {"meterRegistry", "counter", "timer", "gauge", "Metrics", "micrometer"},
}

# Method names that indicate metrics operations
METRICS_METHODS = {
    "python": {"inc", "dec", "observe", "set", "labels", "increment", "decrement", "timing", "gauge", "histogram"},
    "javascript": {"inc", "dec", "observe", "set", "labels", "increment", "decrement", "timing", "gauge", "histogram", "counter"},
    "typescript": {"inc", "dec", "observe", "set", "labels", "increment", "decrement", "timing", "gauge", "histogram", "counter"},
    "go": {"Inc", "Dec", "Observe", "Set", "Add", "With", "WithLabelValues", "NewCounter", "NewHistogram", "NewGauge"},
    "java": {"increment", "record", "count", "timer", "gauge", "counter", "register"},
}

# Standalone metrics functions (constructor-style in Python)
METRICS_FUNCTIONS = {
    "python": {"Counter", "Histogram", "Gauge", "Summary", "Info", "Enum"},
    "javascript": set(),
    "typescript": set(),
    "go": {"NewCounter", "NewCounterVec", "NewHistogram", "NewHistogramVec", "NewGauge", "NewGaugeVec"},
    "java": set(),
}

# Object/package names that indicate external I/O (HTTP, DB, file, cloud)
EXTERNAL_IO_OBJECTS = {
    "python": {
        "requests", "httpx", "aiohttp", "urllib", "urllib3",
        "db", "cursor", "session", "connection", "engine",
        "boto3", "s3", "sqs", "dynamodb", "s3_client", "sqs_client",
        "redis", "client",
    },
    "javascript": {
        "axios", "http", "https", "fetch",
        "db", "pool", "connection", "knex", "prisma", "mongoose", "sequelize",
        "fs", "s3", "dynamodb", "redis",
    },
    "typescript": {
        "axios", "http", "https", "fetch",
        "db", "pool", "connection", "knex", "prisma", "mongoose", "sequelize",
        "fs", "s3", "dynamodb", "redis",
    },
    "go": {
        "http", "client",
        "db", "sql", "tx", "conn", "rows",
        "os", "ioutil",
        "grpc", "s3", "sqs", "dynamodb", "redis",
    },
    "java": {
        "restTemplate", "httpClient", "webClient",
        "jdbcTemplate", "entityManager", "connection", "statement", "preparedStatement",
        "s3Client", "sqsClient", "dynamoDbClient", "redisTemplate",
    },
}

# Method names on I/O objects that represent actual I/O operations
EXTERNAL_IO_METHODS = {
    "python": {
        "get", "post", "put", "delete", "patch", "head", "request", "send",
        "execute", "executemany", "fetchone", "fetchall", "fetchmany",
        "commit", "rollback", "connect",
        "upload_file", "download_file", "put_object", "get_object",
        "send_message", "receive_message",
    },
    "javascript": {
        "get", "post", "put", "delete", "patch", "request",
        "query", "execute", "find", "findOne", "findMany", "create", "update", "insertMany",
        "readFile", "writeFile", "readdir", "mkdir", "unlink",
    },
    "typescript": {
        "get", "post", "put", "delete", "patch", "request",
        "query", "execute", "find", "findOne", "findMany", "create", "update", "insertMany",
        "readFile", "writeFile", "readdir", "mkdir", "unlink",
    },
    "go": {
        "Get", "Post", "Do", "Head", "NewRequest",
        "Query", "QueryRow", "Exec", "QueryContext", "ExecContext",
        "Prepare", "Begin", "Commit", "Rollback",
        "Open", "ReadFile", "WriteFile", "Create",
    },
    "java": {
        "exchange", "getForObject", "postForObject", "getForEntity",
        "send", "retrieve", "body",
        "executeQuery", "executeUpdate", "execute",
        "find", "persist", "merge", "remove", "createQuery", "createNativeQuery",
        "getResultList", "getSingleResult",
    },
}

# Standalone I/O functions (no object prefix)
EXTERNAL_IO_FUNCTIONS = {
    "python": {"open", "urlopen"},
    "javascript": {"fetch"},
    "typescript": {"fetch"},
    "go": set(),
    "java": set(),
}

# Decorator/annotation names that indicate HTTP route handlers
HTTP_HANDLER_DECORATORS = {
    "python": {
        "app.get", "app.post", "app.put", "app.delete", "app.patch",
        "app.route", "app.api_route",
        "router.get", "router.post", "router.put", "router.delete", "router.patch",
        "router.route", "router.api_route",
        "route", "api_view",
    },
    "java": {
        "GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping",
        "RequestMapping", "Path", "GET", "POST", "PUT", "DELETE", "PATCH",
    },
}

# Express/Gin/Chi-style route registration call patterns (object.method style)
HTTP_HANDLER_CALL_OBJECTS = {
    "javascript": {"app", "router", "server"},
    "typescript": {"app", "router", "server"},
    "go": {"mux", "router", "r", "e", "g", "http"},
}

HTTP_HANDLER_CALL_METHODS = {
    "javascript": {"get", "post", "put", "delete", "patch", "use", "all", "route"},
    "typescript": {"get", "post", "put", "delete", "patch", "use", "all", "route"},
    "go": {
        "GET", "POST", "PUT", "DELETE", "PATCH",
        "Handle", "HandleFunc", "Get", "Post", "Put", "Delete",
        "Group", "Use",
    },
}


def is_logging_call(language: str, object_name: str | None, method_name: str) -> bool:
    """Check if a call expression represents a logging call."""
    if object_name:
        objects = LOGGING_OBJECTS.get(language, set())
        methods = LOGGING_METHODS.get(language, set())
        if object_name in objects and method_name in methods:
            return True
        # Java: System.out.println / System.err.println
        if language == "java" and object_name in ("out", "err") and method_name in JAVA_SYSTEM_LOGGING:
            return True
    else:
        functions = LOGGING_FUNCTIONS.get(language, set())
        if method_name in functions:
            return True
    return False


def is_metrics_call(language: str, object_name: str | None, method_name: str) -> bool:
    """Check if a call expression represents a metrics instrumentation call."""
    if object_name:
        objects = METRICS_OBJECTS.get(language, set())
        methods = METRICS_METHODS.get(language, set())
        return object_name in objects and method_name in methods
    else:
        functions = METRICS_FUNCTIONS.get(language, set())
        return method_name in functions


def is_external_io(language: str, object_name: str | None, method_name: str) -> bool:
    """Check if a call expression represents an external I/O operation."""
    if object_name:
        objects = EXTERNAL_IO_OBJECTS.get(language, set())
        methods = EXTERNAL_IO_METHODS.get(language, set())
        return object_name in objects and method_name in methods
    else:
        functions = EXTERNAL_IO_FUNCTIONS.get(language, set())
        return method_name in functions


def is_http_handler_decorator(language: str, decorator_name: str) -> bool:
    """Check if a decorator/annotation indicates an HTTP handler."""
    decorators = HTTP_HANDLER_DECORATORS.get(language, set())
    return decorator_name in decorators


def is_http_handler_registration(language: str, object_name: str, method_name: str) -> bool:
    """Check if a call expression is an HTTP route registration (Express/Gin/Chi style)."""
    objects = HTTP_HANDLER_CALL_OBJECTS.get(language, set())
    methods = HTTP_HANDLER_CALL_METHODS.get(language, set())
    return object_name in objects and method_name in methods
