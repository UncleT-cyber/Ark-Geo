#!/bin/sh
# ARK Lab Target B entrypoint — foreground sshd, logs to stderr (docker logs).
set -e
echo "[ark-lab-ssh] starting sshd on :22 (lab account: labuser)" >&2
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
