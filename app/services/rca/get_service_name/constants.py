"""
Constants for service name extraction
"""

# Priority files to check based on language
LANGUAGE_FILES = {
    "Python": ["main.py", "app.py", "server.py", "__init__.py"],
    "JavaScript": ["index.js", "server.js", "app.js"],
    "TypeScript": ["index.ts", "server.ts", "app.ts"],
    "Go": ["main.go", "server.go"],
}

UNIVERSAL_FILES = ["Dockerfile", ".env", "package.json", "pyproject.toml"]

# Regex patterns for service name detection (ordered by priority)
SERVICE_PATTERNS = {
    # TOP PRIORITY: Dockerfile LABEL service.name="xxx"
    "dockerfile_label_service_name": r'LABEL\s+service\.name\s*=\s*["\']([a-zA-Z0-9_\-]+)["\']',
    # Other Dockerfile patterns
    "dockerfile_label_service": r'LABEL\s+service\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?',
    "dockerfile_env": r'ENV\s+(?:SERVICE_NAME|APP_NAME)\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?',
    # Application patterns
    "python_logger": r'logger\s*=\s*logging\.getLogger\(["\']([a-zA-Z0-9_\-\.]+)["\']\)',
    "fastapi_app": r'FastAPI\([^)]*title\s*=\s*["\']([^"\']+)["\']',
    "env_var": r'(?:SERVICE_NAME|APP_NAME)\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?',
    "package_name": r'"name"\s*:\s*"([a-zA-Z0-9_\-@/]+)"',
}
