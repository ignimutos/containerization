FROM alpine:latest AS base

ENV TZ=Asia/Shanghai
ENV PORT_TOR=9150
ENV PORT_DNS=8853
ENV LOG_LEVEL=notice
ENV LOG_TARGET=stdout
ENV HEALTH_CHECK_URL=https://www.facebookwkhpilnemxj7asaniu7vnjjbiltxjqhye3mhbshg7kx5tfyd.onion

COPY --chown=tor:tor misc/torrc /etc/tor/
COPY --chown=tor:tor misc/*.sh /
COPY --chown=tor:tor misc/tor-reload /usr/bin/tor-reload

RUN echo '@edge https://dl-cdn.alpinelinux.org/alpine/edge/community' >> /etc/apk/repositories && \
  apk -v add tor@edge curl tzdata su-exec --no-cache && \
  mkdir /etc/torrc.d && \
  chmod -R 700 /etc/tor /etc/torrc.d /var/lib/tor && \
  chmod +x /health-check.sh /entrypoint.sh /usr/bin/tor-reload

HEALTHCHECK --timeout=10s --start-period=60s \
  CMD sh -c /health-check.sh

VOLUME [ "/var/lib/tor" ]

ENTRYPOINT [ "/entrypoint.sh" ]


FROM base AS obfs

ENV OBFS=true

COPY --chown=tor:tor misc/tor-get-bridge /usr/bin/tor-get-bridge

RUN apk -v add lyrebird@edge --no-cache && \
  chmod +x /usr/bin/tor-get-bridge