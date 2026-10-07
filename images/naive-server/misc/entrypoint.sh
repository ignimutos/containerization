#!/bin/ash
set -e

check_var() {
  if [ -z "$1" ]; then
    echo "错误：环境变量 $2 未设置！"
    exit 1
  fi
}

# 校验必须的环境变量（根据实际需求调整）
check_var "$DOMAIN" "DOMAIN"
check_var "$EMAIL" "EMAIL"
check_var "$USER" "USER"
check_var "$PASS" "PASS"
check_var "$REVERSE_SERVER" "REVERSE_SERVER"

if [ -e /etc/caddy/Caddyfile ]; then
  cat <<EOF >/etc/caddy/Caddyfile
{
  admin off
	log {
		output stdout
		format console {
			time_format wall
			time_local
		}
		level $LOG_LEVEL
	}
  order forward_proxy before file_server
  order forward_proxy before reverse_proxy
}
:443, $DOMAIN {
  tls $EMAIL
  forward_proxy {
    basic_auth $USER $PASS
    hide_ip
    hide_via
    probe_resistance
  }
  reverse_proxy  $REVERSE_SERVER  {
    header_up  Host  {upstream_hostport}
    header_up  X-Forwarded-Host  {host}
  }
}
EOF
fi

caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
