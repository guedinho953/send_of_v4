import hashlib
import base64
from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet():
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    key_b64 = base64.urlsafe_b64encode(key)
    return Fernet(key_b64)


def encrypt(plain_text: str) -> str:
    if not plain_text:
        return ''
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    if not cipher_text:
        return ''
    return _get_fernet().decrypt(cipher_text.encode()).decode()
