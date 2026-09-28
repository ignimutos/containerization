#!/bin/sh
CONFIG_FILE="/root/config.yml"
[ ! -f "$CONFIG_FILE" ] && touch "$CONFIG_FILE"

write_config() {
  local key="${1%%=*}"
  local key=$(echo "$key" | tr '[:upper:]' '[:lower:]' | sed 's/nezha_//')
  local value="${1#*=}"
  local pattern="${key}:\s*[^\s]+"

  if ! grep -qE "$pattern" "$CONFIG_FILE"; then
    echo "$key: $value" | tee -a "$CONFIG_FILE"
  fi
}

if [ -z "${NEZHA_UUID}" ]; then
  for iface in $(ls /sys/class/net); do
    if [ -d "/sys/class/net/$iface/device" ]; then
      mac=$(cat "/sys/class/net/$iface/address")
      echo "Found Mac Address: $mac"
      break
    fi
  done
  name=${mac:-$(cat /etc/machine-id 2>/dev/null)}
  name=${name:-$(cat /etc/resolv.conf)}
  export NEZHA_UUID=$(uuidgen --md5 -n @dns -N ${name})
fi

if printenv | grep -q '^NEZHA_'; then
  echo "Generate Agent Config:"
  echo "------------------------------"
  printenv | grep -i '^NEZHA_' | while read -r line; do
    write_config "$line"
  done
  echo "------------------------------"
  echo "Generate Agent Config Complete"
fi
exec /agent -c="$CONFIG_FILE"
