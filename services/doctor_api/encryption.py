from cryptography.fernet import Fernet

from settings import settings

_fernet = Fernet(settings.FERNET_KEY.encode())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception as exc:
        raise ValueError(f"Decryption failed: {exc}") from exc
