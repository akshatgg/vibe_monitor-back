import logging
from typing import Optional

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError
from opentelemetry import trace

from app.core.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class S3Client:
    def __init__(self):
        self.bucket = settings.CHAT_UPLOADS_BUCKET
        self.region = settings.AWS_REGION
        self._session = None
        self._s3 = None

    async def _get_s3_client(self):
        """Get or create S3 client using singleton pattern.

        Note: This client must be explicitly closed via close() method
        to prevent connection leaks. The lifespan handler in main.py
        ensures proper cleanup on application shutdown.
        """
        if self._s3 is None:
            self._session = aioboto3.Session()
            client_kwargs = {"region_name": self.region}
            if settings.AWS_ENDPOINT_URL and settings.is_local:
                client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL
            # Use __aenter__ to get the client from the context manager
            # __aexit__ will be called in close() method
            self._s3 = await self._session.client("s3", **client_kwargs).__aenter__()
        return self._s3

    async def generate_upload_url(
        self, key: str, content_type: str = "application/octet-stream"
    ) -> Optional[str]:
        """Generate a presigned URL for uploading a file."""
        try:
            s3 = await self._get_s3_client()
            url = await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=settings.CHAT_UPLOADS_URL_EXPIRY_SECONDS,
            )
            return url
        except (ClientError, BotoCoreError):
            logger.exception("Failed to generate upload URL")
            return None

    async def generate_download_url(
        self, key: str, filename: str | None = None
    ) -> Optional[str]:
        """Generate a presigned URL for downloading a file.

        Args:
            key: S3 object key
            filename: Original filename for Content-Disposition header (prevents XSS)
        """
        try:
            s3 = await self._get_s3_client()
            params = {"Bucket": self.bucket, "Key": key}

            # Add Content-Disposition to force download and prevent XSS
            # This ensures browsers download the file instead of rendering it
            if filename:
                # Sanitize filename: ASCII-only for compatibility, URL-encode for RFC 5987
                # Remove/replace problematic characters that cause issues with S3/LocalStack
                import unicodedata
                from urllib.parse import quote

                # Normalize Unicode and convert to ASCII-safe version
                normalized = unicodedata.normalize("NFKD", filename)
                ascii_filename = normalized.encode("ascii", "ignore").decode("ascii")
                # Replace any remaining problematic chars
                ascii_filename = ascii_filename.replace('"', "'").replace("\\", "_")
                # Fallback if filename becomes empty
                if not ascii_filename:
                    ascii_filename = "download"

                # Use RFC 5987 encoding for full Unicode support in modern browsers
                encoded_filename = quote(filename, safe="")

                params["ResponseContentDisposition"] = (
                    f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
                )

            url = await s3.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=settings.CHAT_UPLOADS_URL_EXPIRY_SECONDS,
            )
            return url
        except (ClientError, BotoCoreError):
            logger.exception("Failed to generate download URL")
            return None

    async def upload_file(
        self, key: str, file_content: bytes, content_type: str
    ) -> bool:
        """Upload file directly to S3."""
        with tracer.start_as_current_span(
            "s3.upload_file",
            attributes={
                "s3.bucket": self.bucket,
                "s3.key": key,
                "s3.size_bytes": len(file_content),
                "s3.content_type": content_type,
            },
        ) as span:
            try:
                s3 = await self._get_s3_client()
                await s3.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=file_content,
                    ContentType=content_type,
                )
                logger.info(f"Uploaded to S3: {key} ({len(file_content)} bytes)")
                span.set_attribute("s3.success", True)
                return True
            except (ClientError, BotoCoreError) as e:
                logger.exception(f"Failed to upload: {key}")
                span.set_attribute("s3.success", False)
                span.set_attribute("s3.error", str(e))
                span.record_exception(e)
                return False

    async def download_file(self, key: str) -> Optional[bytes]:
        """Download file from S3 (for worker image processing)."""
        with tracer.start_as_current_span(
            "s3.download_file",
            attributes={"s3.bucket": self.bucket, "s3.key": key},
        ) as span:
            try:
                s3 = await self._get_s3_client()
                response = await s3.get_object(Bucket=self.bucket, Key=key)
                content = await response["Body"].read()
                logger.info(f"Downloaded from S3: {key} ({len(content)} bytes)")
                span.set_attribute("s3.size_bytes", len(content))
                span.set_attribute("s3.success", True)
                return content
            except (ClientError, BotoCoreError) as e:
                logger.exception(f"Failed to download: {key}")
                span.set_attribute("s3.success", False)
                span.set_attribute("s3.error", str(e))
                span.record_exception(e)
                return None

    async def delete_file(self, key: str) -> bool:
        """Delete a single file from S3."""
        try:
            s3 = await self._get_s3_client()
            await s3.delete_object(Bucket=self.bucket, Key=key)
            logger.info(f"Deleted from S3: {key}")
            return True
        except (ClientError, BotoCoreError):
            logger.exception(f"Failed to delete: {key}")
            return False

    async def delete_files(self, keys: list[str]) -> bool:
        """Delete multiple files from S3 (batch operation)."""
        if not keys:
            return True

        with tracer.start_as_current_span(
            "s3.delete_files",
            attributes={"s3.bucket": self.bucket, "s3.file_count": len(keys)},
        ) as span:
            try:
                s3 = await self._get_s3_client()
                objects = [{"Key": key} for key in keys]
                await s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
                logger.info(f"Deleted {len(keys)} files from S3")
                span.set_attribute("s3.success", True)
                return True
            except (ClientError, BotoCoreError) as e:
                logger.exception(f"Failed to delete {len(keys)} files")
                span.set_attribute("s3.success", False)
                span.set_attribute("s3.error", str(e))
                span.record_exception(e)
                return False

    async def close(self):
        if self._s3:
            await self._s3.__aexit__(None, None, None)
            self._s3 = None
        self._session = None


s3_client = S3Client()
