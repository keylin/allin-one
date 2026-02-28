"""凭证加解密模块 — Fernet 对称加密

兼容策略:
- 未配置 CREDENTIAL_ENCRYPTION_KEY 时透传明文，零破坏
- decrypt_credential 对非 Fernet 格式数据透传，兼容未加密的历史数据
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet() -> Fernet | None:
    key = settings.CREDENTIAL_ENCRYPTION_KEY
    if not key:
        return None
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_credential(plaintext: str) -> str:
    """加密凭证明文。未配置密钥时原样返回。"""
    f = _get_fernet()
    if not f:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """解密凭证密文。未配置密钥或非 Fernet 格式时原样返回（兼容历史数据）。"""
    f = _get_fernet()
    if not f:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ciphertext
