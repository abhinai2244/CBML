FROM cloudflare/cloudflared:latest AS cf
FROM alpine:latest

COPY --from=cf /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY tunnel.sh /script/tunnel.sh

ENTRYPOINT ["/bin/sh", "/script/tunnel.sh"]
