#!/bin/ash
if [ ! -f /etc/torrc.d/default.conf ]; then
  cat <<EOF >/etc/torrc.d/default.conf
Log ${LOG_LEVEL} ${LOG_TARGET}
DNSPort 0.0.0.0:${PORT_DNS}
SocksPort 0.0.0.0:${PORT_TOR}
EOF
fi

if [ $OBFS ]; then
  cat <<EOF >/etc/torrc.d/obfs.conf
UseBridges 1
ClientTransportPlugin obfs4 exec /usr/bin/lyrebird
EOF
  tor-get-bridge
fi

chown -R tor:tor /etc/tor /etc/torrc.d /var/lib/tor
chmod -R 700 /etc/tor /etc/torrc.d /var/lib/tor
su-exec tor:tor /usr/bin/tor -f /etc/tor/torrc
