# Target A — synthetic HTTP training service (disposable, no external deps at runtime)
FROM alpine:3.20

# Build-time only: python3 for the tiny synthetic service. No runtime egress.
RUN apk add --no-cache python3

COPY server.py /server.py

# Non-root app user (uid 1001), no capabilities needed
RUN adduser -D -u 1001 -s /sbin/nologin labhttp \
    && chown -R labhttp:labhttp /server.py

USER labhttp
EXPOSE 8080
CMD ["python3", "-u", "/server.py"]
