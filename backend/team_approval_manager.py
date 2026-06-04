"""Generic team approval requests and image write handlers."""
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi import HTTPException

from backend.database import get_db_session
from backend.migration_manager import (
    MigrationTaskManager,
    _parse_image_ref,
    registry_write_requires_approval,
    test_source_image_availability,
)
from backend.models import TeamApprovalRequest, User


REQUEST_TYPE_IMAGE_TAG = "image_tag"
REQUEST_TYPE_IMAGE_MIGRATION = "image_migration"
TERMINAL_STATUSES = {"completed", "failed", "rejected", "canceled"}


def _usernames_by_id(user_ids):
    ids = [uid for uid in set(user_ids or []) if uid]
    if not ids:
        return {}
    db = get_db_session()
    try:
        return {
            row.user_id: row.username
            for row in db.query(User.user_id, User.username)
            .filter(User.user_id.in_(ids))
            .all()
        }
    finally:
        db.close()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _validate_migration_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_registry_name = _clean_text(payload.get("source_registry_name"))
    target_registry_name = _clean_text(payload.get("target_registry_name"))
    source_image = _clean_text(payload.get("source_image"))
    target_image = _clean_text(payload.get("target_image"))
    allow_overwrite = bool(payload.get("allow_overwrite"))

    if not source_registry_name:
        raise ValueError("请选择源镜像仓库")
    if not target_registry_name:
        raise ValueError("请选择目标镜像仓库")
    if not source_image:
        raise ValueError("请填写源镜像")
    if not target_image:
        raise ValueError("请填写目标镜像")

    _parse_image_ref(source_image)
    _parse_image_ref(target_image)

    return {
        "source_registry_name": source_registry_name,
        "source_image": source_image,
        "target_registry_name": target_registry_name,
        "target_image": target_image,
        "allow_overwrite": allow_overwrite,
    }


def _validate_tag_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    registry_name = _clean_text(payload.get("registry_name"))
    image_name = _clean_text(payload.get("image_name")).strip("/")
    source_tag = _clean_text(payload.get("source_tag")) or "latest"
    target_tag = _clean_text(payload.get("target_tag")) or "latest"
    allow_overwrite = bool(payload.get("allow_overwrite"))

    if not registry_name:
        raise ValueError("请选择镜像仓库")
    if not image_name:
        raise ValueError("请填写镜像名")
    if " " in image_name:
        raise ValueError("镜像名不能包含空格")
    if ":" in image_name.rsplit("/", 1)[-1]:
        raise ValueError("镜像名不能包含标签，请分别填写源标签和目标标签")
    if source_tag == target_tag:
        raise ValueError("源标签和目标标签不能相同")

    source_image = f"{image_name}:{source_tag}"
    target_image = f"{image_name}:{target_tag}"
    _parse_image_ref(source_image)
    _parse_image_ref(target_image)

    return {
        "registry_name": registry_name,
        "image_name": image_name,
        "source_tag": source_tag,
        "target_tag": target_tag,
        "source_registry_name": registry_name,
        "source_image": source_image,
        "target_registry_name": registry_name,
        "target_image": target_image,
        "allow_overwrite": allow_overwrite,
    }


def _title_for_migration(payload: Dict[str, Any]) -> str:
    return f"镜像迁移：{payload['source_image']} -> {payload['target_image']}"


def _title_for_tag(payload: Dict[str, Any]) -> str:
    return (
        f"镜像打标：{payload['image_name']}:"
        f"{payload['source_tag']} -> {payload['target_tag']}"
    )


def _target_exists(payload: Dict[str, Any], team_id: str, user_id: str) -> bool:
    result = test_source_image_availability(
        payload["target_image"],
        payload["target_registry_name"],
        team_id,
        user_id,
    )
    return bool(result.get("success"))


