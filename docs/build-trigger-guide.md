# 镜像构建触发指南

本文介绍 App2Docker 的构建触发方式：

1. **Web 界面 - 镜像构建**：在构建向导中选择或新建 Git 数据源后构建
2. **API - 配置文件触发**：通过 `POST /api/build-with-config`，配合仓库根目录的 `.app2docker.yaml`
3. **API - 常规 Git 构建**：`POST /api/build-from-source`（支持 `source_id` 或临时认证参数）

---

## 认证说明

所有 API 请求均需携带认证信息，支持以下两种方式：

| 方式 | 请求头 | 说明 |
|------|--------|------|
| JWT Token | `Authorization: Bearer <token>` | 登录后获取，有效期 24h |
| App Key | `Authorization: Bearer <app_key>` | 用户管理 → APP Key，适合 CI/CD |

**Token / App Key 即代表调用者身份**：后端据此定位用户，并自动匹配该用户的个人 Git 数据源（按 `git_url`）。因此 curl 典型用法是 **只传 `git_url`**，无需每次带 `team_id`（仅当用户属于多个团队时才需要显式指定）。

```bash
# 登录获取 Token
curl -X POST http://<host>:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
```

### API 凭据策略（curl / CI）

| 场景 | 请求体 | 行为 |
|------|--------|------|
| 日常触发 | 仅 `git_url` | 使用 Token 对应用户已保存的**个人**数据源凭据 |
| 首次 / 轮换 Token | `git_url` + `git_username` / `git_password`（或 `temp_git_*`） | 构建成功后凭据写入个人数据源，后续可只传 URL |
| 显式指定 | `source_id` | 使用指定数据源（需有 `run` 权限） |

> `temp_git_password` / `git_password` 不会出现在日志中；写入个人数据源后加密存储，其他团队成员不可见。

---

## 方式一：Web 界面 - 镜像构建

适用于在平台内手动发起构建。

1. 进入 **镜像构建** 页面
2. 步骤 1 选择 **Git 数据源**
3. 从下拉列表选择已有数据源，或点击 **新建数据源**：
   - 填写 **数据源名称**、**Git 仓库地址**（必填）
   - 私有仓库可填写 **用户名 / 密码或 Token**
   - 点击 **验证并保存**，系统自动创建数据源
4. 选择 **分支/标签** 后，按向导完成模板、镜像名等配置并提交

新建的数据源会同步出现在 **数据源管理** 页面，后续构建可直接复用。

### 团队 / 个人数据源

| 类型 | 创建方式 | 可见范围 | 凭据 |
|------|----------|----------|------|
| **个人** | 构建页「新建数据源」（固定个人） | 仅创建者 + 团队管理员 | 各自 Token，互不可见 |
| **团队** | 数据源管理页（管理员） | `private`：授权成员；`team_public`：全团可见 | 团队共用 Token |

- 构建页新建始终为 **个人** 数据源；同一团队、同一用户、同一 URL 不会重复创建，会 **更新凭据**。
- 管理员可在 **数据源管理** 创建 **团队** 数据源，并设置 **团内公开** 或 **成员授权**。
- 列表与构建下拉会显示 **个人 / 团队 / 团内公开** 标识及创建者名称。

---

## 方式二：配置文件触发（推荐 CI/CD）

在 Git 仓库根目录放置 `.app2docker.yaml` 配置文件，通过一条 curl 命令触发构建。

### 核心概念：分支/tag 与 Profile 分离

| 维度 | 作用 | 参数 |
|------|------|------|
| 代码检出 | 决定 clone 哪个分支/tag | `branch` / `tag_name` |
| 构建配置 | 决定使用哪份构建配置 | `profile` → `.app2docker-{profile}.yaml` |

**Profile 推导规则**（未显式指定 `profile` 时）：

```
1. 指定了 tag_name  → profile = tag_name
2. 否则指定了 branch → profile = branch
3. 否则             → profile = default（查找 .app2docker.yaml）
```

**配置文件匹配**：

```
1. 查找 .app2docker-{profile}.yaml
2. 未找到则回退 .app2docker.yaml
3. 都不存在则使用请求中的手动参数（需传 template 等）
```

### 文件命名

```
.app2docker.yaml              # default profile（兜底）
.app2docker-main.yaml         # profile=main
.app2docker-develop.yaml      # profile=develop
.app2docker-prod.yaml         # profile=prod
.app2docker-v1.0.yaml         # profile=v1.0（tag 名）
```

