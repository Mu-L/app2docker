# CLI reference

Install from an app2docker checkout:

```bash
python -m pip install -e ./cli
```

Configuration precedence is command-line flags, then `APP2DOCKER_*` environment variables, then the user config file. Global connection flags must appear before the command. Authentication auto-selects certificate, then API Key, then Basic.

```bash
app2docker config set --server https://build.example.com \
  --credential-id CREDENTIAL_ID --private-key ~/.ssh/app2docker_cli \
  --ca-cert /path/company-ca.pem --team-id TEAM_ID
```

Upload the matching `.pub` public key under the logged-in App2Docker account. The platform rejects a fingerprint already bound to any credential. Keep the private key local; encrypted keys read the passphrase only from `APP2DOCKER_KEY_PASSPHRASE`.

Alternatives are `--api-key KEY` or `--username USER --password PASSWORD`. Use `--auth-mode certificate|api-key|basic` to force one. Relevant environment variables are `APP2DOCKER_SERVER`, `APP2DOCKER_AUTH_MODE`, `APP2DOCKER_CREDENTIAL_ID`, `APP2DOCKER_PRIVATE_KEY`, `APP2DOCKER_API_KEY`, `APP2DOCKER_USERNAME`, `APP2DOCKER_PASSWORD`, `APP2DOCKER_CA_CERT`, and `APP2DOCKER_TEAM_ID`. The config file is `%APPDATA%\app2docker\config.json` on Windows or `${XDG_CONFIG_HOME:-~/.config}/app2docker/config.json` on Unix. `config show` masks API Keys and passwords.

## Builds

`build [PROJECT]` accepts `--source git|local`, `--git-url`, `--branch`, `--tag-name`, `--profile`, `--project-type`, `--template`, `--image-name`, `--tag`, `--push|--no-push`, `--save-pipeline NAME`, `--pipeline-description`, `--deploy CONFIG_ID`, repeated `--deploy-target NAME`, `--detach`, and `--json`.

Git source requires a clean checkout whose HEAD equals its upstream. Local source builds tracked files plus unignored untracked files and permits dirty content. Saving a pipeline from local source additionally requires an origin, clean checkout, upstream, and matching HEAD because future runs use Git.

Without `--detach`, the CLI polls status and prints new logs until completion. With `--json`, it suppresses streaming logs and prints the final task object. Ctrl+C stops only local waiting.

## Tasks and pipelines

```bash
app2docker task status TASK_ID
app2docker task logs TASK_ID
app2docker task logs TASK_ID --follow
app2docker task stop TASK_ID
app2docker pipeline list [--json]
app2docker pipeline trigger PIPELINE_ID [--branch BRANCH|--tag-name TAG] [--detach] [--json]
app2docker deploy list [--json]
app2docker deploy trigger CONFIG_ID [--target NAME] [--detach] [--json]
```

跟踪类命令支持 `--retries COUNT`、`--poll-interval SECONDS` 和
`--timeout SECONDS`。日志按服务端日志 ID 增量读取；临时连接错误会退避重试，
超时或 Ctrl+C 仅停止本地等待。JSON 模式把实时日志写入 stderr，最终 JSON 写入 stdout。

`run` and `trigger` are aliases for pipeline and deployment configurations. They call the same authenticated server-side execution paths used by the web UI and record `trigger_source=cli`. A build with `--save-pipeline` creates the pipeline and starts its first linked build. `build --deploy CONFIG_ID` triggers the saved deployment configuration only after the build completes successfully; it cannot be combined with `--detach`.

Exit status is 0 for success, 1 for an API or remote build failure, 2 for local usage/configuration errors, and 130 when log following is interrupted.
