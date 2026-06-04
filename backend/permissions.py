"""
Permission definitions.
"""

# Menu permissions
MENU_DASHBOARD = "menu.dashboard"
MENU_BUILD = "menu.build"
MENU_EXPORT = "menu.export"
MENU_MIGRATION = "menu.migration"
MENU_TEAM_REQUESTS = "menu.team-requests"
MENU_TASKS = "menu.tasks"
MENU_PIPELINE = "menu.pipeline"
MENU_DATASOURCE = "menu.datasource"
MENU_REGISTRY = "menu.registry"
MENU_TEMPLATE = "menu.template"
MENU_RESOURCE_PACKAGE = "menu.resource-package"
MENU_HOST = "menu.host"
MENU_DOCKER = "menu.docker"
MENU_DEPLOY = "menu.deploy"
MENU_USERS = "menu.users"

ALL_MENU_PERMISSIONS = [
    MENU_DASHBOARD,
    MENU_BUILD,
    MENU_EXPORT,
    MENU_MIGRATION,
    MENU_TEAM_REQUESTS,
    MENU_TASKS,
    MENU_PIPELINE,
    MENU_DATASOURCE,
    MENU_REGISTRY,
    MENU_TEMPLATE,
    MENU_RESOURCE_PACKAGE,
    MENU_HOST,
    MENU_DOCKER,
    MENU_DEPLOY,
    MENU_USERS,
]

PERMISSION_NAMES = {
    MENU_DASHBOARD: "仪表盘",
    MENU_BUILD: "镜像构建",
    MENU_EXPORT: "导出镜像",
    MENU_MIGRATION: "镜像迁移",
    MENU_TEAM_REQUESTS: "团队申请",
    MENU_TASKS: "任务管理",
    MENU_PIPELINE: "流水线",
    MENU_DATASOURCE: "数据源",
    MENU_REGISTRY: "镜像仓库",
    MENU_TEMPLATE: "模板管理",
    MENU_RESOURCE_PACKAGE: "资源包",
    MENU_HOST: "主机管理",
    MENU_DOCKER: "Docker管理",
    MENU_DEPLOY: "部署管理",
    MENU_USERS: "用户管理",
}
