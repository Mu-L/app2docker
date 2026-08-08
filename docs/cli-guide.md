# App2Docker CLI 与 AI 集成指南

App2Docker CLI 让开发者、CI 和 AI 编码助手通过同一套命令触发项目构建、跟踪日志，并把一次构建保存为可重复运行的流水线。CLI 支持唯一证书、API Key 和 Basic 三种认证方式。

## 安装

在 App2Docker 仓库中执行：

```bash
python -m pip install -e ./cli
app2docker --help
```

## 配置连接

推荐先在本机生成独立 SSH 密钥，并在 App2Docker 的“用户中心 → CLI 认证”上传公钥文件。平台按 SHA-256 指纹保证公钥全局唯一，私钥始终留在本机：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/app2docker_cli
```

上传 `~/.ssh/app2docker_cli.pub` 后复制平台返回的凭证 ID，再配置 CLI。使用私有 CA 时同时提供 CA PEM：

```bash
app2docker config set \
  --server https://app2docker.example.com \
  --credential-id CREDENTIAL_ID \
  --private-key ~/.ssh/app2docker_cli \
  --ca-cert /path/to/company-ca.pem \
  --team-id TEAM_ID

app2docker doctor
```

私钥加密时，通过 `APP2DOCKER_KEY_PASSPHRASE` 提供口令，CLI 不把口令写入配置文件。Windows PowerShell 可将续行符改为反引号，或写成一行。

没有证书时也可以使用 API Key：

```bash
app2docker config set --server https://app2docker.example.com --api-key YOUR_API_KEY
```

或者使用 Basic 凭证（必须配合 HTTPS）：

```bash
app2docker config set --server https://app2docker.example.com \
  --username USERNAME --password PASSWORD
```

默认认证优先级为“证书 → API Key → Basic”，也可用 `--auth-mode certificate|api-key|basic` 固定模式。`config show` 会隐藏 API Key 和密码。

配置优先级为：全局命令行参数 > 环境变量 > 用户配置文件。全局参数需写在子命令之前，例如 `app2docker --team-id TEAM_ID pipeline list`。

| 配置 | 环境变量 |
| --- | --- |
| 服务地址 | `APP2DOCKER_SERVER` |
| 认证模式 | `APP2DOCKER_AUTH_MODE` |
| 证书凭证 ID | `APP2DOCKER_CREDENTIAL_ID` |
| 本地私钥路径 | `APP2DOCKER_PRIVATE_KEY` |
| 私钥口令（不落盘） | `APP2DOCKER_KEY_PASSPHRASE` |
| API Key | `APP2DOCKER_API_KEY` |
| Basic 用户名 | `APP2DOCKER_USERNAME` |
| Basic 密码 | `APP2DOCKER_PASSWORD` |
| 自定义 CA | `APP2DOCKER_CA_CERT` |
| 团队 ID | `APP2DOCKER_TEAM_ID` |

Windows 配置位于 `%APPDATA%\app2docker\config.json`，Linux/macOS 位于 `${XDG_CONFIG_HOME:-~/.config}/app2docker/config.json`。不要提交私钥、API Key、密码或配置文件。

## 触发构建

### 构建已推送的 Git 版本

```bash
app2docker build --source git --profile prod
```

Git 模式要求工作区干净、当前分支已设置 upstream，并且本地 HEAD 与 upstream 一致，确保服务器构建的就是当前版本。仓库、分支和 commit 信息默认从当前 Git 项目读取。

Git 凭证按登录账号隔离。账号为某个仓库保存凭证后，同一 Git 主机和组织路径前缀下的新仓库会自动复用，并为目标仓库创建个人数据源记录；最长的组织路径前缀优先，不会跨账号复用。

### 构建当前本地版本

```bash
app2docker build --source local --profile dev
```

本地模式把 Git 已跟踪文件和未被忽略的未跟踪文件打成临时 ZIP，上传后仍由 App2Docker 原有的 `.app2docker*.yaml`、Dockerfile、多服务和镜像推送逻辑处理。`.git`、被 `.gitignore` 忽略的文件和 Git 仓库外文件不会上传；CLI 会拒绝符号链接，服务端也会拒绝路径穿越和符号链接 ZIP 条目。

常用覆盖参数：

```bash
app2docker build --source git \
  --profile prod \
  --image-name registry.example.com/team/app \
  --tag v1.2.3 \
  --push