### 配置文件示例

`.app2docker-prod.yaml`：

```yaml
version: "1.0"

# 可选：仅当请求未指定 branch/tag 时，用于确定检出分支
git:
  branch: main

build:
  project_type: jar
  template: dragonwell21-upload
  dockerfile_name: Dockerfile
  use_project_dockerfile: true
  sub_path: null

image:
  name: myapp
  prefix: registry.cn-shanghai.aliyuncs.com/myrepo
  tag: latest          # 支持变量：{branch} {profile} {date} {commit}
  push: true

template_params:
  JVM_OPTS: "-Xms1g -Xmx2g"
  ENV: "production"
```

`.app2docker-develop.yaml`：

```yaml
version: "1.0"

build:
  project_type: jar
  template: dragonwell21-upload

image:
  name: myapp-dev
  prefix: registry.cn-shanghai.aliyuncs.com/myrepo
  tag: dev
  push: true

template_params:
  JVM_OPTS: "-Xms256m -Xmx512m"
  ENV: "development"
```

**镜像 tag 支持的变量占位符**：

| 变量 | 说明 | 示例 |
|------|------|------|
| `{branch}` | 实际检出的分支 | `main` |
| `{profile}` | 使用的 profile 名 | `prod` |
| `{date}` | 当前日期 YYYYMMDD | `20260606` |
| `{commit}` | Git commit SHA（前 7 位） | `a1b2c3d` |
| `{timestamp}` | 当前时间戳 | `1699999999` |

### API：`POST /api/build-with-config`

**请求参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `git_url` | 是 | Git 仓库地址 |
| `branch` | 否 | 检出分支 |
| `tag_name` | 否 | 检出 Git tag（优先于 branch） |
| `profile` | 否 | 显式指定 profile；未指定则从 tag/branch 推导 |
| `git_username` | 否 | 私有仓库用户名 |
| `git_password` | 否 | 私有仓库密码或 Token |
| `project_type` | 否 | 覆盖配置文件中的项目类型 |
| `template` | 否 | 覆盖配置文件中的模板 |
| `image_name` | 否 | 覆盖配置文件中的镜像名 |
| `tag` | 否 | 覆盖配置文件中的镜像 tag |
| `push` | 否 | 覆盖配置文件中的 push 设置 |
| `team_id` | 否 | 团队 ID；**单团队用户可省略**（由 Token 定位用户后自动选用唯一团队）；多团队用户必填 |

> 仅显式传入的参数会覆盖配置文件；未传的字段以配置文件为准。

### curl 示例

```bash
HOST=http://localhost:8000
TOKEN=<your_jwt_or_app_key>
# TEAM_ID 仅多团队用户需要：-d '{"team_id":"<id>", "git_url":"..."}'
```

**最简用法**（Token 定位用户 + 已保存凭据；默认分支 → `.app2docker.yaml`）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git"}'
```

**指定分支**（profile 自动=develop → `.app2docker-develop.yaml`）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "branch": "develop"}'
```

**分支与 profile 解耦**（clone main，使用 prod 配置）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "branch": "main", "profile": "prod"}'
```

**tag 触发**（checkout v1.0 → profile 自动=v1.0）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "tag_name": "v1.0"}'
```

**私有仓库：首次带凭据**（写入个人数据源，之后可只传 `git_url`）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "git_url": "https://github.com/user/private-repo.git",
    "git_username": "user",
    "git_password": "ghp_xxxx",
    "profile": "prod"
  }'
```

**响应示例**：

```json
{
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "branch": "main",
  "tag_name": null,
  "profile": "prod",
  "config_source": ".app2docker-prod.yaml",
  "message": "构建任务已启动"
}
```

构建进度请在 **任务管理** 中查看。

---

## 方式三：常规 Git 构建 API

适用于 Web 界面或脚本直接传入完整构建参数，不依赖仓库内的配置文件。

### API：`POST /api/build-from-source`

```bash
curl -X POST "$HOST/api/build-from-source" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "git_url": "https://github.com/user/repo.git",
    "branch": "main",
    "project_type": "jar",
    "template": "dragonwell21-upload",
    "imagename": "myapp/demo",
    "tag": "latest",
    "push": "off",
    "use_project_dockerfile": true,
    "dockerfile_name": "Dockerfile"
  }'