def _execute_image_write_request(
    request_row: TeamApprovalRequest,
    reviewer_id: str,
    *,
    payload: Dict[str, Any],
    title: str,
) -> Dict[str, Any]:
    if not registry_write_requires_approval(
        payload["target_registry_name"], request_row.team_id, reviewer_id
    ):
        raise HTTPException(status_code=400, detail="目标仓库不是认证仓库，无需团队申请")

    if not payload.get("allow_overwrite") and _target_exists(
        payload, request_row.team_id, reviewer_id
    ):
        raise HTTPException(
            status_code=409,
            detail="目标镜像标签已存在，申请未允许覆盖，无法通过审核",
        )

    task_id = MigrationTaskManager().create_task(
        task_name=request_row.title or title,
        source_image=payload["source_image"],
        target_image=payload["target_image"],
        source_registry_name=payload["source_registry_name"],
        target_registry_name=payload["target_registry_name"],
        team_id=request_row.team_id,
        created_by=request_row.requested_by,
        approval_request_id=request_row.request_id,
        execute_now=True,
    )
    return {
        "migration_task_id": task_id,
        "source_image": payload["source_image"],
        "target_image": payload["target_image"],
    }


def _execute_migration_request(request_row, reviewer_id: str) -> Dict[str, Any]:
    payload = _validate_migration_payload(request_row.payload or {})
    return _execute_image_write_request(
        request_row,
        reviewer_id,
        payload=payload,
        title=_title_for_migration(payload),
    )


def _execute_tag_request(request_row, reviewer_id: str) -> Dict[str, Any]:
    payload = _validate_tag_payload(request_row.payload or {})
    return _execute_image_write_request(
        request_row,
        reviewer_id,
        payload=payload,
        title=_title_for_tag(payload),
    )


APPROVAL_HANDLERS = {
    REQUEST_TYPE_IMAGE_TAG: {
        "validate_payload": _validate_tag_payload,
        "title": _title_for_tag,
        "approve_execute": _execute_tag_request,
    },
    REQUEST_TYPE_IMAGE_MIGRATION: {
        "validate_payload": _validate_migration_payload,
        "title": _title_for_migration,
        "approve_execute": _execute_migration_request,
    },
}


def _handler_for(request_type: str):
    handler = APPROVAL_HANDLERS.get(request_type)
    if not handler:
        raise ValueError(f"不支持的申请类型: {request_type}")
    return handler


def _sync_execution_status(row: TeamApprovalRequest) -> None:
    if not row or row.status in TERMINAL_STATUSES:
        return
    result = row.result or {}
    task_id = result.get("migration_task_id")
    if not task_id:
        return

    task = MigrationTaskManager().get_task(task_id)
    if not task:
        return
    now = datetime.now()
    task_status = task.get("status")
    last_status = task.get("last_run_status")
    if last_status == "completed":
        row.status = "completed"
        row.completed_at = row.completed_at or now
        row.error = ""
    elif task_status == "failed" or last_status == "failed":
        row.status = "failed"
        row.completed_at = row.completed_at or now
        row.error = task.get("error") or row.error or "执行失败"
    elif task_status in ("pending", "running"):
        row.status = "running"
    elif row.status == "approved":
        row.status = "running"
    row.updated_at = now


