"""账号绑定的 CLI 公钥凭证与请求签名验证。"""

import base64
import binascii
import hashlib
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from sqlalchemy.exc import IntegrityError

from backend.database import get_db_session
from backend.models import CliCredential, CliRequestNonce, User


CURRENT_CLI_CREDENTIAL_ID = ContextVar("cli_credential_id", default=None)
MAX_CLOCK_SKEW_SECONDS = 300


def _load_public_key(public_key: str):
    data = (public_key or "").strip().encode("utf-8")
    if not data:
        raise ValueError("公钥不能为空")
    try:
        key = serialization.load_ssh_public_key(data)
    except ValueError:
        try:
            key = serialization.load_pem_public_key(data)
        except ValueError as exc:
            raise ValueError("仅支持 OpenSSH 或 PEM 公钥") from exc
    if isinstance(key, rsa.RSAPublicKey) and key.key_size < 2048:
        raise ValueError("RSA 公钥长度至少为 2048 位")
    if not isinstance(
        key, (ed25519.Ed25519PublicKey, rsa.RSAPublicKey, ec.EllipticCurvePublicKey)
    ):
        raise ValueError("仅支持 Ed25519、RSA 或 ECDSA 公钥")
    return key


def _canonical_public_key(key) -> str:
    return key.public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii")


