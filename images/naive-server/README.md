# NaïveProxy Server

基于 Caddy 和 `forwardproxy@naive` 插件构建的 NaïveProxy 服务端镜像，用来暴露一个带 Naïve padding 的前置代理入口。

## 上游项目

- NaïveProxy：<https://github.com/klzgrad/naiveproxy>
- Caddy：<https://caddyserver.com/>
- Caddy `reverse_proxy` 文档：<https://caddyserver.com/docs/caddyfile/directives/reverse_proxy>
- Caddy `basic_auth` 文档：<https://caddyserver.com/docs/caddyfile/directives/basic_auth>

## 本仓库镜像行为

这个镜像不是直接运行 `naive` 二进制，而是：

- 通过 `xcaddy` 编译 `github.com/caddyserver/forwardproxy=github.com/klzgrad/forwardproxy@naive`
- 在启动时根据环境变量生成 `/etc/caddy/Caddyfile`
- 使用 Caddy 提供 TLS、认证、forward proxy 和反向代理能力

适合单容器部署一个 Naïve 服务端入口。

## 快速开始

你需要至少提供：

- `DOMAIN`
- `EMAIL`
- `USER`
- `PASS`
- `REVERSE_SERVER`

其中 `REVERSE_SERVER` 是伪装站点或反代上游地址，`USER`/`PASS` 用作 forward proxy 认证。

## docker run

```bash
docker run -d \
  --name naive-server \
  -p 80:80 \
  -p 443:443 \
  -p 443:443/udp \
  -v caddy_data:/data/caddy \
  -e DOMAIN=example.com \
  -e EMAIL=admin@example.com \
  -e USER=naiveuser \
  -e PASS=naivepass \
  -e REVERSE_SERVER=https://example.org \
  -e LOG_LEVEL=info \
  ignimutos/naive-server:latest
```

## docker compose

```yaml
services:
  naive-server:
    image: ignimutos/naive-server:latest
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      DOMAIN: example.com
      EMAIL: admin@example.com
      USER: naiveuser
      PASS: naivepass
      REVERSE_SERVER: https://example.org
      LOG_LEVEL: info
      TZ: Asia/Shanghai
    volumes:
      - caddy_data:/data/caddy

volumes:
  caddy_data:
```

## 环境变量、端口、卷

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `DOMAIN` | 空 | 对外服务域名 |
| `EMAIL` | 空 | TLS 证书申请邮箱 |
| `USER` | 空 | forward proxy 用户名 |
| `PASS` | 空 | forward proxy 密码 |
| `REVERSE_SERVER` | `https://docs.godotengine.org` | 伪装或反代上游 |
| `LOG_LEVEL` | `info` | Caddy 日志级别 |

### 端口

| 端口 | 说明 |
| --- | --- |
| `80/tcp` | HTTP |
| `443/tcp` | HTTPS |
| `443/udp` | HTTP/3 / QUIC |

### 卷

| 路径 | 说明 |
| --- | --- |
| `/data/caddy` | 建议持久化证书和运行数据 |

## 标签与更新策略

- `latest`
- `<version>`

标签跟随上游 Caddy 版本，也会在 `forwardproxy@naive` 插件源码变化时触发重建。

## 注意事项

- 这个镜像使用环境变量生成配置，不适合把自定义 `Caddyfile` 当作主要配置入口。
- `REVERSE_SERVER` 只是反向代理目标，不会自动替你生成上游应用。
- `DOMAIN`、`EMAIL`、`USER`、`PASS`、`REVERSE_SERVER` 缺一不可，否则 entrypoint 会直接退出。
