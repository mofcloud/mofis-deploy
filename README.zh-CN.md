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

仅放行配置时选择的服务器 SSH 端口（默认 **2222**）。无需开放数据库端口 5432 或 6432。连接串中的 `pgbouncer:6432` 是隧道内的地址，不要改成服务器公网地址。

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

## 已安装过 MOFIS 数据库？

完整模式会检测本机已有的 MOFIS 数据卷。默认选择「继续使用原数据库」，自动读取可用的旧配置。找不到时可选择「生成新密码」或导入原密码。生成新密码会在启动时通过容器内管理员连接重设 `mof` 角色密码，保留数据库内容；其他使用旧数据库密码的客户端需要更新连接。若容器内管理员认证不可用，脚本会停止并提示，不删除数据。

选择「创建独立数据库」时，会生成独立项目名和数据卷，不覆盖旧库；默认 SSH 端口为 2223，也可以自行指定。普通 PostgreSQL 实例不会被自动当成 MOFIS 数据库接管。

已有配置启动时如果密码不匹配，脚本会提前提示。可以执行：

```sh
./manage.sh repair
```

默认导入原密码，也可选择「忘记密码」生成新密码。两种方式均保留数据和 MOFIS 连接串；密码恢复只适用于本工具管理的 PostgreSQL，外接数据库仍需联系管理员。

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

启动时会显示镜像检查/下载进度、PG 就绪、连接验证和服务就绪四个阶段；本地已有镜像时直接复用，不重复访问镜像仓库。

## 原地升级

需要 Python 3.8 或更新版本。在当前使用的部署目录执行：

```sh
./manage.sh upgrade
# 或指定版本：
./manage.sh upgrade 0.1.8
```

脚本从 GitHub 下载正式安装包，验证 SHA256 和文件清单，备份部署文件后在原目录更新。保留已有配置、密码、MOFIS 连接串、Docker 项目及数据卷名称和 SSH 指纹，只更新镜像版本配置。服务检查失败时恢复旧文件并尝试启动旧服务；若 Docker 或网络不可用，回退后的服务也可能启动失败，请查看结果提示。本操作不代替数据库备份，也不支持自动跨 PostgreSQL 大版本升级。

0.1.6 以前的版本没有升级命令。第一次先下载并解压新版，再用新版升级脚本指向**原来已经配置好的目录**：

```sh
python3 /新版目录/scripts/upgrade.py --directory /原部署目录
```

完成后继续使用原部署目录，新解压的临时目录可以删除；以后直接执行 `./manage.sh upgrade`，不要重新运行 `configure.sh`。

服务器无法访问 GitHub 时，可以在电脑下载 ZIP 和同一版本的 `SHA256SUMS`，传到服务器后离线更新：

```sh
./manage.sh upgrade --archive /文件路径/mofis-deploy-0.1.8.zip --checksum /文件路径/SHA256SUMS
```

旧版第一次升级时，将同样的 `--archive` 和 `--checksum` 参数加到新版 `scripts/upgrade.py` 命令后即可。Docker 镜像仍需要本地已有或能够从镜像仓库下载。确认正常前保留 `.upgrade-backups/`；升级期间不要同时执行其他部署命令。异常中断可能留下 `.upgrade-lock`，确认没有升级进程运行后才可删除该锁目录。

## 一个 Compose 文件，两种数据库模式

需要 Docker Compose 2.20 或更新版本。`configure.sh` 自动将模式保存到 `.env`：自带 PG 开启 `COMPOSE_PROFILES=managed-db`；外接 PG 留空。日常直接执行 `docker compose up -d`、`docker compose stop` 或 `docker compose down`，不需要额外指定文件。使用 `manage.sh start` 还会检查连接并显示启动进度。除非明确要删除数据，否则不要给 `down` 加 `-v` / `--volumes`。

旧配置在升级/启动时自动迁移，保留项目名、数据卷、密码和 CA。安装包临时携带一个供旧升级命令识别的兼容文件，配置/启动后自动移除；运行时只使用 `compose.yaml`。维护者测试用的 `compose.build.yaml` 不进入用户下载包。
