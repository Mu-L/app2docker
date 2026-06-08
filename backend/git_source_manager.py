# backend/git_source_manager.py
"""Git 数据源管理器 - 用于管理验证过的 Git 仓库（基于数据库）"""
import base64
import uuid
import threading
from datetime import datetime
from typing import Optional, Dict, List
from backend.database import get_db_session, init_db
from backend.models import GitSource, User
from backend.crypto_utils import encrypt_password, decrypt_password

# 确保数据库已初始化
try:
    init_db()
except:
    pass


class GitSourceManager:
    """Git 数据源管理器（基于数据库）"""

    def __init__(self):
        self.lock = threading.RLock()

    def _resolve_created_by_name(self, db, created_by: Optional[str]) -> Optional[str]:
        if not created_by:
            return None
        user = db.query(User).filter(User.user_id == created_by).first()
        return user.username if user else None

    def _to_dict(
        self,
        source: GitSource,
        include_password: bool = False,
        db=None,
    ) -> Optional[Dict]:
        """将数据库模型转换为字典"""
        if not source:
            return None

        own_db = db is None
        if own_db:
            db = get_db_session()

        try:
            created_by_name = self._resolve_created_by_name(db, source.created_by)
        finally:
            if own_db:
                db.close()
                db = None

        result = {
            "source_id": source.source_id,
            "name": source.name,
            "description": source.description,
            "git_url": source.git_url,
            "branches": source.branches or [],
            "tags": source.tags or [],
            "default_branch": source.default_branch,
            "username": source.username,
            "dockerfiles": source.dockerfiles or {},
            "created_at": source.created_at.isoformat() if source.created_at else None,
            "updated_at": source.updated_at.isoformat() if source.updated_at else None,
            "team_id": source.team_id,
            "created_by": source.created_by,
            "created_by_name": created_by_name,
            "scope": source.scope or "personal",
            "visibility": source.visibility or "private",
        }

        if include_password:
            # 返回解密后的密码（用于内部操作）
            if source.password:
                try:
                    result["password"] = decrypt_password(source.password)
                except (ValueError, Exception):
                    # 如果解密失败，尝试迁移旧格式（base64编码）
                    try:
                        # 尝试base64解码
                        plaintext = base64.b64decode(
                            source.password.encode("utf-8")
                        ).decode("utf-8")
                        # 加密后更新数据库
                        encrypted = encrypt_password(plaintext)
                        db = get_db_session()
                        try:
                            source_obj = (
                                db.query(GitSource)
                                .filter(GitSource.source_id == source.source_id)
                                .first()
                            )
                            if source_obj:
                                source_obj.password = encrypted
                                db.commit()
                        finally:
                            db.close()
                        result["password"] = plaintext
                    except Exception as e:
                        print(f"⚠️ 解密GitSource密码失败: {e}")
                        result["password"] = None
            else:
                result["password"] = None
        else:
            result["has_password"] = bool(source.password)

        return result

    def create_source(
        self,
        name: str,
        git_url: str,
        description: str = "",
        branches: List[str] = None,
        tags: List[str] = None,
        default_branch: str = None,
        username: str = None,
        password: str = None,
        dockerfiles: Dict[str, str] = None,
        team_id: str = None,
        created_by: str = None,
        scope: str = "personal",
        visibility: str = "private",
    ) -> str:
        """创建 Git 数据源"""
        source_id = str(uuid.uuid4())
        scope = (scope or "personal").strip().lower()
        visibility = (visibility or "private").strip().lower()
        if scope == "personal":
            visibility = "private"

        # 加密密码（使用 AES 加密）
        encrypted_password = None
        if password:
            encrypted_password = encrypt_password(password)

        db = get_db_session()
        try:
            source = GitSource(
                source_id=source_id,
                name=name,
                description=description,
                git_url=git_url,
                branches=branches or [],
                tags=tags or [],
                default_branch=default_branch,
                username=username or "",
                password=encrypted_password,
                dockerfiles=dockerfiles or {},
                team_id=team_id,
                created_by=created_by,
                scope=scope,
                visibility=visibility,
            )

            db.add(source)
            db.commit()
            return source_id
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def get_source(
        self, source_id: str, include_password: bool = False
    ) -> Optional[Dict]:
        """获取数据源配置"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            return self._to_dict(source, include_password)
        finally:
            db.close()

    def list_sources(self, include_password: bool = False, query: Optional[str] = None) -> List[Dict]:
        """列出所有数据源配置，支持模糊查询"""
        db = get_db_session()
        try:
            query_obj = db.query(GitSource)
            
            # 如果提供了查询关键词，进行模糊搜索
            if query:
                query_lower = query.lower().strip()
                # 对名称、Git URL、描述进行模糊匹配
                query_obj = query_obj.filter(
                    (GitSource.name.ilike(f"%{query_lower}%")) |
                    (GitSource.git_url.ilike(f"%{query_lower}%")) |
                    (GitSource.description.ilike(f"%{query_lower}%"))
                )
            
            sources = query_obj.order_by(GitSource.created_at.desc()).all()
            result = [
                self._to_dict(s, include_password, db=db) for s in sources
            ]
            
            # 限制返回结果数量（最多50条）
            if len(result) > 50:
                result = result[:50]
            
            return result
        finally:
            db.close()

    def update_source(
        self,
        source_id: str,
        name: str = None,
        git_url: str = None,
        description: str = None,
        branches: List[str] = None,
        tags: List[str] = None,
        default_branch: str = None,
        username: str = None,
        password: str = None,
        scope: str = None,
        visibility: str = None,
    ) -> bool:
        """更新数据源配置"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source:
                return False

            if name is not None:
                source.name = name
            if git_url is not None:
                source.git_url = git_url
            if description is not None:
                source.description = description
            if branches is not None:
                source.branches = branches
            if tags is not None:
                source.tags = tags
            if default_branch is not None:
                source.default_branch = default_branch
            if username is not None:
                source.username = username
            if password is not None:
                if password:
                    # 加密密码后存储
                    source.password = encrypt_password(password)
                else:
                    source.password = None
            if scope is not None:
                source.scope = (scope or "personal").strip().lower()
            if visibility is not None:
                source.visibility = (visibility or "private").strip().lower()
            if (source.scope or "personal") == "personal":
                source.visibility = "private"

            if source.dockerfiles is None:
                source.dockerfiles = {}

            source.updated_at = datetime.now()
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_source(self, source_id: str) -> bool:
        """删除数据源配置"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source:
                return False

            db.delete(source)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def get_source_by_url(self, git_url: str) -> Optional[Dict]:
        """通过 Git URL 获取数据源配置（全局，兼容旧逻辑）"""
        db = get_db_session()
        try:
            source = db.query(GitSource).filter(GitSource.git_url == git_url).first()
            return self._to_dict(source, db=db)
        finally:
            db.close()

    def upsert_personal_credentials(
        self,
        team_id: str,
        created_by: str,
        git_url: str,
        username: str = None,
        password: str = None,
        name: str = None,
    ) -> tuple[str, bool]:
        """
        创建或更新当前用户的个人数据源凭据。
        返回 (source_id, created) — created=False 表示更新了已有记录。
        """
        existing = self.get_personal_source_by_url(team_id, created_by, git_url)
        if existing:
            self.update_source(
                source_id=existing["source_id"],
                username=username,
                password=password,
            )
            return existing["source_id"], False

        repo_name = (
            git_url.rstrip("/").split("/")[-1].replace(".git", "") or "repo"
        )
        source_id = self.create_source(
            name=name or repo_name,
            git_url=git_url,
            username=username,
            password=password,
            team_id=team_id,
            created_by=created_by,
            scope="personal",
            visibility="private",
        )
        return source_id, True

    def get_personal_source_by_url(
        self, team_id: str, created_by: str, git_url: str
    ) -> Optional[Dict]:
        """同一团队 + 创建者 + URL 的个人数据源"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource)
                .filter(
                    GitSource.team_id == team_id,
                    GitSource.created_by == created_by,
                    GitSource.git_url == git_url,
                    GitSource.scope == "personal",
                )
                .first()
            )
            return self._to_dict(source, db=db)
        finally:
            db.close()

    def get_source_by_scope_url(
        self,
        team_id: str,
        git_url: str,
        scope: str,
        created_by: Optional[str] = None,
    ) -> Optional[Dict]:
        """按团队、URL、scope（及可选创建者）匹配数据源"""
        db = get_db_session()
        try:
            query = db.query(GitSource).filter(
                GitSource.team_id == team_id,
                GitSource.git_url == git_url,
                GitSource.scope == (scope or "personal").strip().lower(),
            )
            if created_by:
                query = query.filter(GitSource.created_by == created_by)
            source = query.first()
            return self._to_dict(source, db=db)
        finally:
            db.close()

    def get_decrypted_password(self, source_id: str) -> Optional[str]:
        """获取解密后的密码"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source or not source.password:
                return None
            try:
                # 尝试解密（AES加密格式）
                return decrypt_password(source.password)
            except (ValueError, Exception):
                # 如果解密失败，尝试迁移旧格式（base64编码）
                try:
                    # 尝试base64解码
                    plaintext = base64.b64decode(
                        source.password.encode("utf-8")
                    ).decode("utf-8")
                    # 加密后更新数据库
                    encrypted = encrypt_password(plaintext)
                    source.password = encrypted
                    db.commit()
                    return plaintext
                except Exception as e:
                    print(f"⚠️ 解密GitSource密码失败: {e}")
                    return None
        finally:
            db.close()

    def get_auth_config(self, source_id: str) -> Dict[str, str]:
        """获取数据源的认证配置"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source:
                return {}

            auth_config = {}
            if source.username:
                auth_config["username"] = source.username

            password = self.get_decrypted_password(source_id)
            if password:
                auth_config["password"] = password

            return auth_config
        finally:
            db.close()

    def update_dockerfile(
        self, source_id: str, dockerfile_path: str, content: str
    ) -> bool:
        """更新或创建 Dockerfile"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source:
                return False

            if not source.dockerfiles:
                source.dockerfiles = {}

            source.dockerfiles[dockerfile_path] = content
            source.updated_at = datetime.now()
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_dockerfile(self, source_id: str, dockerfile_path: str) -> bool:
        """删除 Dockerfile"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source or not source.dockerfiles:
                return False

            if dockerfile_path in source.dockerfiles:
                del source.dockerfiles[dockerfile_path]
                source.updated_at = datetime.now()
                db.commit()
                return True

            return False
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()

    def get_dockerfile(self, source_id: str, dockerfile_path: str) -> Optional[str]:
        """获取 Dockerfile 内容"""
        db = get_db_session()
        try:
            source = (
                db.query(GitSource).filter(GitSource.source_id == source_id).first()
            )
            if not source or not source.dockerfiles:
                return None

            return source.dockerfiles.get(dockerfile_path)
        finally:
            db.close()
