# MOFIS 团队共享数据库

在自己的服务器部署数据库连接服务，由 MOFIS 通过 SSH 隧道访问。服务器无需安装 MOF。团队共享库需要 MOFIS Pro 或有效试用。

两种方案共用此下载包：

| 方案 | 组件 | 适用情况 |
| --- | --- | --- |
| 完整版 | PostgreSQL 16 + PgBouncer + SSH | 没有数据库，推荐首次部署 |
| 已有数据库 | PgBouncer + SSH | 已有 PostgreSQL / RDS |

## 快速开始

需要 Docker Engine、Docker Compose V2、OpenSSL。密钥模式还需要 `ssh-keygen`。支持 Linux amd64 / arm64。

从本仓库 Releases 下载 ZIP，解压后运行：

```sh
chmod +x configure.sh manage.sh
./configure.sh
./manage.sh start
```

按提示选择方案、认证方式、填写服务器地址。密钥模式粘贴**自己电脑的公钥**（通常是 `~/.ssh/id_ed25519.pub`），私钥留在自己电脑。没有密钥时可以在电脑执行 `ssh-keygen -t ed25519`，也可以选择自动生成密码。

在服务器上查看 `connection.txt`，按其中内容在 MOFIS 添加「团队共享库」，选择「SSH 隧道」。密钥认证选择对应私钥或 SSH Agent；密码认证使用生成的 SSH 密码。

仅放行服务器 SSH 端口 **2222**。无需开放数据库端口 5432 或 6432。连接串中的 `pgbouncer:6432` 是隧道内的地址，不要改成服务器公网地址。

```sh
./manage.sh fingerprint  # 核对 MOFIS 显示的 SSH 主机指纹
./manage.sh status
./manage.sh logs
./manage.sh stop
./manage.sh start
```

`connection.txt` 包含连接凭证，请仅交给获准访问共享库的团队成员。不要上传 `config/`、`.env` 或 `connection.txt`。配置脚本不会覆盖已有配置。

## 已有数据库

配置脚本选择 2。先准备一个独立数据库及其所有者账号，该账号需要创建 schema、表、索引和执行迁移的权限，无需超级用户。数据库需允许此服务器访问。

填写真实数据库地址、端口、名称、用户和密码。MOFIS 仍使用脚本生成的 `mof@pgbouncer:6432/mof` 连接串；PgBouncer 在内部映射到真实数据库。真实数据库密码不需要填入 MOFIS。

数据库密码支持常见标点，暂不支持换行。数据库名和用户名使用简单字母、数字、下划线等标识符。

外部数据库 TLS 默认校验证书，需要提供数据库 CA 文件；也可选择仅加密（不验证身份），或在受信任私网关闭 TLS。SSH 仅加密电脑到 SSH 容器这一段，不会代替 PgBouncer 到远程数据库的 TLS。

不要同时让多个独立 MOF 服务和 MOFIS 管理同一个新库，首次连接按 App 提示等待初始化。实际兼容性需要以所用 MOFIS 版本和数据库权限测试为准。

## 数据与更新

数据库数据和 SSH 主机密钥使用 Docker 命名卷持久保存。`stop` 和 `restart` 不删除数据。更新前备份数据库及配置。完整模式的数据库密码只在首次初始化生效，修改文件不会自动更改已有数据库角色密码。

PgBouncer 默认 **Session pooling**，支持应用事务和会话级迁移锁；不要直接改成 Transaction pooling。SSH 容器仅允许转发到 `pgbouncer:6432`，不提供终端或 SFTP。

## 维护者发布

镜像：`ghcr.io/mofcloud/pgbouncer` 和 `ghcr.io/mofcloud/ssh-tunnel`。

```sh
npm ci
npm test
./scripts/package.sh
```

修改 `VERSION` 并更新 `compose.yaml` 中默认镜像版本，提交代码后推送对应 `vX.Y.Z` 标签。GitHub Actions 会先执行测试，再构建 amd64 / arm64 镜像，发布 GHCR，创建附带 ZIP 和校验和的 Release。普通分支推送只测试，不发布。首次发布后需要在组织 Packages 中将两份镜像设为 Public；测试匿名拉取后再把下载入口放到官网。

测试使用独立临时 Docker 项目，不连接真实客户数据库，结束后清理测试卷。下载包使用文件白名单打包，不包含本机密钥或密码。

参考：[PostgreSQL SSH 隧道](https://www.postgresql.org/docs/current/ssh-tunnels.html)、[PgBouncer 配置](https://www.pgbouncer.org/config.html)、[GitHub 镜像发布](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)。
