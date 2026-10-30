# MOFIS shared database deployment

[中文说明](README.zh-CN.md)

Self-host a PostgreSQL connection service for MOFIS. No MOF server installation is required. Team shared databases require MOFIS Pro or an active trial.

- **New database:** PostgreSQL 16 + PgBouncer + SSH.
- **Existing database:** PgBouncer + SSH, connected to your dedicated PostgreSQL database or RDS.
- Key authentication by default; generated SSH password optional.
- Session pooling, SCRAM client authentication, persistent database and SSH host keys.
- Only SSH port 2222 is published. No database ports or interactive SSH shell are exposed.

## Install

Download a versioned ZIP from Releases. Requires Docker Engine, Docker Compose V2 and OpenSSL; key mode additionally requires `ssh-keygen`. Linux amd64 and arm64 images are published on release tags.

```sh
chmod +x configure.sh manage.sh
./configure.sh
./manage.sh start
```

Choose a deployment mode, authentication method and server address. For key mode paste your computer's **public** key; keep the private key on your computer. Password mode generates a random password.

Open the private `connection.txt` on the server and enter its settings in MOFIS → Add team shared database → SSH tunnel. Keep `pgbouncer:6432` in the database URI: it is the tunnel destination, not a public DNS name.

```sh
./manage.sh fingerprint  # compare with the host fingerprint shown in MOFIS
./manage.sh status
./manage.sh logs
./manage.sh stop
./manage.sh start
```

Allow SSH port 2222 through your server firewall. Protect `config/`, `.env` and `connection.txt`; never commit or publish them. The setup script refuses to overwrite existing configuration.

## Existing PostgreSQL

Create a dedicated database and owner role before setup. The role needs schema/table/index creation and migration privileges, but not superuser privileges. Allow the deployment server to reach it. Provide its address, database, username and password during setup. MOFIS uses a separate generated pooler credential; the actual backend password stays on the server.

TLS certificate verification is the default for an external database; supply its CA certificate. Encryption-only and private-network plaintext are explicit alternatives. SSH does not encrypt the hop from PgBouncer to the external database. Newline passwords are unsupported; database/user names must be simple identifiers.

## Existing MOFIS deployment

Full setup detects local MOFIS data volumes. Choose continue (default). Saved credentials are loaded automatically when available; otherwise choose to generate a new password or import the original password. Generating a password resets only the managed PostgreSQL `mof` role on start, preserving database contents. Other clients using the old database password must update their connections. Local PostgreSQL administrator access is required; if unavailable, recovery stops without deleting data. Reusing a project takes over its containers while retaining the data volume.
Choosing an independent database creates a unique project and volume, retaining the old deployment. The suggested SSH port is 2223; the wizard allows another port. Arbitrary PostgreSQL installations are not automatically taken over.

Startup checks backend credentials before waiting for pooler health. To repair a mismatch in an existing full-mode configuration:

```sh
./manage.sh repair
```

Choose import (default) to keep the database password, or forgotten-password recovery to generate a new one. Both preserve data and MOFIS client credentials. Recovery is available only for our managed PostgreSQL, not external databases.

Startup displays image checks/download progress, PostgreSQL readiness, connection verification and service readiness. Cached images are reused without contacting the registry.

## Persistence and upgrades

Named Docker volumes retain PostgreSQL data and SSH host identity across restarts. Back up both the database and configuration before upgrades. PostgreSQL initialization credentials apply only when creating a new data volume; editing a secret does not rotate an existing database role's password.

Keep PgBouncer in **session** mode. This supports SQL transactions and session-level migration locks. SSH forwarding is restricted to `pgbouncer:6432`; shell and SFTP sessions are disabled.

## Maintainer release

```sh
npm ci
npm test
./scripts/package.sh
```

Set `VERSION` and matching default image tags in `compose.yaml`, commit, and push `vX.Y.Z`. Actions tests, publishes multi-architecture images to `ghcr.io/mofcloud/pgbouncer` and `ghcr.io/mofcloud/ssh-tunnel`, then creates a ZIP release with checksums and mirrors it to Cloudflare R2. Branch pushes only validate. On first publication, set both GHCR packages to Public and verify anonymous pulls before publishing website download links.

