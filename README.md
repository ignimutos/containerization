# Containerization

Auto-build Docker images for personal usage.

## 目录结构

- `images/`：各镜像的构建上下文。每个镜像目录包含自己的 `config.yml`、构建上下文文件和附属脚本；Dockerfile 可以是普通 `Dockerfile`，也可以是待渲染的 `Dockerfile.j2`（见下）。
- `tooling/build/`：Python 构建工具。负责解析配置、解析上游版本、决定是否重建、组装 Docker 命令。
- `tests/build/`：构建工具的本地测试。
- `.github/workflows/build.yml`：CI 入口。先跑 Python 测试，再按改动范围选择目标镜像构建。

## 环境准备

仓库现在使用 `uv` 管理本地 Python 环境。

```bash
uv sync
```

需要本地安装：

- Docker / buildx
- `uv`

如果要让 resolver 访问 GitHub API，设置有效的 `GITHUB_TOKEN`：

```bash
export GITHUB_TOKEN='<token>'
```

## 本地测试

跑全部构建测试：

```bash
uv run pytest tests/build -q
```

跑单个测试文件：

```bash
uv run pytest tests/build/test_resolvers.py -q
uv run pytest tests/build/test_cli.py -q
uv run pytest tests/build/test_config.py -q
```

## 本地命令示例

解析单个镜像默认 target 当前版本：

```bash
uv run python -m tooling.build resolve caddy: --repo-root .
```

根据改动文件直接选择并构建：

```bash
uv run python -m tooling.build build --repo-root . --changed-file pyproject.toml --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build --repo-root . --changed-file images/tg-signer/config.yml --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
```

本地构建单个镜像：

```bash
uv run python -m tooling.build build tg-signer --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
```

批量构建多个镜像：

```bash
uv run python -m tooling.build build caddy tg-signer --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
```

只构建某个镜像的默认 target 或单个 target 变体时，直接用统一位置参数语法：

```bash
uv run python -m tooling.build build caddy: --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build caddy:naive --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build +all -caddy:naive --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --force
```

推送模式（通常给 CI 用）：

```bash
uv run python -m tooling.build build tg-signer --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --push --platform linux/amd64 --force
```

## 构建日志

默认模式会隐藏 Docker 普通构建输出，只保留流程日志和失败信息：

- 成功时打印 `start` / `success`
- 失败时打印 `failed`、执行命令和 Docker 错误输出
- 本地 `docker build --load` 不会额外显示 `platform`
- `--push` / buildx 模式会在流程日志里显示 `platform`

如果需要排障，可以加 `--debug` 透传 Docker 原始输出：

```bash
uv run python -m tooling.build build tg-signer --repo-root . --registry-user ignimutos --state-file /tmp/containerization-version.yml --force --debug
```

## `config.yml` 格式

每个镜像在 `images/<name>/config.yml` 下维护自己的构建配置。常见 resolver：

- `github_tag`
- `github_sha`
- `alpine_pkg`
- `regex_match`

示例：

```yaml
version:
  github_tag:
    repo: caddyserver/caddy
targets:
  - target: caddy-base
    sha:
      github_sha:
        repos:
          - caddy-dns/cloudflare
          - caddyserver/transform-encoder
          - greenpau/caddy-trace
  - name: rr
    target: caddy-rr
    sha:
      github_sha:
        repos:
          - caddy-dns/cloudflare
          - caddyserver/transform-encoder
          - greenpau/caddy-trace
          - caddyserver/replace-response
  - name: naive
    target: caddy-naive
    sha:
      github_sha:
        repos:
          - caddy-dns/cloudflare
          - caddyserver/transform-encoder
          - greenpau/caddy-trace
          - klzgrad/naiveproxy
```

默认 target 直接用无 `name` 的 target 表达；`base` 不再是特殊保留值。

## Dockerfile 模板

镜像目录里放 `Dockerfile.j2` 即自动启用模板渲染，不需要在 `config.yml` 写任何字段；也可以用 `targets[].template` 指定别的模板文件。

模板渲染出的 Dockerfile 不会落进仓库，而是写到临时目录后传给 `docker build -f`，构建上下文保持干净。

上下文变量：

- `repos`：该 target 的 `sha.github_sha.repos` 原列表，用来渲染构建命令，避免在 `config.yml` 与 Dockerfile 里各写一遍。
- `version`：该 target 解析出的版本。

`repos` 里的 repo 名不一定等于构建工具期望的模块路径（例如 `klzgrad/naiveproxy` 实际要构建成 `github.com/caddyserver/forwardproxy=github.com/klzgrad/forwardproxy@naive`）。这种无法从 `config.yml` 推导的映射写在模板里，不要在工具里做特判。`images/caddy/Dockerfile.j2` 是可用示例。

## CI / version 分支

GitHub Actions 会在这些路径变化时触发：

- `images/**`
- `tooling/build/**`
- `tests/build/**`
- `pyproject.toml`
- `uv.lock`

CI 流程：

1. checkout `version` 分支到旁边目录
2. checkout `main`
3. 通过 Infisical 拉取密钥（见下）
4. `uv sync --frozen`
5. `uv run pytest tests/build -q`
6. 根据手工 targets 或 changed files 直接决定本次应构建的 image/targets
7. 调用 `uv run python -m tooling.build build ... --push`
8. 只把构建状态写回 `version` 分支

`version` 分支保存可变构建状态；`main` 不保存这类状态文件。切到这套新语义前，需要先手工把 `version` 分支里的 `version.yml` 重置成 `{}`，避免旧状态格式残留。

### CI 密钥：Infisical

CI 用到的真实凭据（Docker Hub 用户名/密码、Telegram bot token/chat id）存放在 Infisical，**不再使用 GitHub secrets**。workflow 通过 `Infisical/secrets-action` 走 OIDC 鉴权拉取，短时 token、仓库内零长时凭据。

需要配置：

- **Infisical 侧**（一次）：创建一个 OIDC Machine Identity，绑定 `repo:ignimutos/Containerization`（Audience 用所有者 URL，Subject 用 `repo:ignimutos/*:ref` 可覆盖同组织的多个仓库），并赋予项目读取权限。
- **Infisical 项目**：在对应环境里建 4 个 secret，名字必须与 workflow 引用一致：
  - `DOCKERHUB_USER` — Docker Hub 用户名
  - `DOCKERHUB_TOKEN` — Docker Hub 访问令牌（Access Token，不是登录密码）
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
- **GitHub vars**（非敏感，配成仓库 vars）：
  - `INFISICAL_IDENTITY_ID` — Machine Identity 的 identity id
  - `INFISICAL_PROJECT_SLUG` — 项目 slug
  - `INFISICAL_ENV_SLUG` — 环境 slug（如 `prod`）
  - 可选：`INFISICAL_DOMAIN`（默认 `https://app.infisical.com`）、`INFISICAL_SECRET_PATH`（默认 `/`）、`INFISICAL_RECURSIVE`（默认 `true`，递归拉取子文件夹）
