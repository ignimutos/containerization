ARG VERSION=2.10.0


FROM caddy:${VERSION}-builder-alpine AS builder
RUN xcaddy build --with github.com/caddyserver/forwardproxy=github.com/klzgrad/forwardproxy@naive


FROM caddy:${VERSION}-alpine

ENV TZ=Asia/Shanghai
ENV DOMAIN=
ENV EMAIL=
ENV USER=
ENV PASS=
ENV REVERSE_SERVER=https://docs.godotengine.org
ENV LOG_LEVEL=info

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY misc/entrypoint.sh /entrypoint.sh

RUN apk add --no-cache tzdata &&\
  chmod +x /usr/bin/caddy /entrypoint.sh

VOLUME [ "/data/caddy" ]

EXPOSE 80 443

ENTRYPOINT [ "/entrypoint.sh" ]
