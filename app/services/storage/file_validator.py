from typing import Tuple

import magic
from fastapi import HTTPException, status


class FileValidationError(HTTPException):
    """Custom exception for file validation errors."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class FileValidator:
    """Service for validating uploaded files."""

    # File categories based on MIME types
    # NOTE: SVG intentionally excluded due to XSS risk (can contain embedded JavaScript)
    IMAGE_MIMES = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/gif",
        "image/webp",
        "image/bmp",
    }

    VIDEO_MIMES = {
        "video/mp4",
        "video/mpeg",
        "video/quicktime",
        "video/x-msvideo",
        "video/x-matroska",
        "video/webm",
        "video/x-ms-wmv",
        "video/x-flv",
    }

    DOCUMENT_MIMES = {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    CODE_MIMES = {
        "text/x-python",
        "text/x-python-script",
        "application/x-python",
        "text/javascript",
        "application/javascript",
        "text/x-typescript",
        "application/x-typescript",
        "text/x-c",
        "text/x-c++",
        "text/x-java",
        "text/html",
        "text/css",
        "application/json",
        "application/xml",
        "text/xml",
    }

    DATA_MIMES = {
        "application/json",
        "application/yaml",
        "text/yaml",
        "application/x-yaml",
        "text/x-yaml",
        "text/log",
    }

    # Allowed extensions mapping
    # NOTE: SVG intentionally excluded due to XSS risk (can contain embedded JavaScript)
    EXTENSION_TO_CATEGORY = {
        # Images
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
        ".webp": "image",
        ".bmp": "image",
        # Videos
        ".mp4": "video",
        ".mov": "video",
        ".avi": "video",
        ".mkv": "video",
        ".webm": "video",
        ".wmv": "video",
        ".flv": "video",
        ".mpeg": "video",
        ".mpg": "video",
        # Documents
        ".pdf": "document",
        ".txt": "document",
        ".md": "document",
        ".csv": "document",
        ".xls": "document",
        ".xlsx": "document",
        # Code
        ".py": "code",
        ".js": "code",
        ".ts": "code",
        ".tsx": "code",
        ".jsx": "code",
        ".java": "code",
        ".c": "code",
        ".cpp": "code",
        ".h": "code",
        ".html": "code",
        ".css": "code",
        ".php": "code",
        ".rb": "code",
        ".go": "code",
        ".rs": "code",
        ".swift": "code",
        ".kt": "code",
        ".scala": "code",
        # Data
        ".json": "data",
        ".yaml": "data",
        ".yml": "data",
        ".log": "data",
        ".xml": "data",
    }

    @staticmethod
    def validate_file(
        filename: str,
        file_content: bytes,
        max_size_bytes: int,
        allowed_extensions: list[str],
    ) -> Tuple[str, str]:
        # Check file size
        file_size = len(file_content)
        if file_size == 0:
            raise FileValidationError(f"File '{filename}' is empty.")
        if file_size > max_size_bytes:
            max_mb = max_size_bytes / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            raise FileValidationError(
                f"File '{filename}' is too large ({actual_mb:.2f}MB). "
                f"Maximum allowed size is {max_mb:.0f}MB."
            )

        # Check file extension
        file_ext = None
        if "." in filename:
            file_ext = "." + filename.rsplit(".", 1)[-1].lower()

        if not file_ext or file_ext not in allowed_extensions:
            raise FileValidationError(
                f"File type '{file_ext or 'unknown'}' is not allowed. "
                f"Allowed types: {', '.join(allowed_extensions)}"
            )

        # Detect MIME type
        try:
            mime = magic.from_buffer(file_content, mime=True)
        except Exception as e:
            raise FileValidationError(
                f"Failed to detect MIME type for '{filename}': {str(e)}"
            )

        # Verify MIME type
        file_category = FileValidator.EXTENSION_TO_CATEGORY.get(file_ext)

        if not file_category:
            raise FileValidationError(
                f"Unknown file category for extension '{file_ext}'"
            )

        # Validate MIME type matches file category for security
        # This prevents attackers from uploading malicious executables with fake extensions
        category_mimes = {
            "image": FileValidator.IMAGE_MIMES,
            "video": FileValidator.VIDEO_MIMES,
            "document": FileValidator.DOCUMENT_MIMES,
            "code": FileValidator.CODE_MIMES,
            "data": FileValidator.DATA_MIMES,
        }

        allowed_mimes = category_mimes.get(file_category)
        if allowed_mimes and mime not in allowed_mimes:
            # Allow text/plain for code and data files (common fallback MIME type)
            if file_category in ("code", "data") and mime == "text/plain":
                pass  # Allow text/plain as valid MIME for code/data files
            else:
                raise FileValidationError(
                    f"File '{filename}' has extension '{file_ext}' but MIME type is '{mime}'. "
                    f"Expected a {file_category} MIME type."
                )

        return mime, file_category

    @staticmethod
    def get_category_from_mime(mime_type: str) -> str:
        if mime_type in FileValidator.IMAGE_MIMES:
            return "image"
        elif mime_type in FileValidator.VIDEO_MIMES:
            return "video"
        elif mime_type in FileValidator.DOCUMENT_MIMES:
            return "document"
        elif mime_type in FileValidator.CODE_MIMES:
            return "code"
        elif mime_type in FileValidator.DATA_MIMES:
            return "data"
        else:
            return "data"  # Default
