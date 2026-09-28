# Nezha Agent

为 [Nezha Agent](https://github.com/nezhahq/agent) 提供的容器化运行方式，适合把被监控节点接入 Nezha Dashboard。

## 上游项目

- Agent 仓库：<https://github.com/nezhahq/agent>
- Agent 安装文档：<https://nezha-v0.mereith.dev/en_US/guide/agent>

## 本仓库镜像行为

这个镜像会从上游源码编译 `agent` 二进制，并通过 entrypoint 根据环境变量自动生成 `/root/config.yml`。

与上游手动安装相比，这个容器镜像额外做了几件事：

- 默认禁用自动更新
- 默认禁用强制更新
- 默认禁用命令执行
- 当未显式提供 `NEZHA_UUID` 时，尝试根据宿主机网卡 MAC 地址自动生成 UUID

## 快速开始

最常见的方式是直接使用宿主机网络运行，并提供 Dashboard 地址与 `client_secret`。

## docker run

```bash
docker run -d \
  --name nezha-agent \
  --network host \
  -e NEZHA_SERVER=data.example.com:5555 \
  -e NEZHA_CLIENT_SECRET=your-secret \
  -e NEZHA_TLS=false \
  ignimutos/nezha-agent:latest
```

如果你希望手动维护配置文件，也可以挂载：

```bash
docker run -d \
  --name nezha-agent \
  --network host \
  -v "$PWD/config.yml:/root/config.yml" \
  ignimutos/nezha-agent:latest
```

## docker compose

```yaml
services:
  nezha-agent:
    image: ignimutos/nezha-agent:latest
    restart: unless-stopped
    network_mode: host
    environment:
      NEZHA_SERVER: data.example.com:5555
      NEZHA_CLIENT_SECRET: your-secret
      NEZHA_TLS: "false"
      NEZHA_DEBUG: "true"
      NEZHA_DISABLE_AUTO_UPDATE: "true"
      NEZHA_DISABLE_COMMAND_EXECUTE: "true"
      NEZHA_DISABLE_FORCE_UPDATE: "true"
```

## 环境变量、端口、卷

### 常用环境变量

| 配置项 | 环境变量 | 默认值 |
| --- | --- | --- |
| `server` | `NEZHA_SERVER` | 必填 |
| `client_secret` | `NEZHA_CLIENT_SECRET` | 必填 |
| `uuid` | `NEZHA_UUID` | 未设置时自动生成 |
| `debug` | `NEZHA_DEBUG` | `true` |
| `tls` | `NEZHA_TLS` | `false` |
| `disable_auto_update` | `NEZHA_DISABLE_AUTO_UPDATE` | `true` |
| `disable_command_execute` | `NEZHA_DISABLE_COMMAND_EXECUTE` | `true` |
| `disable_force_update` | `NEZHA_DISABLE_FORCE_UPDATE` | `true` |

### 端口

这个镜像通常通过 `network_mode=host` 直接使用宿主机网络，不单独暴露固定端口映射。

### 卷

| 路径 | 说明 |
| --- | --- |
| `/root/config.yml` | 可选，自定义 agent 配置 |

## 标签与更新策略

- `latest`
- `<version>`

标签跟随上游 `nezhahq/agent` release 更新。

## 注意事项

- 推荐使用 `network_mode=host`，这样最接近上游 agent 直接运行的网络行为。
- `NEZHA_SERVER`、`NEZHA_CLIENT_SECRET` 需要从你的 Nezha Dashboard 后台获取。
- 如果你不设置 `NEZHA_UUID`，镜像会尝试基于宿主机设备信息自动生成；在某些精简环境里，显式设置会更稳定。