```

未指定 `--profile` 时，App2Docker 继续按分支或 Tag 选择 `.app2docker.<profile>.yaml`，并回退到 `.app2docker.yaml`。

## 同时保存为流水线

```bash
app2docker build --source git --profile prod --save-pipeline production-release
```

流水线在任务创建时即与任务绑定，并保存 Git 地址、分支、固定 profile 和显式覆盖项。团队内同名流水线会返回冲突，不会覆盖原配置。本地源码也可使用 `--save-pipeline`，但必须有 origin、干净工作区，并确保 HEAD 已推送到 upstream，保证后续流水线能从 Git 重现。

## 日志、异步执行和任务控制

默认命令持续输出增量日志并在任务结束时返回。`--detach` 立即返回任务 ID；`--json` 输出适合脚本处理的 JSON。按 Ctrl+C 只停止本地等待，不会停止服务端构建。

```bash
app2docker build --source git --detach
app2docker task status TASK_ID
app2docker task logs TASK_ID --follow
app2docker task stop TASK_ID
```

只有明确需要取消远端构建时才执行 `task stop`。

## 流水线

```bash
app2docker pipeline list
app2docker pipeline trigger PIPELINE_ID
app2docker pipeline trigger PIPELINE_ID --branch release/1.x --detach
app2docker pipeline trigger PIPELINE_ID --tag-name v1.2.3
```

`trigger` 与 `run` 等价。CLI 不复制流水线逻辑，而是像经过账号凭证认证的 Webhook 一样调用服务端流水线执行入口，并记录 `trigger_source=cli`。使用 `build --save-pipeline NAME` 时，会保存流水线并立即创建该流水线关联的首次构建任务；以后直接按流水线 ID 触发即可。

## 部署任务

部署同样复用管理端已经保存的部署配置和权限，不在 CLI 中保存主机密钥或重新解释部署 YAML：

```bash
app2docker deploy list
app2docker deploy trigger DEPLOY_CONFIG_ID
app2docker deploy trigger DEPLOY_CONFIG_ID --target production-a --detach
```

默认会跟踪部署日志直到完成。`--target` 可重复传入，只执行部署配置中的指定目标。部署属于外部变更操作，AI 助手只应在用户明确要求时触发。

需要一个命令完成构建成功后部署时：

```bash
app2docker build --source git --profile prod --deploy DEPLOY_CONFIG_ID
```

只有构建状态为 `completed` 才会触发部署；`--deploy-target NAME` 可限定部署目标。自动部署需要等待构建结果，因此不能和 `--detach` 同时使用。

## CI 与 AI 助手

CI 中建议通过密钥管理器注入环境变量，并使用 JSON 输出：

```bash
export APP2DOCKER_SERVER=https://app2docker.example.com
export APP2DOCKER_API_KEY="$APP2DOCKER_CI_KEY"
export APP2DOCKER_CA_CERT=/etc/ssl/company-ca.pem
export APP2DOCKER_TEAM_ID=TEAM_ID
app2docker build --source git --profile prod --json
```

仓库内的 `skills/app2docker-build/SKILL.md` 可供支持 Skills 的 AI 编码助手使用。它会先检查连接和 Git 状态，再触发服务端构建、流水线或用户明确指定的部署配置，并返回任务 ID、最终状态和失败原因。

退出码：`0` 成功，`1` API 或远端构建失败，`2` 本地参数/配置错误，`130` 用户中断日志等待。
