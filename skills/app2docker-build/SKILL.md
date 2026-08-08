---
name: app2docker-build
description: Trigger, follow, and troubleshoot app2docker builds, saved pipelines, and deployment configurations with the app2docker CLI. Use when a user asks an AI agent to build or publish a Git/local project, save or trigger a pipeline, trigger a deployment task, chain a successful build to deployment, inspect logs/status, or stop a task.
---

# App2Docker Build

Use the repository's `app2docker` CLI as an authenticated, webhook-like trigger for server-side build, pipeline, and deployment configurations while keeping credentials out of prompts and output.

## Workflow

1. Check that the CLI is installed with `app2docker --help`. If it is not, install this repository's package with `python -m pip install -e ./cli`.
2. Run `app2docker doctor`. If authentication is missing, prefer an account-bound unique certificate (`credential_id` plus local private key); otherwise use an API Key or HTTPS Basic credentials. Never upload, print, or commit a private key, API Key, or password.
3. Inspect `git status --short` and the available `.app2docker*.yaml` files.
4. Choose the source:
   - Use `app2docker build --source git` for a clean, pushed branch. This is the reproducible default.
   - Use `app2docker build --source local` when the user explicitly wants to build current unpublished or uncommitted files. The CLI uploads tracked and unignored untracked files only.
5. Pass `--profile NAME` when the requested environment maps to `.app2docker.NAME.yaml`. Otherwise allow app2docker to derive it from branch or tag.
6. Add `--save-pipeline NAME` only when the user asks for a reusable pipeline. Explain that the name must be unique in the team and a local-source saved pipeline requires a clean, pushed upstream.
7. Use `app2docker pipeline trigger PIPELINE_ID` to trigger an existing saved pipeline. A build with `--save-pipeline` already creates and triggers its first linked task.
8. Use `app2docker deploy trigger CONFIG_ID` only when the user explicitly asks to deploy. Use `build --deploy CONFIG_ID` only when they explicitly request build-then-deploy; it waits for a successful build first.
9. Let commands follow logs unless the user requests asynchronous execution; then use `--detach` and report the task ID.
10. Report the final build/deployment status, task IDs, pipeline ID if created, and actionable failures.

## Common Commands

```bash
app2docker doctor
app2docker build --source git --profile prod
app2docker build --source local --profile dev
app2docker build --source git --save-pipeline release --detach
app2docker task status TASK_ID
app2docker task logs TASK_ID --follow
app2docker pipeline list
app2docker pipeline trigger PIPELINE_ID
app2docker deploy list
app2docker deploy trigger CONFIG_ID
app2docker build --source git --deploy CONFIG_ID
```

Do not trigger deployment or run `app2docker task stop` without explicit user intent. Pressing Ctrl+C while following output detaches locally and leaves the remote task running.

Read [references/cli.md](references/cli.md) for configuration precedence, command options, automation behavior, and exit codes.