def public_key_fingerprint(public_key: str) -> tuple[str, str]:
    key = _load_public_key(public_key)
    canonical = _canonical_public_key(key)
    blob = base64.b64decode(canonical.split()[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return canonical, f"SHA256:{digest}"


def create_credential(user_id: str, name: str, public_key: str, expires_at=None) -> dict:
    if len(public_key or "") > 16384:
        raise ValueError("公钥内容过长")
    clean_name = (name or "CLI 凭证").strip()
    if len(clean_name) > 255:
        raise ValueError("CLI 凭证名称不能超过 255 个字符")
    canonical, fingerprint = public_key_fingerprint(public_key)
    db = get_db_session()
    try:
        credential = CliCredential(
            credential_id=str(uuid.uuid4()),
            user_id=user_id,
            name=clean_name or "CLI 凭证",
            public_key=canonical,
            fingerprint=fingerprint,
            enabled=True,
            expires_at=expires_at,
        )
        db.add(credential)
        db.commit()
        return credential_to_dict(credential)
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("该公钥已绑定到其他 CLI 凭证，不能重复使用") from exc
    finally:
        db.close()


def credential_to_dict(item: CliCredential) -> dict:
    return {
        "credential_id": item.credential_id,
        "name": item.name,
        "fingerprint": item.fingerprint,
        "enabled": bool(item.enabled),
        "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def list_credentials(user_id: str) -> list[dict]:
    db = get_db_session()
    try:
        rows = (
            db.query(CliCredential)
            .filter(CliCredential.user_id == user_id)
            .order_by(CliCredential.created_at.desc())
            .all()
        )
        return [credential_to_dict(row) for row in rows]
    finally:
        db.close()


def toggle_credential(user_id: str, credential_id: str):
    db = get_db_session()
    try:
        row = (
            db.query(CliCredential)
            .filter(
                CliCredential.credential_id == credential_id,
                CliCredential.user_id == user_id,
            )
            .first()
        )
        if not row:
            return None
        row.enabled = not row.enabled
        db.commit()
        return bool(row.enabled)
    finally:
        db.close()


def delete_credential(user_id: str, credential_id: str) -> bool:
    db = get_db_session()
    try:
        row = (
            db.query(CliCredential)
            .filter(
                CliCredential.credential_id == credential_id,
                CliCredential.user_id == user_id,
            )
            .first()
        )
        if not row:
            return False
        db.query(CliRequestNonce).filter(
            CliRequestNonce.credential_id == credential_id
        ).delete(synchronize_session=False)
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


def _verify_signature(key, algorithm: str, signature: bytes, message: bytes) -> None:
    if isinstance(key, ed25519.Ed25519PublicKey) and algorithm == "ed25519":
        key.verify(signature, message)
    elif isinstance(key, rsa.RSAPublicKey) and algorithm == "rsa-sha256":
        key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(key, ec.EllipticCurvePublicKey) and algorithm == "ecdsa-sha256":
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    else:
        raise ValueError("签名算法与公钥类型不匹配")


def verify_signed_request(request) -> dict:
    headers = request.headers
    credential_id = headers.get("x-app2docker-credential-id", "").strip()
    timestamp_text = headers.get("x-app2docker-timestamp", "").strip()
    nonce = headers.get("x-app2docker-nonce", "").strip()
    body_hash = headers.get("x-app2docker-content-sha256", "").strip().lower()
    algorithm = headers.get("x-app2docker-signature-algorithm", "").strip().lower()
    signature_text = headers.get("x-app2docker-signature", "").strip()
    if not all(
        (credential_id, timestamp_text, nonce, body_hash, algorithm, signature_text)
    ):
        raise ValueError("CLI 签名请求头不完整")
    if len(nonce) < 16 or len(nonce) > 128:
        raise ValueError("CLI 请求 nonce 格式无效")
    if len(body_hash) != 64 or any(ch not in "0123456789abcdef" for ch in body_hash):
        raise ValueError("CLI 请求体摘要格式无效")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise ValueError("CLI 请求时间戳无效") from exc
    if abs(int(time.time()) - timestamp) > MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("CLI 请求已过期，请校准本机时间")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("CLI 请求签名格式无效") from exc

    raw_path = request.scope.get("raw_path") or request.url.path.encode("utf-8")
    target = raw_path.decode("latin-1")
    query = request.scope.get("query_string", b"")
    if query:
        target += "?" + query.decode("latin-1")
    actual_body_hash = request.scope.get("app2docker.body_sha256")
    if actual_body_hash is not None and actual_body_hash != body_hash:
        raise ValueError("CLI 请求体摘要不匹配")
    message = "\n".join(
        [request.method.upper(), target, timestamp_text, nonce, body_hash]
    ).encode("utf-8")

    db = get_db_session()
    try:
        credential = (
            db.query(CliCredential)
            .filter(
                CliCredential.credential_id == credential_id,
                CliCredential.enabled == True,
            )
            .first()
        )
        if not credential or (
            credential.expires_at and credential.expires_at < datetime.now()
        ):
            raise ValueError("CLI 凭证不存在、已禁用或已过期")
        user = (
            db.query(User)
            .filter(User.user_id == credential.user_id, User.enabled == True)
            .first()
        )
        if not user:
            raise ValueError("CLI 凭证所属用户不存在或已禁用")
        try:
            _verify_signature(
                _load_public_key(credential.public_key), algorithm, signature, message
            )
        except InvalidSignature as exc:
            raise ValueError("CLI 请求签名无效") from exc

        cutoff = datetime.now() - timedelta(seconds=MAX_CLOCK_SKEW_SECONDS * 2)
        db.query(CliRequestNonce).filter(CliRequestNonce.created_at < cutoff).delete(
            synchronize_session=False
        )
        db.add(
            CliRequestNonce(
                nonce_id=f"{credential_id}:{nonce}", credential_id=credential_id
            )
        )
        credential.last_used_at = datetime.now()
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError("CLI 请求 nonce 已使用，拒绝重放") from exc
        CURRENT_CLI_CREDENTIAL_ID.set(credential_id)
        return {
            "user_id": user.user_id,
            "username": user.username,
            "credential_id": credential_id,
            "fingerprint": credential.fingerprint,
        }
    finally:
        db.close()


class RequestBodyHashMiddleware:
    """流式计算请求体摘要，不在内存中复制本地源码包。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        digest = hashlib.sha256()
        completed = False

        async def receive_with_hash():
            nonlocal completed
            message = await receive()
            if message.get("type") == "http.request":
                digest.update(message.get("body", b""))
                if not message.get("more_body", False):
                    completed = True
                    scope["app2docker.body_sha256"] = digest.hexdigest()
            return message

        await self.app(scope, receive_with_hash, send)
        if not completed:
            scope.setdefault("app2docker.body_sha256", hashlib.sha256(b"").hexdigest())