def _to_dict(row: TeamApprovalRequest, usernames: Optional[Dict[str, str]] = None) -> dict:
    usernames = usernames or {}
    return {
        "request_id": row.request_id,
        "team_id": row.team_id,
        "request_type": row.request_type,
        "title": row.title,
        "status": row.status,
        "requested_by": row.requested_by,
        "requested_by_username": usernames.get(row.requested_by),
        "reviewed_by": row.reviewed_by,
        "reviewed_by_username": usernames.get(row.reviewed_by),
        "review_note": row.review_note or "",
        "payload": row.payload or {},
        "result": row.result or {},
        "error": row.error or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class TeamApprovalManager:
    def create_request(
        self,
        *,
        team_id: str,
        request_type: str,
        payload: Dict[str, Any],
        requested_by: str,
        title: str = "",
    ) -> str:
        handler = _handler_for(request_type)
        cleaned_payload = handler["validate_payload"](payload or {})
        request_title = _clean_text(title) or handler["title"](cleaned_payload)

        db = get_db_session()
        try:
            request_id = str(uuid.uuid4())
            now = datetime.now()
            row = TeamApprovalRequest(
                request_id=request_id,
                team_id=team_id,
                request_type=request_type,
                title=request_title,
                status="pending",
                requested_by=requested_by,
                payload=cleaned_payload,
                result={},
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            return request_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list_requests(
        self,
        *,
        team_id: str,
        status: Optional[str] = None,
        request_type: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> list[dict]:
        db = get_db_session()
        try:
            q = db.query(TeamApprovalRequest).filter(
                TeamApprovalRequest.team_id == team_id
            )
            if status:
                q = q.filter(TeamApprovalRequest.status == status)
            if request_type:
                q = q.filter(TeamApprovalRequest.request_type == request_type)
            if requested_by:
                q = q.filter(TeamApprovalRequest.requested_by == requested_by)
            rows = q.order_by(TeamApprovalRequest.created_at.desc()).all()
            changed = False
            for row in rows:
                before = row.status
                _sync_execution_status(row)
                changed = changed or before != row.status
            if changed:
                db.commit()
            usernames = _usernames_by_id(
                [r.requested_by for r in rows] + [r.reviewed_by for r in rows]
            )
            return [_to_dict(r, usernames) for r in rows]
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_request(self, request_id: str) -> Optional[dict]:
        db = get_db_session()
        try:
            row = (
                db.query(TeamApprovalRequest)
                .filter(TeamApprovalRequest.request_id == request_id)
                .first()
            )
            if not row:
                return None
            before = row.status
            _sync_execution_status(row)
            if before != row.status:
                db.commit()
            usernames = _usernames_by_id([row.requested_by, row.reviewed_by])
            return _to_dict(row, usernames)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def approve_request(
        self,
        request_id: str,
        *,
        reviewer_id: str,
        review_note: str = "",
    ) -> dict:
        db = get_db_session()
        try:
            row = (
                db.query(TeamApprovalRequest)
                .filter(TeamApprovalRequest.request_id == request_id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="申请不存在")
            if row.status != "pending":
                raise HTTPException(status_code=400, detail="只有待审核申请可以同意")

            now = datetime.now()
            row.status = "approved"
            row.reviewed_by = reviewer_id
            row.review_note = review_note or ""
            row.reviewed_at = now
            row.started_at = now
            row.updated_at = now
            request_snapshot = SimpleNamespace(
                request_id=row.request_id,
                team_id=row.team_id,
                request_type=row.request_type,
                title=row.title,
                requested_by=row.requested_by,
                payload=dict(row.payload or {}),
            )
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            execute_result = _handler_for(request_snapshot.request_type)["approve_execute"](
                request_snapshot,
                reviewer_id,
            )
        except HTTPException:
            self._reset_pending_after_approval_error(request_id)
            raise
        except Exception as e:
            self._mark_failed(request_id, str(e))
            raise

        db = get_db_session()
        try:
            saved = (
                db.query(TeamApprovalRequest)
                .filter(TeamApprovalRequest.request_id == request_id)
                .first()
            )
            saved.status = "running"
            saved.result = execute_result
            saved.error = ""
            saved.updated_at = datetime.now()
            db.commit()
        finally:
            db.close()
        return self.get_request(request_id) or {}

    def reject_request(
        self,
        request_id: str,
        *,
        reviewer_id: str,
        review_note: str = "",
    ) -> dict:
        db = get_db_session()
        try:
            row = (
                db.query(TeamApprovalRequest)
                .filter(TeamApprovalRequest.request_id == request_id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="申请不存在")
            if row.status != "pending":
                raise HTTPException(status_code=400, detail="只有待审核申请可以驳回")
            now = datetime.now()
            row.status = "rejected"
            row.reviewed_by = reviewer_id
            row.review_note = review_note or ""
            row.reviewed_at = now
            row.completed_at = now
            row.updated_at = now
            db.commit()
            return self.get_request(request_id) or {}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _reset_pending_after_approval_error(self, request_id: str) -> None:
        db = get_db_session()
        try:
            row = (
                db.query(TeamApprovalRequest)
                .filter(TeamApprovalRequest.request_id == request_id)
                .first()
            )
            if row and row.status == "approved":
                row.status = "pending"
                row.reviewed_by = None
                row.review_note = ""
                row.reviewed_at = None
                row.started_at = None
                row.updated_at = datetime.now()
                db.commit()
        finally:
            db.close()

    def _mark_failed(self, request_id: str, error: str) -> None:
        db = get_db_session()
        try:
            row = (
                db.query(TeamApprovalRequest)
                .filter(TeamApprovalRequest.request_id == request_id)
                .first()
            )
            if row:
                row.status = "failed"
                row.error = error
                row.completed_at = datetime.now()
                row.updated_at = datetime.now()
                db.commit()
        finally:
            db.close()
