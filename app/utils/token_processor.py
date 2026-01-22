import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


class TokenProcessor:
    """
    Token encryption and decryption utility using Fernet symmetric encryption
    """

    def __init__(self):
        self._fernet = Fernet(self._get_encryption_key())

    @staticmethod
    def _get_encryption_key() -> bytes:
        """
        Generate encryption key from JWT secret

        Returns:
            bytes: URL-safe base64-encoded encryption key

        Raises:
            Exception: If key generation fails
        """
        try:
            secret = settings.CRYPTOGRAPHY_SECRET
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
            return key
        except Exception as err:
            raise Exception(f"Error generating encryption key: {err}")

    def encrypt(self, token: str) -> str:
        """
        Encrypt a token string

        Args:
            token: Plain text token to encrypt

        Returns:
            str: Encrypted token as string
        """
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, encrypted_token: str) -> str:
        """
        Decrypt an encrypted token string

        Args:
            encrypted_token: Encrypted token string

        Returns:
            str: Decrypted plain text token
        """
        return self._fernet.decrypt(encrypted_token.encode()).decode()


token_processor = TokenProcessor()
