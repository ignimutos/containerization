# tor2socks

面向容器场景的 Tor 客户端镜像，提供 SOCKS 与 DNS 入口；另有 `obfs` 变体，额外内置 `lyrebird` 用于 obfs4 等桥接场景。

## 上游项目

- Tor Project：<https://www.torproject.org/>
- Bridges / obfs4 说明：<https://support.torproject.org/little-t-tor/circumvention/using-bridges/>

## 本仓库镜像行为

这个镜像会在启动时生成基础 `torrc.d/default.conf`，默认开启：

- `DNSPort 0.0.0.0:${PORT_DNS}`
- `SocksPort 0.0.0.0:${PORT_TOR}`

基础标签提供纯 Tor 客户端能力；`obfs` 标签在此基础上额外安装 `lyrebird`，并在启动时写入桥接配置、尝试获取桥接信息。

## 快速开始

如果你只需要一个本地 SOCKS + DNS 代理，直接运行基础标签即可；如果你处在需要桥接/混淆的网络环境，改用 `obfs-latest` 或 `obfs-<version>`。

## docker run

基础标签：

```bash
docker run -d \
  --name tor2socks \
  -p 9150:9150 \
  -p 8853:8853/udp \
  -v tor_data:/var/lib/tor \
  -e PORT_TOR=9150 \
  -e PORT_DNS=8853 \
  -e LOG_LEVEL=notice \
  ignimutos/tor2socks:latest
```

obfs 变体：

```bash
docker run -d \
  --name tor2socks-obfs \
  -p 9150:9150 \
  -p 8853:8853/udp \
  -v tor_data:/var/lib/tor \
  ignimutos/tor2socks:obfs-latest
```

## docker compose

```yaml
services:
  tor2socks:
    image: ignimutos/tor2socks:latest
    restart: unless-stopped
    ports:
      - "9150:9150"
      - "8853:8853/udp"
    environment:
      PORT_TOR: 9150
      PORT_DNS: 8853
      LOG_LEVEL: notice
      LOG_TARGET: stdout
    volumes:
      - tor_data:/var/lib/tor

volumes:
  tor_data:
```

## 环境变量、端口、卷

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `PORT_TOR` | `9150` | SOCKS 监听端口 |
| `PORT_DNS` | `8853` | DNS 监听端口 |
| `LOG_LEVEL` | `notice` | Tor 日志级别 |
| `LOG_TARGET` | `stdout` | Tor 日志输出 |
| `HEALTH_CHECK_URL` | `https://www.facebookwkhpilnemxj7asaniu7vnjjbiltxjqhye3mhbshg7kx5tfyd.onion` | 健康检查目标 |

### 端口

| 端口 | 说明 |
| --- | --- |
| `9150/tcp` | 默认 SOCKS5 入口 |
| `8853/udp` | 默认 DNS 入口 |

### 卷

| 路径 | 说明 |
| --- | --- |
| `/var/lib/tor` | 建议持久化 Tor 数据目录 |

## 标签与更新策略

- `latest` / `<version>`：基础 Tor 镜像
- `obfs-latest` / `obfs-<version>`：额外包含 `lyrebird`

基础标签跟随 Alpine 的 `tor` 包版本更新；`obfs` 变体还会在 `lyrebird` 包变化时触发重建。

## 注意事项

- `obfs` 变体会自动启用 `UseBridges 1` 和 `ClientTransportPlugin obfs4 exec /usr/bin/lyrebird`。
- 桥接信息本身需要你自行从 Tor 官方桥接分发渠道获取；镜像只负责运行 Tor 与 pluggable transport。
- 健康检查默认通过本地 SOCKS 访问 onion 地址；如果你的环境禁止该目标，可以覆写 `HEALTH_CHECK_URL`。
