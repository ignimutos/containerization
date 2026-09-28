# NaïveProxy Client

基于上游 [NaïveProxy](https://github.com/klzgrad/naiveproxy) 发布包封装的客户端镜像，用来在容器内提供本地 SOCKS 代理入口。

## 上游项目

- 项目主页：<https://github.com/klzgrad/naiveproxy>
- 用法说明：<https://github.com/klzgrad/naiveproxy/blob/master/USAGE.txt>

## 本仓库镜像行为

这个镜像下载上游发布的 `naive` 二进制，并通过简单的 entrypoint 把环境变量转换为：

```bash
naive --listen="$LISTEN" --proxy="$PROXY"
```

适合把容器作为一个单独的 Naïve 客户端使用，而不是在容器里维护复杂的 `config.json`。

## 快速开始

最常见的用法是把本地 `1080` 映射到容器里的 SOCKS 端口，再通过 `PROXY` 指向你的 Naïve 服务端。

## docker run

```bash
docker run -d \
  --name naive-client \
  -p 1080:1080 \
  -e LISTEN=socks://0.0.0.0:1080 \
  -e PROXY=https://user:pass@example.com \
  -e TZ=Asia/Shanghai \
  ignimutos/naive-client:latest
```

## docker compose

```yaml
services:
  naive-client:
    image: ignimutos/naive-client:latest
    restart: unless-stopped
    ports:
      - "1080:1080"
    environment:
      TZ: Asia/Shanghai
      LISTEN: socks://0.0.0.0:1080
      PROXY: https://user:pass@example.com
```

## 环境变量、端口、卷

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `LISTEN` | `socks://0.0.0.0:1080` | 本地监听地址 |
| `PROXY` | 空 | 上游 Naïve 代理地址，通常需要显式设置 |

### 端口

| 端口 | 说明 |
| --- | --- |
| `1080/tcp` | 默认 SOCKS5 入口（由 `LISTEN` 决定） |

### 卷

这个镜像默认不依赖持久化卷。

## 标签与更新策略

- `latest`
- `<version>`

标签跟随上游 `klzgrad/naiveproxy` 的 release 版本更新。

## 注意事项

- `PROXY` 应填写你的 Naïve 服务端地址，例如 `https://user:pass@example.com` 或 `quic://user:pass@example.com`。
- 这个镜像走环境变量驱动；如果你想使用更复杂的 JSON 配置，需要自行覆写启动命令。
- 如果你需要服务端而不是客户端，请使用本仓库的 `naive-server` 镜像。
