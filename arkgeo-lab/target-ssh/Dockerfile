# Target B — disposable SSH training service (authorized lab account only)
FROM alpine:3.20

# Build-time only: sshd server. No host keys, no production secrets.
RUN apk add --no-cache openssh-server \
    && mkdir -p /run/sshd /etc/ssh \
    && ssh-keygen -A \
    && adduser -D -u 1000 -s /bin/sh labuser \
    && echo "labuser:Arklab-Test-2026!" | chpasswd

COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# Non-privileged container execution: default Docker caps only (no --privileged),
# no host mounts, no host SSH keys (keys generated in-image at build time).
EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
