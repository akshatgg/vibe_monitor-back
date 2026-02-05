"""
Constants for code parser module.

Defines supported file extensions, directories/files to skip, and language mappings.
"""

import os

# Map language name to file extensions
SUPPORTED_EXTENSIONS = {
    "python": [".py"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "go": [".go"],
    "java": [".java"],
}

# Config/infrastructure files (stored as content only, no function/class parsing)
CONFIG_EXTENSIONS = {
    "yaml": [".yaml", ".yml"],
    "json": [".json"],
    "toml": [".toml"],
    "dockerfile": ["Dockerfile", ".dockerfile"],
    "markdown": [".md", ".mdx"],
    "env": [".env.example", ".env.sample"],
    "requirements": ["requirements.txt", "requirements-dev.txt"],
    "makefile": ["Makefile", "makefile"],
    "shell": [".sh", ".bash"],
}

# Build reverse mapping for config files
CONFIG_EXTENSION_TO_LANGUAGE = {}
for lang, extensions in CONFIG_EXTENSIONS.items():
    for ext in extensions:
        CONFIG_EXTENSION_TO_LANGUAGE[ext] = lang

# Reverse mapping: extension to language
EXTENSION_TO_LANGUAGE = {}
for lang, extensions in SUPPORTED_EXTENSIONS.items():
    for ext in extensions:
        EXTENSION_TO_LANGUAGE[ext] = lang

# All supported extensions as a set for quick lookup
ALL_SUPPORTED_EXTENSIONS = set(EXTENSION_TO_LANGUAGE.keys())

# Directories to skip during parsing
SKIP_DIRECTORIES = {
    # Package managers / dependencies
    "node_modules",
    "vendor",
    "bower_components",
    "jspm_packages",
    # Python
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    "site-packages",
    ".eggs",
    "*.egg-info",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".hypothesis",
    # Build outputs
    "dist",
    "build",
    "out",
    "target",
    "bin",
    "obj",
    ".next",
    ".nuxt",
    ".output",
    # IDE / Editor
    ".idea",
    ".vscode",
    ".vs",
    # Version control
    ".git",
    ".svn",
    ".hg",
    # Test coverage
    "coverage",
    "htmlcov",
    ".coverage",
    ".nyc_output",
    # Misc
    ".cache",
    ".tmp",
    "tmp",
    "temp",
    "logs",
    ".terraform",
    ".serverless",
}

# Files to skip during parsing
SKIP_FILES = {
    # Lock files
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.sum",
    "Cargo.lock",
    "Gemfile.lock",
    "poetry.lock",
    "composer.lock",
    # Config files that might be large
    ".DS_Store",
    "Thumbs.db",
}

# Maximum file size to parse (in bytes) - 1MB
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024

# File patterns that indicate generated/minified code
SKIP_PATTERNS = [
    ".min.",  # Minified files
    ".bundle.",  # Bundled files
    ".generated.",  # Generated files
    ".d.ts",  # TypeScript declaration files (usually auto-generated)
]


def should_skip_file(file_path: str, file_size: int = 0) -> bool:
    """
    Check if a file should be skipped during parsing.

    Args:
        file_path: Path to the file
        file_size: Size of the file in bytes

    Returns:
        True if the file should be skipped
    """
    # Check file name
    file_name = os.path.basename(file_path)
    if file_name in SKIP_FILES:
        return True

    # Check directory components
    path_parts = file_path.split("/")
    for part in path_parts[:-1]:  # Exclude the file name
        if part in SKIP_DIRECTORIES:
            return True

    # Check skip patterns
    for pattern in SKIP_PATTERNS:
        if pattern in file_path:
            return True

    # Check file size (if provided and non-zero)
    if file_size > 0 and file_size > MAX_FILE_SIZE_BYTES:
        return True

    return False


def get_language_for_file(file_path: str) -> str | None:
    """
    Get the language for a file based on its extension.

    Args:
        file_path: Path to the file

    Returns:
        Language name or None if not supported
    """
    file_name = os.path.basename(file_path)
    _, ext = os.path.splitext(file_path)

    # Check exact filename match first (for Dockerfile, Makefile, etc.)
    if file_name in CONFIG_EXTENSION_TO_LANGUAGE:
        return CONFIG_EXTENSION_TO_LANGUAGE[file_name]

    # Check extension-based languages
    ext_lower = ext.lower()
    if ext_lower in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext_lower]

    # Check config extensions
    if ext_lower in CONFIG_EXTENSION_TO_LANGUAGE:
        return CONFIG_EXTENSION_TO_LANGUAGE[ext_lower]

    return None


def is_supported_file(file_path: str) -> bool:
    """
    Check if a file has a supported extension.

    Args:
        file_path: Path to the file

    Returns:
        True if the file has a supported extension
    """
    return get_language_for_file(file_path) is not None


def is_code_file(file_path: str) -> bool:
    """
    Check if a file is a code file (not a config file).

    Code files have parsers that extract functions/classes.
    Config files are stored as content only.

    Args:
        file_path: Path to the file

    Returns:
        True if the file is a code file with a parser
    """
    _, ext = os.path.splitext(file_path)
    return ext.lower() in EXTENSION_TO_LANGUAGE


def get_file_extension(file_path: str) -> str:
    """
    Get the file extension for logging purposes.

    Args:
        file_path: Path to the file

    Returns:
        File extension including the dot, or filename if no extension
    """
    file_name = os.path.basename(file_path)
    _, ext = os.path.splitext(file_path)
    return ext.lower() if ext else file_name
