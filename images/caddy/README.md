# Caddy

> 基于官方 Caddy 镜像构建的增强版容器，内置常用插件，并额外提供 `naive` 变体。

## Upstream Project

- 上游服务是 [Caddy](https://caddyserver.com/)。
- 官方镜像说明见 [Docker Hub `caddy`](https://hub.docker.com/_/caddy)，镜像源码在 [`caddyserver/caddy-docker`](https://github.com/caddyserver/caddy-docker)。
- Caddyfile 语法见 [Caddyfile 文档](https://caddyserver.com/docs/caddyfile)。
- `naive` 变体额外包含 `forward_proxy` 模块的 naive 分支，相关能力来自 [`caddyserver/forwardproxy`](https://github.com/caddyserver/forwardproxy) 与 [`klzgrad/naiveproxy`](https://github.com/klzgrad/naiveproxy)。

## What This Image Adds

- 所有标签都在官方 `caddy:<version>-alpine` 基础上重新编译，并内置：
  - `github.com/caddy-dns/cloudflare`
  - `github.com/caddyserver/transform-encoder`
  - `github.com/greenpau/caddy-trace`
  - `github.com/caddyserver/replace-response`
  - `github.com/mholt/caddy-l4`
- `naive` 变体额外编译：
  - `github.com/caddyserver/forwardproxy=github.com/klzgrad/forwardproxy@naive`
- 安装 `tzdata`，默认设置 `TZ=Asia/Shanghai`。
- 额外提供辅助脚本：`caddy-fmt`、`caddy-check`、`caddy-reload`。

## Image Targets

- 默认变体：`ignimutos/caddy:latest` 和 `ignimutos/caddy:<version>`
- `naive` 变体：`ignimutos/caddy:naive-latest` 和 `ignimutos/caddy:naive-<version>`
- 仓库内对应的 Docker build target 分别是 `caddy-base`、`caddy-naive`。

## Configuration

- 容器默认从 `/etc/caddy/Caddyfile` 读取配置，并使用 `caddyfile` adapter 启动。
- 建议持久化 `/data/caddy`，保存证书与运行状态。
- 可通过 `TZ` 覆盖容器时区。
- 如果使用 `naive` 变体，需要在 `Caddyfile` 中显式启用 `forward_proxy`。
- 根据上游 `forwardproxy`/NaïveProxy 文档，代理场景通常应让站点地址以 `:443` 开头；如果同时使用 `file_server`，需要把 `forward_proxy` 放到更靠前的顺序，例如全局 `order forward_proxy before file_server`。

## Files, Ports, and Volumes

- 文件：
  - `/etc/caddy/Caddyfile`：默认加载的主配置文件
  - `/usr/bin/caddy-fmt`：格式化 `/etc/caddy/Caddyfile`
  - `/usr/bin/caddy-check`：格式化后执行 `caddy adapt`
  - `/usr/bin/caddy-reload`：格式化后执行 `caddy reload`
- 端口：
  - `80/tcp`：HTTP
  - `443/tcp`：HTTPS
  - `443/udp`：HTTP/3 / QUIC，镜像未显式 `EXPOSE`，如需启用请在运行时自行映射
- 卷：
  - `/data/caddy`：已声明为持久化卷

## Usage

默认变体示例：

```bash
docker run -d \
  --name caddy \
  -p 80:80 \
  -p 443:443 \
  -p 443:443/udp \
  -e TZ=Asia/Shanghai \
  -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v caddy_data:/data/caddy \
  ignimutos/caddy:latest
```

`naive` 变体最小示例：

```caddyfile
{
  order forward_proxy before file_server
}

:443, example.com {
  tls me@example.com
  forward_proxy {
    basic_auth user pass
    hide_ip
    hide_via
    probe_resistance
  }
}
```

```bash
docker run -d \
  --name caddy-naive \
  -p 443:443 \
  -p 443:443/udp \
  -e TZ=Asia/Shanghai \
  -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v caddy_data:/data/caddy \
  ignimutos/caddy:naive-latest
```

## Notes

- 入口命令固定为 `caddy run --config /etc/caddy/Caddyfile --adapter caddyfile`，容器内必须存在可用的 `Caddyfile`。
- `caddy-check` 与 `caddy-reload` 都默认操作 `/etc/caddy/Caddyfile`。
- `naive` 是仓库里的 target 名；对外发布的 Docker tag 是 `naive-latest` / `naive-<version>`。
