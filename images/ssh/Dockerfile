FROM alpine:3.22
RUN apk add --no-cache openssh-server \
    && adduser -D -s /bin/sh tunnel
COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /usr/local/bin/start-ssh
RUN chmod 755 /usr/local/bin/start-ssh
ENTRYPOINT ["/usr/local/bin/start-ssh"]
