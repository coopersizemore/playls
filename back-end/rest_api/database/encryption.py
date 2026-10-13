"""Transparent encryption for sensitive columns (Spotify tokens)."""
import os
from cryptography.fernet import Fernet
from sqlalchemy.types import Text, TypeDecorator

# Fernet key, generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_key = os.getenv("TOKEN_ENCRYPTION_KEY")
if not _key:
    raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set (see back-end/env.example)")
_fernet = Fernet(_key)


class EncryptedText(TypeDecorator):
    """Text column that is encrypted before it reaches the database."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _fernet.decrypt(value.encode()).decode()
