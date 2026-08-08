# backend/migrate.py
"""数据迁移脚本：从 JSON 文件迁移到数据库"""
import json
import os
import base64
import uuid
from datetime import datetime
from backend.database import init_db, get_db_session
from backend.models import (
    Pipeline, Task, GitSource, Host, ResourcePackage, OperationLog, ExportTask, PipelineTaskHistory
)

# JSON 文件路径
PIPELINES_FILE = "data/pipelines.json"
GIT_SOURCES_FILE = "data/git_sources.json"
HOSTS_METADATA_FILE = "data/hosts/metadata.json"
RESOURCE_PACKAGES_METADATA_FILE = "data/resource_packages/metadata.json"
TASKS_FILE = "data/docker_build/tasks/tasks.json"
EXPORT_TASKS_FILE = "data/exports/tasks/tasks.json"
OPERATION_LOGS_FILE = "data/logs/operations.jsonl"


def migrate_pipelines(db):
    """迁移流水线数据"""
    if not os.path.exists(PIPELINES_FILE):
        print("⚠️ 流水线文件不存在，跳过迁移")
        return 0
    
    try:
        with open(PIPELINES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            pipelines = data.get("pipelines", {})
        
        count = 0
        for pipeline_id, pipeline_data in pipelines.items():
            # 检查是否已存在
            existing = db.query(Pipeline).filter(Pipeline.pipeline_id == pipeline_id).first()
            if existing:
                print(f"⏭️ 流水线 {pipeline_id} 已存在，跳过")
                continue
            
            # 转换日期时间
            created_at = None
            updated_at = None
            last_triggered_at = None
            next_run_time = None
            
            if pipeline_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(pipeline_data["created_at"])
                except:
                    pass
            
            if pipeline_data.get("updated_at"):
                try:
                    updated_at = datetime.fromisoformat(pipeline_data["updated_at"])
                except:
                    pass
            
            if pipeline_data.get("last_triggered_at"):
                try:
                    last_triggered_at = datetime.fromisoformat(pipeline_data["last_triggered_at"])
                except:
                    pass
            
            if pipeline_data.get("next_run_time"):
                try:
                    next_run_time = datetime.fromisoformat(pipeline_data["next_run_time"])
                except:
                    pass
            
            pipeline = Pipeline(
                pipeline_id=pipeline_id,
                name=pipeline_data.get("name", ""),
                description=pipeline_data.get("description", ""),
                enabled=pipeline_data.get("enabled", True),
                git_url=pipeline_data.get("git_url", ""),
                branch=pipeline_data.get("branch"),
                profile=pipeline_data.get("profile"),
                sub_path=pipeline_data.get("sub_path"),
                project_type=pipeline_data.get("project_type", "jar"),
                template=pipeline_data.get("template"),
                image_name=pipeline_data.get("image_name"),
                tag=pipeline_data.get("tag", "latest"),
                push=pipeline_data.get("push", False),
                push_registry=pipeline_data.get("push_registry"),
                template_params=pipeline_data.get("template_params", {}),
                use_project_dockerfile=pipeline_data.get("use_project_dockerfile", True),
                dockerfile_name=pipeline_data.get("dockerfile_name", "Dockerfile"),
                webhook_token=pipeline_data.get("webhook_token", str(uuid.uuid4())),
                webhook_secret=pipeline_data.get("webhook_secret"),
                webhook_branch_filter=pipeline_data.get("webhook_branch_filter", False),
                webhook_use_push_branch=pipeline_data.get("webhook_use_push_branch", True),
                branch_tag_mapping=pipeline_data.get("branch_tag_mapping", {}),
                selected_services=pipeline_data.get("selected_services", []),
                service_push_config=pipeline_data.get("service_push_config", {}),
                service_template_params=pipeline_data.get("service_template_params", {}),
                push_mode=pipeline_data.get("push_mode", "multi"),
                resource_package_configs=pipeline_data.get("resource_package_configs", []),
                cron_expression=pipeline_data.get("cron_expression"),
                next_run_time=next_run_time,
                current_task_id=pipeline_data.get("current_task_id"),
                task_queue=pipeline_data.get("task_queue", []),
                source_id=pipeline_data.get("source_id"),
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                last_triggered_at=last_triggered_at,
                trigger_count=pipeline_data.get("trigger_count", 0),
            )
            
            db.add(pipeline)
            count += 1
        
        db.commit()
        print(f"✅ 迁移了 {count} 个流水线")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移流水线失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_git_sources(db):
    """迁移 Git 数据源"""
    if not os.path.exists(GIT_SOURCES_FILE):
        print("⚠️ Git 数据源文件不存在，跳过迁移")
        return 0
    
    try:
        with open(GIT_SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            sources = data.get("sources", {})
        
        count = 0
        for source_id, source_data in sources.items():
            existing = db.query(GitSource).filter(GitSource.source_id == source_id).first()
            if existing:
                print(f"⏭️ Git 数据源 {source_id} 已存在，跳过")
                continue
            
            created_at = None
            updated_at = None
            
            if source_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(source_data["created_at"])
                except:
                    pass
            
            if source_data.get("updated_at"):
                try:
                    updated_at = datetime.fromisoformat(source_data["updated_at"])
                except:
                    pass
            
            git_source = GitSource(
                source_id=source_id,
                name=source_data.get("name", ""),
                description=source_data.get("description", ""),
                git_url=source_data.get("git_url", ""),
                branches=source_data.get("branches", []),
                tags=source_data.get("tags", []),
                default_branch=source_data.get("default_branch"),
                username=source_data.get("username"),
                password=source_data.get("password"),  # 已经是加密的
                dockerfiles=source_data.get("dockerfiles", {}),
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
            )
            
            db.add(git_source)
            count += 1
        
        db.commit()
        print(f"✅ 迁移了 {count} 个 Git 数据源")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移 Git 数据源失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_hosts(db):
    """迁移主机数据"""
    if not os.path.exists(HOSTS_METADATA_FILE):
        print("⚠️ 主机元数据文件不存在，跳过迁移")
        return 0
    
    try:
        with open(HOSTS_METADATA_FILE, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        count = 0
        for host_id, host_data in metadata.items():
            existing = db.query(Host).filter(Host.host_id == host_id).first()
            if existing:
                print(f"⏭️ 主机 {host_id} 已存在，跳过")
                continue
            
            created_at = None
            updated_at = None
            
            if host_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(host_data["created_at"])
                except:
                    pass
            
            if host_data.get("updated_at"):
                try:
                    updated_at = datetime.fromisoformat(host_data["updated_at"])
                except:
                    pass
            
            host = Host(
                host_id=host_id,
                name=host_data.get("name", ""),
                host=host_data.get("host", ""),
                port=host_data.get("port", 22),
                username=host_data.get("username"),
                password=host_data.get("password"),
                private_key=host_data.get("private_key"),
                key_password=host_data.get("key_password"),
                docker_enabled=host_data.get("docker_enabled", False),
                docker_version=host_data.get("docker_version"),
                description=host_data.get("description", ""),
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
            )
            
            db.add(host)
            count += 1
        
        db.commit()
        print(f"✅ 迁移了 {count} 个主机")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移主机失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_resource_packages(db):
    """迁移资源包数据"""
    if not os.path.exists(RESOURCE_PACKAGES_METADATA_FILE):
        print("⚠️ 资源包元数据文件不存在，跳过迁移")
        return 0
    
    try:
        with open(RESOURCE_PACKAGES_METADATA_FILE, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        count = 0
        for package_id, package_data in metadata.items():
            existing = db.query(ResourcePackage).filter(ResourcePackage.package_id == package_id).first()
            if existing:
                print(f"⏭️ 资源包 {package_id} 已存在，跳过")
                continue
            
            created_at = None
            updated_at = None
            
            if package_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(package_data["created_at"])
                except:
                    pass
            
            if package_data.get("updated_at"):
                try:
                    updated_at = datetime.fromisoformat(package_data["updated_at"])
                except:
                    pass
            
            package = ResourcePackage(
                package_id=package_id,
                name=package_data.get("name", ""),
                description=package_data.get("description", ""),
                filename=package_data.get("filename", ""),
                size=package_data.get("size", 0),
                extracted=package_data.get("extracted", False),
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
            )
            
            db.add(package)
            count += 1
        
        db.commit()
        print(f"✅ 迁移了 {count} 个资源包")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移资源包失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_tasks(db):
    """迁移任务数据"""
    if not os.path.exists(TASKS_FILE):
        print("⚠️ 任务文件不存在，跳过迁移")
        return 0
    
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)
            tasks = tasks_data.get("tasks", {})
        
        count = 0
        for task_id, task_data in tasks.items():
            existing = db.query(Task).filter(Task.task_id == task_id).first()
            if existing:
                print(f"⏭️ 任务 {task_id} 已存在，跳过")
                continue
            
            created_at = None
            completed_at = None
            
            if task_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(task_data["created_at"])
                except:
                    pass
            
            if task_data.get("completed_at"):
                try:
                    completed_at = datetime.fromisoformat(task_data["completed_at"])
                except:
                    pass
            
            # 提取任务配置
            task_config = task_data.get("task_config", {})
            if not task_config:
                # 向后兼容：从任务数据构建配置
                task_config = {
                    "git_url": task_data.get("git_url", ""),
                    "image_name": task_data.get("image"),
                    "tag": task_data.get("tag", "latest"),
                    "branch": task_data.get("branch"),
                    "project_type": task_data.get("project_type", "jar"),
                    "template": task_data.get("template"),
                    "should_push": task_data.get("should_push", False),
                    "sub_path": task_data.get("sub_path"),
                    "use_project_dockerfile": task_data.get("use_project_dockerfile", True),
                    "dockerfile_name": task_data.get("dockerfile_name", "Dockerfile"),
                    "pipeline_id": task_data.get("pipeline_id"),
                    "trigger_source": task_data.get("trigger_source", "manual"),
                }
            
            task = Task(
                task_id=task_id,
                task_type=task_data.get("task_type", "build_from_source"),
                image=task_data.get("image"),
                tag=task_data.get("tag"),
                status=task_data.get("status", "pending"),
                created_at=created_at or datetime.now(),
                completed_at=completed_at,
                error=task_data.get("error"),
                task_config=task_config,
                source=task_data.get("source", "手动构建"),
                pipeline_id=task_data.get("pipeline_id"),
                git_url=task_data.get("git_url"),
                branch=task_data.get("branch"),
                project_type=task_data.get("project_type"),
                template=task_data.get("template"),
                should_push=task_data.get("should_push", False),
                sub_path=task_data.get("sub_path"),
                use_project_dockerfile=task_data.get("use_project_dockerfile", True),
                dockerfile_name=task_data.get("dockerfile_name", "Dockerfile"),
                trigger_source=task_data.get("trigger_source", "manual"),
            )
            
            db.add(task)
            count += 1
        
        db.commit()
        print(f"✅ 迁移了 {count} 个任务")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移任务失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_operation_logs(db):
    """迁移操作日志"""
    if not os.path.exists(OPERATION_LOGS_FILE):
        print("⚠️ 操作日志文件不存在，跳过迁移")
        return 0
    
    try:
        count = 0
        with open(OPERATION_LOGS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    log_entry = json.loads(line)
                    timestamp = None
                    if log_entry.get("timestamp"):
                        try:
                            timestamp = datetime.fromisoformat(log_entry["timestamp"])
                        except:
                            pass
                    
                    log = OperationLog(
                        username=log_entry.get("username", "unknown"),
                        action=log_entry.get("action", "unknown"),
                        details=log_entry.get("details", {}),
                        timestamp=timestamp or datetime.now(),
                    )
                    
                    db.add(log)
                    count += 1
                except json.JSONDecodeError:
                    continue
        
        db.commit()
        print(f"✅ 迁移了 {count} 条操作日志")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移操作日志失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_export_tasks(db):
    """迁移导出任务"""
    if not os.path.exists(EXPORT_TASKS_FILE):
        print("⚠️ 导出任务文件不存在，跳过迁移")
        return 0
    
    try:
        with open(EXPORT_TASKS_FILE, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)
            tasks = tasks_data.get("tasks", {})
        
        count = 0
        for task_id, task_data in tasks.items():
            existing = db.query(ExportTask).filter(ExportTask.task_id == task_id).first()
            if existing:
                print(f"⏭️ 导出任务 {task_id} 已存在，跳过")
                continue
            
            created_at = None
            completed_at = None
            
            if task_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(task_data["created_at"])
                except:
                    pass
            
            if task_data.get("completed_at"):
                try:
                    completed_at = datetime.fromisoformat(task_data["completed_at"])
                except:
                    pass
            
            export_task = ExportTask(
                task_id=task_id,
                task_type=task_data.get("task_type", "single"),
                status=task_data.get("status", "pending"),
                images=task_data.get("images", []),
                compose_config=task_data.get("compose_config"),
                output_path=task_data.get("output_path"),
                created_at=created_at or datetime.now(),
                completed_at=completed_at,
                error=task_data.get("error"),
            )
            
            db.add(export_task)
            count += 1
        
        db.commit()
        print(f"✅ 迁移了 {count} 个导出任务")
        return count
    except Exception as e:
        db.rollback()
        print(f"❌ 迁移导出任务失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def migrate_all():
    """执行所有迁移"""
    print("🚀 开始数据迁移...")
    
    # 初始化数据库
    init_db()
    
    # 获取数据库会话
    db = get_db_session()
    
    try:
        total = 0
        total += migrate_pipelines(db)
        total += migrate_git_sources(db)
        total += migrate_hosts(db)
        total += migrate_resource_packages(db)
        total += migrate_tasks(db)
        total += migrate_operation_logs(db)
        total += migrate_export_tasks(db)
        
        print(f"\n✅ 数据迁移完成！共迁移 {total} 条记录")
    except Exception as e:
        print(f"\n❌ 数据迁移失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    import uuid
    migrate_all()

