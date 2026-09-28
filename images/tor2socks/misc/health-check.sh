#!/bin/ash
if curl -sf --socks5-hostname localhost:${PORT_TOR} -IL ${HEALTH_CHECK_URL}; then
  exit 0
else
  exit 1
fi
