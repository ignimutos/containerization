# CLAUDE.md

Claude Code（claude.ai/code）在此仓库工作时看此文件。

## 仓库

- 自动构建 Docker 镜像。镜像上下文在 `images/`；构建编排在 `tooling/build/`。
- 唯一入口：`uv run python -m tooling.build ...`，见 `tooling/build/cli.py:81`。
- 每个镜像事实来源：`images/<name>/config.yml`，见 `tooling/build/config.py:35`、`tooling/build/config.py:51`。
- 可变构建状态在 `version` 分支 `version.yml`, 不在 `main`, 见 `tooling/build/state.py:81`、`.github/workflows/build.yml:59`、`.github/workflows/build.yml:227`。
- 无独立 lint; 主要验证靠 `pytest` + CLI 冒烟, 见 `pyproject.toml:20`、`.github/workflows/build.yml:127`。

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
7. CI 在 `.github/workflows/build.yml` 的 `build` job (`:49`) 串起测试、选目标、推送、回写状态。

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

- 先 checkout `version`, 再 checkout `main`, 见 `.github/workflows/build.yml:59`、`.github/workflows/build.yml:78`。
- 执行顺序: `uv sync --frozen` → `uv run pytest tests/build -q` → 直接调用 `tooling.build build --push` → `sync-readmes` → 单条 Telegram 通知 → `write-summary` → 回写 `version`。
- `build` 默认带 `--ignore-failure` (`vars.IGNORE_FAILURE`, 默认 `true`) : 单个 target 失败不中止其余 target, 但有失败时退出码仍非 0。见 `tooling/build/cli.py` 的 `_run_builds`。
- Telegram 通知只有一个 `if: always()` 步骤, `STATUS` 来自 `${{ job.status }}`; 报告文件缺失时退化为状态加 run 链接, 凭据为空时跳过。`sync-readmes` 与回写 `version` 同样是 `always()`, 已成功 target 的状态照常落盘。
- 凭据默认走 Infisical（OIDC）：配置项是仓库 Variables，经 job 级 `env:` 读取，`project-id` 等由 `Inject secrets from Infisical` 步骤消费；该步骤在 identity/project 为空时跳过，此时（或需要覆盖时）由紧随其后的 `Overlay repo secrets` 步骤从 repo secrets 注入，非空 repo secret 覆盖 Infisical 值。见 `.github/workflows/build.yml` 与 README 对应章节。
- 只回写 `version` 分支 `version.yml`; 失败 target 不写入, 下轮自动重试。
- `version` 分支缺失时 CI 自动创建并写入初始 `{}`；分支已存在但残留旧状态时仍需手工把 `version.yml` 重置成 `{}`。
- `TARGETS` 非空时，workflow 会把它拆成 `build` 的位置参数；否则 push 事件走 changed-files 选择逻辑。
- Build 触发路径: `images/**`、`tooling/build/**`、`tests/build/**`、`pyproject.toml`、`uv.lock`; `.github/**` 被排除, 见 `.github/workflows/build.yml:20`。

## 修改时注意

- 文档若与当前实现冲突，以代码和 `tests/build/` 为准。
- 新增镜像必须有 `images/<name>/config.yml`，否则 CLI 不会发现，见 `tooling/build/config.py:35`。
- 增删镜像同步更新 `tests/build/test_repository_layout.py:4`。
- 改 `tooling/build/**`、`tests/build/**`、`pyproject.toml`、`uv.lock` 默认影响全部镜像，见 `tooling/build/change_detection.py:20`、`tooling/build/change_detection.py:22`、`tooling/build/change_detection.py:24`。
- 镜像目录内 README 可能是单镜像约束，别误当全仓库规则。
