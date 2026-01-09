import asyncio
import json
import logging
from io import BytesIO
from typing import Optional

import yaml
from PyPDF2 import PdfReader

from app.core.config import settings

logger = logging.getLogger(__name__)


class TextExtractor:
    @staticmethod
    async def extract_text(
        file_content: bytes,
        mime_type: str,
        filename: str,
        max_chars: int | None = None,
    ) -> Optional[str]:
        """Extract text from various file types.

        Args:
            file_content: Raw file bytes
            mime_type: MIME type of the file
            filename: Name of the file
            max_chars: Maximum characters to extract (defaults to config value)

        Returns:
            Extracted text or None if extraction failed
        """
        if max_chars is None:
            max_chars = settings.TEXT_EXTRACTION_MAX_CHARS
        try:
            # PDF files
            if mime_type == "application/pdf":
                return await TextExtractor._extract_from_pdf(
                    file_content, filename, max_chars
                )

            # JSON files
            elif mime_type == "application/json" or filename.endswith(".json"):
                return await TextExtractor._extract_from_json(
                    file_content, filename, max_chars
                )

            # YAML files
            elif mime_type in [
                "application/yaml",
                "application/x-yaml",
                "text/yaml",
                "text/x-yaml",
            ] or filename.endswith((".yaml", ".yml")):
                return await TextExtractor._extract_from_yaml(
                    file_content, filename, max_chars
                )

            # Text-based files (code, plain text, markdown, CSV, logs, etc.)
            elif mime_type.startswith("text/") or mime_type in [
                "application/javascript",
                "application/x-python",
                "application/x-typescript",
            ]:
                return await TextExtractor._extract_from_text(
                    file_content, filename, max_chars
                )

            else:
                logger.warning(
                    f"No text extraction handler for MIME type '{mime_type}' (file: {filename})"
                )
                return None

        except Exception as e:
            logger.error(f"Failed to extract text from '{filename}': {str(e)}")
            return None

    @staticmethod
    def _sync_extract_from_pdf(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Synchronous PDF text extraction (runs in thread pool)."""
        try:
            pdf_file = BytesIO(file_content)
            pdf_reader = PdfReader(pdf_file)

            text_parts = []
            total_chars = 0

            for page_num, page in enumerate(pdf_reader.pages, start=1):
                page_text = page.extract_text()

                if page_text:
                    remaining_chars = max_chars - total_chars
                    if remaining_chars <= 0:
                        break

                    # Truncate page text if needed
                    if len(page_text) > remaining_chars:
                        page_text = (
                            page_text[:remaining_chars] + "\n[... truncated ...]"
                        )

                    text_parts.append(f"--- Page {page_num} ---\n{page_text}")
                    total_chars += len(page_text)

            if not text_parts:
                logger.warning(f"No text extracted from PDF '{filename}'")
                return None

            extracted = "\n\n".join(text_parts)
            logger.info(
                f"Extracted {total_chars} chars from PDF '{filename}' ({len(pdf_reader.pages)} pages)"
            )

            return extracted

        except Exception as e:
            logger.error(f"PDF extraction failed for '{filename}': {str(e)}")
            return None

    @staticmethod
    async def _extract_from_pdf(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Extract text from PDF files using PyPDF2 (non-blocking)."""
        # Run blocking PDF parsing in thread pool to avoid blocking event loop
        return await asyncio.to_thread(
            TextExtractor._sync_extract_from_pdf, file_content, filename, max_chars
        )

    @staticmethod
    def _sync_extract_from_json(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Synchronous JSON extraction (runs in thread pool)."""
        try:
            text = file_content.decode("utf-8")
            data = json.loads(text)

            # Pretty-print JSON with indentation
            formatted = json.dumps(data, indent=2, ensure_ascii=False)

            if len(formatted) > max_chars:
                formatted = formatted[:max_chars] + "\n[... truncated ...]"

            logger.info(f"Extracted {len(formatted)} chars from JSON '{filename}'")
            return formatted

        except UnicodeDecodeError:
            logger.error(f"Failed to decode JSON file '{filename}' as UTF-8")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in file '{filename}': {str(e)}")
            return None

    @staticmethod
    async def _extract_from_json(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Extract and format JSON files (non-blocking)."""
        return await asyncio.to_thread(
            TextExtractor._sync_extract_from_json, file_content, filename, max_chars
        )

    @staticmethod
    def _sync_extract_from_yaml(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Synchronous YAML extraction (runs in thread pool)."""
        try:
            text = file_content.decode("utf-8")
            data = yaml.safe_load(text)

            # Convert to formatted YAML string using safe_dump to prevent injection
            formatted = yaml.safe_dump(
                data, default_flow_style=False, allow_unicode=True
            )

            if len(formatted) > max_chars:
                formatted = formatted[:max_chars] + "\n[... truncated ...]"

            logger.info(f"Extracted {len(formatted)} chars from YAML '{filename}'")
            return formatted

        except UnicodeDecodeError:
            logger.error(f"Failed to decode YAML file '{filename}' as UTF-8")
            return None
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in file '{filename}': {str(e)}")
            return None

    @staticmethod
    async def _extract_from_yaml(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Extract and format YAML files (non-blocking)."""
        return await asyncio.to_thread(
            TextExtractor._sync_extract_from_yaml, file_content, filename, max_chars
        )

    @staticmethod
    def _sync_extract_from_text(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Synchronous text extraction (runs in thread pool)."""
        try:
            # Try UTF-8 first
            text = file_content.decode("utf-8")

        except UnicodeDecodeError:
            # Fallback to latin-1
            try:
                text = file_content.decode("latin-1")
                logger.warning(f"File '{filename}' decoded as latin-1 (UTF-8 failed)")
            except Exception as e:
                logger.error(f"Failed to decode text file '{filename}': {str(e)}")
                return None

        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... truncated ...]"

        logger.info(f"Extracted {len(text)} chars from text file '{filename}'")
        return text

    @staticmethod
    async def _extract_from_text(
        file_content: bytes, filename: str, max_chars: int
    ) -> Optional[str]:
        """Extract text from plain text files (non-blocking)."""
        return await asyncio.to_thread(
            TextExtractor._sync_extract_from_text, file_content, filename, max_chars
        )
