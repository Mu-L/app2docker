# 镜像构建触发指南

本文介绍 App2Docker 的三种构建触发方式：

1. **Web 界面 - 临时 Git**：无需预先创建数据源，输入地址即可构建
2. **API - 配置文件触发**：通过 `POST /api/build-with-config`，配合仓库根目录的 `.app2docker.yaml`
3. **API - 常规 Git 构建**：`POST /api/build-from-source`（含临时认证参数）

---

## 认证说明

所有 API 请求均需携带认证信息，支持以下两种方式：

| 方式 | 请求头 | 说明 |
|------|--------|------|
| JWT Token | `Authorization: Bearer <token>` | 登录后获取，有效期 24h |
| App Key | `Authorization: Bearer <app_key>` | 用户管理 → APP Key，适合 CI/CD |

```bash
# 登录获取 Token
curl -X POST http://<host>:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
```

---

## 方式一：Web 界面 - 临时 Git

适用于一次性构建，无需在「数据源」中预先登记仓库。

1. 进入 **镜像构建** 页面
2. 步骤 1 选择 **临时 Git**
3. 填写：
   - **Git 仓库地址**（必填）
   - **用户名 / 密码或 Token**（私有仓库选填）
   - **分支/标签**（选填，不填则使用仓库默认分支）
4. 按向导完成模板、镜像名等配置后提交

> 临时认证信息仅用于本次构建，不会写入数据库。

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
| `team_id` | 否 | 团队 ID（多团队用户必填；Web 端由拦截器自动附加） |

> 仅显式传入的参数会覆盖配置文件；未传的字段以配置文件为准。

### curl 示例

```bash
HOST=http://localhost:8000
TOKEN=<your_jwt_or_app_key>
```

**场景 A：只给 Git 地址**（默认分支 → profile=default → `.app2docker.yaml`）

```bash
curl -X POST "$HOST/api/build-with-config?team_id=<team_id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git"}'
```

**场景 A：指定分支**（profile 自动=develop → `.app2docker-develop.yaml`）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "branch": "develop"}'
```

**场景 B：分支与 profile 解耦**（clone main，使用 prod 配置）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "branch": "main", "profile": "prod"}'
```

**场景 C：tag 触发**（checkout v1.0 → profile 自动=v1.0）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "tag_name": "v1.0"}'
```

**场景 D：tag + 显式 profile**（checkout v1.0，使用 release 配置）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "tag_name": "v1.0", "profile": "release"}'
```

**场景 E：只指定 profile**（默认分支 + prod 配置；若配置中有 `git.branch` 则用之）

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "profile": "prod"}'
```

**覆盖配置文件参数**

```bash
curl -X POST "$HOST/api/build-with-config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"git_url": "https://github.com/user/repo.git", "branch": "develop", "push": false, "tag": "custom-tag"}'
```

**私有仓库**

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

### 临时 Git 认证参数

配合 Web「临时 Git」或脚本构建私有仓库时，可附加：

| 参数 | 说明 |
|------|------|
| `temp_git_username` | Git 用户名 |
| `temp_git_password` | Git 密码或 Access Token |

```bash
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
```

认证优先级：**已注册数据源** > **临时认证参数** > **全局 Git 配置**（`data/config.yml`）。

---

## 触发方式对比

| 方式 | 适用场景 | 配置来源 | 是否需要预建数据源 |
|------|----------|----------|-------------------|
| Web 临时 Git | 手动一次性构建 | 界面填写 | 否 |
| `/api/build-with-config` | CI/CD、自动化 | 仓库 `.app2docker.yaml` | 否 |
| `/api/build-from-source` | 脚本、完整参数控制 | 请求体 | 否（可用 `source_id` 引用数据源） |
| 流水线 Webhook | Push 自动触发 | 平台流水线配置 | 是（或填 git_url） |

---

## 常见问题

**Q：仓库没有配置文件，能用 `/api/build-with-config` 吗？**

可以，但需在请求中显式传入 `template`、`image_name` 等构建参数，否则会报错提示缺少配置。

**Q：`profile` 和 `branch` 有什么区别？**

- `branch` / `tag_name`：决定检出哪份代码
- `profile`：决定用哪份构建配置（`.app2docker-{profile}.yaml`）
- 两者可解耦，例如 `branch=main, profile=prod`

**Q：临时 Git 密码会保存吗？**

不会。`temp_git_password` / `git_password` 仅用于本次 clone，不写入数据库。