Tests run against disposable local containers and clean up their volumes. Release archives contain an explicit allowlist of files, excluding all local credentials.

## Upgrade in place

Python 3.8+ is required. From your existing deployment directory:

```sh
./manage.sh upgrade
# Or choose a published version:
./manage.sh upgrade 0.1.9
```

The command downloads from `https://data.mofcloud.com/mofis-deploy` first and falls back to the official GitHub release if that source is unavailable, verifies SHA256 and archive contents, backs up deployment files in `.upgrade-backups/`, and upgrades the current directory. It keeps `.env` settings, `config/`, `connection.txt`, project/volume identities and SSH host keys. Only the deployment image version setting changes. Failed service checks restore previous deployment files and attempt to restart the previous services. Check the reported result; rollback can still fail if Docker or the network is unavailable. Database contents are not backed up by this operation; PostgreSQL major-version changes are rejected.

For versions before 0.1.6, download and extract the new bundle once, then use its upgrader against the **old, configured directory**:

```sh
python3 /path/to/new-bundle/scripts/upgrade.py --directory /path/to/current-deployment
```

Continue using the current deployment directory afterward; the extra extracted bundle is no longer needed. Do not rerun `configure.sh` for upgrades.

For deployments through 0.1.8, the installed upgrader still uses GitHub. Bootstrap the CF-enabled version once from the **existing configured directory**:

```sh
curl -fLO https://data.mofcloud.com/mofis-deploy/0.1.9/mofis-deploy-0.1.9.zip
curl -fLO https://data.mofcloud.com/mofis-deploy/0.1.9/SHA256SUMS
./manage.sh upgrade --archive ./mofis-deploy-0.1.9.zip --checksum ./SHA256SUMS
```

Afterward, `./manage.sh upgrade` uses Cloudflare automatically. Use `--source cloudflare` or `--source github` to select a source explicitly. A checksum or invalid-metadata error stops the upgrade; it does not silently switch sources.

If the server cannot access either source, download the ZIP and `SHA256SUMS` on another computer, transfer both to the server, then run:

```sh
./manage.sh upgrade --archive /path/to/mofis-deploy-0.1.9.zip --checksum /path/to/SHA256SUMS
```

For the first upgrade from an older version, pass the same offline arguments to the new bundle's `scripts/upgrade.py` command above. Required Docker images must also be available locally or downloadable from the registry. Keep backups until the upgrade has been verified. Avoid running other deployment commands during an upgrade; an interrupted process may leave `.upgrade-lock`, which should only be removed after confirming no upgrade is still running.

## One Compose file, two database modes

Requires Docker Compose 2.20+ for optional service dependencies. `configure.sh` saves the mode in `.env`: managed PostgreSQL enables `COMPOSE_PROFILES=managed-db`; external PostgreSQL leaves it empty. Use `docker compose up -d`, `docker compose stop` or `docker compose down` without extra file arguments. `manage.sh start` also checks credentials and displays startup progress. Do not add `--volumes` / `-v` to `down` unless you intend to delete stored data.

Old configurations are migrated automatically on upgrade/start without changing the project name, data volume, passwords or CA. The release includes a temporary compatibility file for older upgrade commands; setup/start removes it automatically. Only `compose.yaml` is used at runtime. Maintainer-only `compose.build.yaml` is not part of customer downloads.

## Cloudflare release mirror

Actions repository secrets: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (object read/write for this bucket only). Repository variables: `R2_ACCOUNT_ID`, `R2_BUCKET=mofcloud-public`, `R2_PUBLIC_URL=https://data.mofcloud.com`. Uploads use the [official R2 S3-compatible endpoint](https://developers.cloudflare.com/r2/api/).

The release workflow uploads only the versioned ZIP and SHA256SUMS under `mofis-deploy/<version>/`. It verifies both public downloads before publishing `mofis-deploy/latest.json`, with caching disabled for that pointer. Serialized mirror jobs cannot move the pointer back to an older version. Other bucket objects are left untouched. If mirroring fails after GitHub release creation, rerun the failed mirror job. Docker images still come from GHCR; the ZIP mirror does not mirror images.