```

### API 临时认证参数（首次 / 轮换 Token）

私有仓库**首次**通过 API 构建时，可附加认证参数；平台会按 Token 对应用户写入**个人**数据源，之后同一 `git_url` 只需 Token + URL：

| 参数 | 说明 |
|------|------|
| `temp_git_username` | Git 用户名 |
| `temp_git_password` | Git 密码或 Access Token |

```bash
# 首次：带凭据
curl -X POST "$HOST/api/build-from-source" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "git_url": "https://github.com/user/private-repo.git",
    "temp_git_username": "user",
    "temp_git_password": "ghp_xxxx",
    "branch": "main",
    "project_type": "jar",
    "template": "dragonwell21-upload",
    "imagename": "myapp/demo",
    "tag": "latest",
    "push": "on"
  }'

# 后续：仅 URL（自动使用已保存的个人凭据）
curl -X POST "$HOST/api/build-from-source" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "git_url": "https://github.com/user/private-repo.git",
    "branch": "main",
    "project_type": "jar",
    "template": "dragonwell21-upload",
    "imagename": "myapp/demo",
    "tag": "latest",
    "push": "on"
  }'
```

认证优先级：**显式 `source_id`** > **Token 对应用户的个人数据源（同 `git_url`）** > **本次请求的临时凭据（首次写入个人源）** > **全局 Git 配置**（`data/config.yml`）。

---

## 触发方式对比

| 方式 | 适用场景 | 配置来源 | 是否需要预建数据源 |
|------|----------|----------|-------------------|
| Web 镜像构建 | 手动构建 | 界面选择/新建数据源 | 可在构建流程中新建 |
| `/api/build-with-config` | CI/CD、自动化 | 仓库 `.app2docker.yaml` | 否 |
| `/api/build-from-source` | 脚本、完整参数控制 | 请求体 | 否（可用 `source_id` 或临时认证） |
| 流水线 Webhook / 手动 / Cron | 自动构建 | 仓库 `.app2docker-<分支或tag>.yaml`，回退 `.app2docker.yaml`，都不存在时使用平台流水线配置 | 是（或填 git_url） |

### 流水线自动识别配置

流水线在克隆代码后自动检测配置，不需要额外开关：

1. 分支构建优先查找 `.app2docker-<branch>.yaml`。
2. Tag 构建优先查找 `.app2docker-<tag>.yaml`。
3. 未找到专用配置时回退 `.app2docker.yaml`。
4. 仓库中没有配置文件时继续使用平台中保存的流水线配置。

配置存在时，项目类型、Dockerfile/模板、镜像、Tag、推送和多服务参数以仓库配置为准。资源包仍使用平台流水线配置，不从仓库配置自动加载。

项目使用自带 Dockerfile 时，可以通过 `build.build_args` 传递构建参数：

```yaml
build:
  use_project_dockerfile: true
  dockerfile_name: Dockerfile
  build_args:
    BUILD_SCRIPT: "build:{profile}"
```

`build_args` 会传递给 `docker buildx build --build-arg`，其字符串值支持 `{branch}`、`{profile}`、`{commit}`、`{date}` 和 `{timestamp}` 变量。

---

## 常见问题

**Q：仓库没有配置文件，能用 `/api/build-with-config` 吗？**

可以，但需在请求中显式传入 `template`、`image_name` 等构建参数，否则会报错提示缺少配置。

**Q：`profile` 和 `branch` 有什么区别？**

- `branch` / `tag_name`：决定检出哪份代码
- `profile`：决定用哪份构建配置（`.app2docker-{profile}.yaml`）
- 两者可解耦，例如 `branch=main, profile=prod`

**Q：curl 需要每次传 `team_id` 吗？**

不需要。`Authorization` 中的 Token / App Key 已定位用户；若该用户只属于一个团队，后端自动选用该团队。仅当用户加入多个团队时，需在 body 中传 `team_id`。

**Q：curl 需要每次传 Git 凭据吗？**

不需要。首次（或 Token 轮换）传 `git_username`/`git_password` 或 `temp_git_*` 后，凭据会写入**当前用户**的个人数据源；后续同一 `git_url` 只传 URL 即可。

**Q：多人使用同一 Git URL 但凭据不同怎么办？**

每人使用自己的 Token / App Key 调用 API，凭据分别存入各自的个人数据源，互不可见。团队管理员也可在数据源管理创建 **团队** 数据源并 **团内公开** 或 **成员授权**。
