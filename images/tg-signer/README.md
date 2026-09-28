# tg-signer

为 [tg-signer](https://github.com/amchii/tg-signer) 准备的容器运行环境，预装了 `tg-signer`、`tg-signer[gui]` 和 `tgcrypto`，适合在 Docker 中执行登录、签到、消息监控或 WebUI 相关命令。

## 上游项目

- 项目主页：<https://github.com/amchii/tg-signer>
- 上游 README：<https://github.com/amchii/tg-signer/blob/main/README.md>

## 本仓库镜像行为

这个镜像主要提供一个现成的 Python 运行环境，而不是包装成固定的长驻服务：

- 基于 `python:3.12-slim`
- 预装 `tg-signer`
- 预装 `tg-signer[gui]`
- 预装 `tgcrypto`
- 工作目录固定为 `/opt/tg-signer`

因此最常见的用法是：**显式传入 `tg-signer ...` 命令**，并把工作目录挂载出来保存 session、配置和记录文件。

## 快速开始

先挂载一个持久化目录到 `/opt/tg-signer`，再显式执行 `tg-signer login` 或 `tg-signer run`。

## docker run

查看帮助：

```bash
docker run --rm -it \
  -v "$PWD/tg-signer:/opt/tg-signer" \
  ignimutos/tg-signer:latest \
  tg-signer --help
```

登录账号：

```bash
docker run --rm -it \
  -v "$PWD/tg-signer:/opt/tg-signer" \
  -e TG_PROXY=socks5://host.docker.internal:1080 \
  ignimutos/tg-signer:latest \
  tg-signer login
```

运行签到任务：

```bash
docker run --rm -it \
  -v "$PWD/tg-signer:/opt/tg-signer" \
  ignimutos/tg-signer:latest \
  tg-signer run
```

## docker compose

```yaml
services:
  tg-signer:
    image: ignimutos/tg-signer:latest
    working_dir: /opt/tg-signer
    stdin_open: true
    tty: true
    volumes:
      - ./tg-signer:/opt/tg-signer
    environment:
      TG_PROXY: socks5://host.docker.internal:1080
    command: ["tg-signer", "run"]
```

## 环境变量、端口、卷

### 常用环境变量

| 变量 | 说明 |
| --- | --- |
| `TG_PROXY` | Telegram 连接代理 |
| `TG_SESSION_STRING` | Session String |
| `TG_ACCOUNT` | 账号名 |
| `OPENAI_API_KEY` | 图片识别 / 计算题 / AI 动作相关能力 |
| `OPENAI_BASE_URL` | 自定义 OpenAI 兼容接口 |
| `OPENAI_MODEL` | 模型名称 |

### 端口

这个镜像默认不暴露固定端口；是否需要暴露端口取决于你执行的 `tg-signer` 子命令。

### 卷

| 路径 | 说明 |
| --- | --- |
| `/opt/tg-signer` | 建议整体持久化，保存 session、工作目录和数据 |

## 标签与更新策略

- `latest`
- `<version>`

标签跟随上游 `amchii/tg-signer` release 更新。

## 注意事项

- 这个镜像没有自定义 entrypoint；请显式传入 `tg-signer ...` 命令。
- 默认工作目录是 `/opt/tg-signer`，不挂载卷的话，session 和配置会在容器删除后丢失。
- 虽然镜像预装了 `gui` 依赖，但具体 WebUI 命令与参数仍以上游 `tg-signer` 当前版本为准。
