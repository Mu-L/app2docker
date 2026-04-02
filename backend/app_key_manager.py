"""APP Key 管理模块"""
import secrets
import hashlib
from datetime import datetime
from typing import Optional

from backend.database import get_db_session
from backend.models import AppKey, User


def _hash_app_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_app_key(user_id: str, name: str, expires_at: Optional[datetime] = None) -> dict:
    """为用户生成新的 APP Key（仅返回一次明文）"""
    db = get_db_session()
    try:
        raw_key = f"a2d_{secrets.token_hex(16)}"
        key_hash = _hash_app_key(raw_key)
        key_prefix = raw_key[:12]

        app_key = AppKey(
            user_id=user_id,
            name=name.strip() if name else "未命名密钥",
            key_hash=key_hash,
            key_prefix=key_prefix,
            enabled=True,
            expires_at=expires_at,
        )
        db.add(app_key)
        db.commit()
        db.refresh(app_key)

        return {
            "key_id": app_key.key_id,
            "name": app_key.name,
            "key_prefix": app_key.key_prefix,
            "enabled": app_key.enabled,
            "created_at": app_key.created_at.isoformat() if app_key.created_at else None,
            "expires_at": app_key.expires_at.isoformat() if app_key.expires_at else None,
            "app_key": raw_key,
        }
    finally:
        db.close()


def validate_app_key(raw_key: str) -> Optional[dict]:
    """校验 APP Key，返回用户信息"""
    if not raw_key:
        return None

    db = get_db_session()
    try:
        key_hash = _hash_app_key(raw_key.strip())
        app_key = (
            db.query(AppKey)
            .filter(AppKey.key_hash == key_hash, AppKey.enabled == True)
            .first()
        )
        if not app_key:
            return None

        if app_key.expires_at and app_key.expires_at < datetime.now():
            return None

        user = (
            db.query(User)
            .filter(User.user_id == app_key.user_id, User.enabled == True)
            .first()
        )
        if not user:
            return None

        app_key.last_used_at = datetime.now()
        db.commit()

        return {"user_id": user.user_id, "username": user.username, "key_id": app_key.key_id}
    finally:
        db.close()


def get_user_app_keys(user_id: str) -> list[dict]:
    """获取用户 APP Key 列表（不返回明文）"""
    db = get_db_session()
    try:
        keys = (
            db.query(AppKey)
            .filter(AppKey.user_id == user_id)
            .order_by(AppKey.created_at.desc())
            .all()
        )
        return [
            {
                "key_id": item.key_id,
                "name": item.name,
                "key_prefix": item.key_prefix,
                "enabled": item.enabled,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            }
            for item in keys
        ]
    finally:
        db.close()


def delete_app_key(key_id: str, user_id: str) -> bool:
    db = get_db_session()
    try:
        app_key = db.query(AppKey).filter(AppKey.key_id == key_id, AppKey.user_id == user_id).first()
        if not app_key:
            return False
        db.delete(app_key)
        db.commit()
        return True
    finally:
        db.close()


def toggle_app_key(key_id: str, user_id: str) -> Optional[bool]:
    db = get_db_session()
    try:
        app_key = db.query(AppKey).filter(AppKey.key_id == key_id, AppKey.user_id == user_id).first()
        if not app_key:
            return None
        app_key.enabled = not app_key.enabled
        db.commit()
        return app_key.enabled
    finally:
        db.close()

