FROM alpine:3.22
RUN apk add --no-cache pgbouncer postgresql-client su-exec \
    && addgroup -S -g 10001 pooler \
    && adduser -S -D -H -u 10001 -G pooler pooler
COPY entrypoint.sh /usr/local/bin/start-pooler
RUN chmod 755 /usr/local/bin/start-pooler
ENTRYPOINT ["/usr/local/bin/start-pooler"]
