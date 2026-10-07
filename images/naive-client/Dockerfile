FROM alpine:latest AS builder

ARG VERSION=143.0.7499.109-2

RUN apk add --no-cache wget xz; \
  set -eux; \
  apkArch="$(apk --print-arch)"; \
  case "$apkArch" in \
    x86_64)  binArch='x64' ;; \
    aarch64) binArch='arm64' ;; \
    riscv64) binArch='riscv64' ;; \
    *) echo >&2 "error: unsupported architecture ($apkArch)"; exit 1 ;; \
  esac; \
  wget -O /tmp/naive.tar.xz "https://github.com/klzgrad/naiveproxy/releases/download/v${VERSION}/naiveproxy-v${VERSION}-linux-${binArch}.tar.xz"; \
  xz -d /tmp/naive.tar.xz; \
  tar -xvf /tmp/naive.tar -C /tmp/; \
  cp /tmp/naiveproxy-v${VERSION}-linux-${binArch}/naive /usr/bin/naive


FROM alpine:latest

COPY --from=builder /usr/bin/naive /usr/bin/naive
COPY misc/entrypoint.sh /entrypoint.sh

ENV TZ=Asia/Shanghai
ENV LISTEN=socks://0.0.0.0:1080
ENV PROXY=

RUN apk add --no-cache tzdata gcompat libgcc; \
  chmod +x /usr/bin/naive /entrypoint.sh; \
  naive --version

ENTRYPOINT [ "/entrypoint.sh" ]