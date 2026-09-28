# CLAUDE.md

Claude Code（claude.ai/code）在此仓库工作时看此文件。

## 仓库

- 自动构建 Docker 镜像。镜像上下文在 `images/`；构建编排在 `tooling/build/`。
- 唯一入口：`uv run python -m tooling.build ...`，见 `tooling/build/cli.py:81`。
- 每个镜像事实来源：`images/<name>/config.yml`，见 `tooling/build/config.py:35`、`tooling/build/config.py:51`。
- 可变构建状态在 `version` 分支 `version.yml`，不在 `main`，见 `tooling/build/state.py:81`、`.github/workflows/build.yml:103`。
- 无独立 lint；主要验证靠 `pytest` + CLI 冒烟，见 `pyproject.toml:20`、`.github/workflows/build.yml:49`。

## 常用命令

```bash
uv sync
uv run pytest tests/build -q
uv run pytest tests/build/test_resolvers.py -q
uv run pytest tests/build/test_cli.py -q
uv run pytest tests/build/test_config.py -q
uv run python -m tooling.build resolve caddy: --repo-root .
uv run python -m tooling.build build --repo-root . --changed-file pyproject.toml --registry-user <registry-user> --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build --repo-root . --changed-file images/tg-signer/config.yml --registry-user <registry-user> --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build tg-signer --repo-root . --registry-user <registry-user> --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build caddy: --repo-root . --registry-user <registry-user> --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build caddy:naive --repo-root . --registry-user <registry-user> --state-file /tmp/containerization-version.yml --force
uv run python -m tooling.build build tg-signer --repo-root . --registry-user <registry-user> --state-file /tmp/containerization-version.yml --push --platform linux/amd64
uv run python -m tooling.build build tg-signer --repo-root . --registry-user <registry-user> --state-file /tmp/containerization-version.yml --force --debug
```

## 架构主链

1. `cli.py` 解析 `resolve` / `build` / `write-summary` 等入口，并统一处理位置参数表达式与 changed-files 选集。
2. `config.py` 扫 `images/*/config.yml`，见 `tooling/build/config.py:35`。
3. `resolvers.py` 解析 `github_tag` / `github_sha` / `alpine_pkg` / `regex_match`，见 `tooling/build/resolvers.py:19`、`tooling/build/resolvers.py:40`、`tooling/build/resolvers.py:65`、`tooling/build/resolvers.py:81`。
4. `state.py` 用 `version.yml` 判定跳过 / 重建，见 `tooling/build/state.py:13`。
5. `docker.py` 生成并执行 `docker build` / `docker buildx build`，见 `tooling/build/docker.py:25`、`tooling/build/docker.py:54`。
6. `template.py` 用 Jinja2 渲染 `Dockerfile.j2`，见 `tooling/build/template.py:11`。
7. CI 在 `.github/workflows/build.yml:23` 串起测试、选目标、推送、回写状态。

## 关键约束

- `null` / 空字符串 / `None` 在命名拼接时忽略；`base` 不再是特殊值，影响 tag 和 state key。
- 默认 target 直接用无 `name` 的 target 表达；`name: base` 非法。
- `github_tag` 去前导 `v`；`github_sha` 把多个仓库最新 commit SHA 拼接后做 sha256，见 `tooling/build/resolvers.py:29`、`tooling/build/resolvers.py:62`。
- 镜像目录有 `Dockerfile.j2` 就自动渲染，无需 `config.yml` 字段；`targets[].template` 可覆盖。渲染产物写临时目录后传给 `docker build -f`，不落仓库，见 `tooling/build/template.py`、`tooling/build/cli.py:161`。
- 模板上下文 `repos` 即该 target 的 `sha.github_sha.repos`；repo 名与构建模块路径不一致的映射写在模板里，不在工具里特判。
- 本地模式走 `docker build --load`；`--push` 才走 `docker buildx build --push`，见 `tooling/build/docker.py:36`。
- `--platform` 只在 push/buildx 模式生效，见 `tooling/build/docker.py:44`。
- 未显式传 `--state-file` 时，会尝试找 `../version/version.yml`；找不到则按无状态处理，见 `tooling/build/state.py:81`、`tooling/build/cli.py:125`。

## CI 事实

- 先 checkout `version`，再 checkout `main`，见 `.github/workflows/build.yml:29`、`.github/workflows/build.yml:35`。
- 执行顺序：`uv sync --frozen` → `uv run pytest tests/build -q` → 直接调用 `tooling.build build --push`。
- 密钥走 Infisical（OIDC），不在 GitHub secrets；见 `.github/workflows/build.yml` 的 `Load secrets from Infisical` 步骤与 README 对应章节。
- 只回写 `version` 分支 `version.yml`。
- rollout 前需要手工把 `version` 分支里的 `version.yml` 重置成 `{}`。
- `TARGETS` 非空时，workflow 会把它拆成 `build` 的位置参数；否则 push 事件走 changed-files 选择逻辑。
- Build 触发路径：`images/**`、`tooling/build/**`、`tests/build/**`、`pyproject.toml`、`uv.lock`；`.github/**` 被排除，见 `.github/workflows/build.yml:7`。

## 修改时注意

- 文档若与当前实现冲突，以代码和 `tests/build/` 为准。
- 新增镜像必须有 `images/<name>/config.yml`，否则 CLI 不会发现，见 `tooling/build/config.py:35`。
- 增删镜像同步更新 `tests/build/test_repository_layout.py:4`。
- 改 `tooling/build/**`、`tests/build/**`、`pyproject.toml`、`uv.lock` 默认影响全部镜像，见 `tooling/build/change_detection.py:20`、`tooling/build/change_detection.py:22`、`tooling/build/change_detection.py:24`。
- 镜像目录内 README 可能是单镜像约束，别误当全仓库规则。
