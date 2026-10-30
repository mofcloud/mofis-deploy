#!/usr/bin/env python3
"""Upgrade deployment files in place; credentials and Docker volumes stay put."""
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
import zipfile

FILES = {
    'VERSION', 'README.md', 'README.zh-CN.md', 'compose.yaml',
    'compose.postgres.yaml', 'configure.sh', 'manage.sh',
    'postgres/10-create-mof.sh', 'scripts/config-common.sh',
    'scripts/repair.sh', 'scripts/upgrade.py',
}

def version(value):
    value = value.removeprefix('v') if hasattr(value, 'removeprefix') else value.lstrip('v')
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Expected a release version such as 0.1.6.')
    return value

MIRROR = 'https://data.mofcloud.com/mofis-deploy'

def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={'User-Agent': 'mofis-deploy-upgrade'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('Release download exceeds the size limit.')
    return data

def download_release(requested=None, source='auto'):
    sources = ['cloudflare', 'github'] if source == 'auto' else [source]
    for provider in sources:
        try:
            release = requested
            timeout = 15 if provider == 'cloudflare' else 60
            print('Checking %s (request timeout: %s seconds)' % (provider, timeout), flush=True)
            if provider == 'cloudflare':
                if not release:
                    release = version(json.loads(fetch(MIRROR + '/latest.json', timeout=timeout))['version'])
                base = MIRROR + '/' + release + '/'
            else:
                if not release:
                    metadata = json.loads(fetch('https://api.github.com/repos/mofcloud/mofis-deploy/releases/latest', timeout=timeout))
                    release = version(metadata['tag_name'])
                base = 'https://github.com/mofcloud/mofis-deploy/releases/download/v' + release + '/'
            print('Downloading v%s from %s' % (release, provider), flush=True)
            data = fetch(base + 'mofis-deploy-' + release + '.zip', timeout=timeout)
            checksums = fetch(base + 'SHA256SUMS', timeout=timeout).decode()
            return data, checksums, release
        except (urllib.error.URLError, TimeoutError, OSError):
            if provider == sources[-1]:
                raise
            print('Cloudflare download unavailable; trying GitHub.', flush=True)
            # A discovered version remains fixed when falling back; never mix
            # archives and checksums from different sources or change releases.
            requested = release

def unpack(data, checksums, requested=None):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) != len(FILES) or len({m.filename for m in members}) != len(members):
            raise ValueError('Unexpected or duplicate files in release archive.')
        prefixes = {PurePosixPath(m.filename).parts[0] for m in members}
        if len(prefixes) != 1:
            raise ValueError('Invalid release directory.')
        prefix = prefixes.pop()
        release = version(prefix.removeprefix('mofis-deploy-') if hasattr(prefix, 'removeprefix') else prefix.replace('mofis-deploy-', '', 1))
        if prefix != 'mofis-deploy-' + release or (requested and release != requested):
            raise ValueError('Release version does not match the requested version.')
        expected = 'mofis-deploy-' + release + '.zip'
        entries = [line.split() for line in checksums.splitlines() if line.strip()]
        hashes = [parts[0] for parts in entries if len(parts) == 2 and parts[1] == expected]
        if hashes != [hashlib.sha256(data).hexdigest()]:
            raise ValueError('Release checksum verification failed.')
        payload = {}
        for member in members:
            relative = member.filename[len(prefix) + 1:]
            mode = member.external_attr >> 16
            if relative not in FILES or stat.S_ISLNK(mode) or member.file_size > 1024 * 1024:
                raise ValueError('Unsafe or unexpected release member.')
            payload[relative] = archive.read(member)
        if set(payload) != FILES or payload['VERSION'].decode().strip() != release:
            raise ValueError('Incomplete release or inconsistent VERSION.')
    return release, payload

def replace(path, contents):
    # Atomic per file, including .env. Never rewrite credential files.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.upgrade-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(contents)
        os.chmod(temporary, 0o755 if path.suffix == '.sh' else 0o600 if path.name == '.env' else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def upgrade(root, release, payload):
    current = version((root/'VERSION').read_text().strip())
    if tuple(map(int, release.split('.'))) <= tuple(map(int, current.split('.'))):
        print('Already at version %s or newer; no changes made.' % release, flush=True)
        return
    if (root/'config/reset-db-password').exists():
        raise ValueError('Finish the pending password recovery with ./manage.sh start before upgrading.')
    pg_pattern = rb'image:\s*postgres:(\d+)'
    old_compose = (root/'compose.yaml').read_bytes()
    if (root/'compose.postgres.yaml').is_file():
        old_compose += (root/'compose.postgres.yaml').read_bytes()
    old_pg = re.search(pg_pattern, old_compose)
    new_pg = re.search(pg_pattern, payload['compose.yaml'])
    if (old_pg.group(1) if old_pg else None) != (new_pg.group(1) if new_pg else None):
        raise ValueError('PostgreSQL major-version changes require a separate database migration.')
    env = (root/'.env').read_bytes()
    if not (root/'config').is_dir():
        raise ValueError('Existing configuration is missing; run configure.sh for a new installation.')
    text = env.decode()
    if not re.search(r'^COMPOSE_PROFILES=', text, flags=re.M):
        mode = re.search(r'^DEPLOY_MODE=(full|external)$', text, flags=re.M)
        if not mode:
            raise ValueError('Missing or invalid deployment mode.')
        text = text.rstrip('\n') + '\nCOMPOSE_PROFILES=' + ('managed-db' if mode.group(1) == 'full' else '') + '\n'
    # Keep explicit project/volume identities and every other setting unchanged.
    text = re.sub(r'^MOFIS_DEPLOY_VERSION=.*\n?', '', text, flags=re.M)
    text = text.rstrip('\n') + '\nMOFIS_DEPLOY_VERSION=' + release + '\n'
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = root/'.upgrade-backups'/(current + '-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    originals = {}
    for name in sorted(FILES | {'.env'}):
        path = root/name
        if path.is_symlink():
            raise ValueError('Refusing to replace symlink: ' + name)
        originals[name] = path.read_bytes() if path.is_file() else None
        if originals[name] is not None:
            replace(backup/name, originals[name])
    print('[3/4] Updating deployment files in the current directory', flush=True)
    try:
        for name, contents in payload.items():
            replace(root/name, contents)
        replace(root/'.env', text.encode())
        print('[4/4] Starting and checking the upgraded services', flush=True)
        subprocess.run(['sh', 'manage.sh', 'start'], cwd=root, check=True)
    except (Exception, KeyboardInterrupt):
        print('Upgrade failed/interrupted. Restoring the previous deployment files.', file=sys.stderr, flush=True)
        for name, contents in originals.items():
            if contents is None:
                (root/name).unlink(missing_ok=True)
            else:
                replace(root/name, contents)
        try:
            subprocess.run(['sh', 'manage.sh', 'start'], cwd=root, check=True)
            print('Previous services restored.', file=sys.stderr, flush=True)
        except Exception:
            print('Previous files restored, but services are not ready. Run ./manage.sh logs.', file=sys.stderr)
        raise
    print('Upgrade complete: %s -> %s. Configuration and data retained.' % (current, release), flush=True)
    print('Previous deployment files retained at: ' + str(backup), flush=True)

def main():
    if sys.version_info < (3, 8):
        raise ValueError('Upgrade requires Python 3.8 or newer.')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Upgrade interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', nargs='?')
    parser.add_argument('--directory', required=True)
    parser.add_argument('--archive', type=Path, help='Offline release ZIP')
    parser.add_argument('--checksum', type=Path, help='Offline SHA256SUMS file')
    parser.add_argument('--source', choices=['auto', 'cloudflare', 'github'], default='auto', help='Download source (default: Cloudflare, then GitHub)')
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    lock = root/'.upgrade-lock'
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        parser.exit(1, 'Another upgrade may be running. If it was interrupted, remove .upgrade-lock after checking.\n')
    try:
        print('[1/4] Finding the release', flush=True)
        requested = version(args.version) if args.version else None
        if args.archive:
            if not args.checksum:
                raise ValueError('Offline upgrades require --checksum SHA256SUMS.')
            data, checksums = args.archive.read_bytes(), args.checksum.read_text()
        else:
            if args.checksum:
                raise ValueError('--checksum requires --archive.')
            data, checksums, requested = download_release(requested, args.source)
        print('[2/4] Verifying checksum and release contents', flush=True)
        release, payload = unpack(data, checksums, requested)
        upgrade(root, release, payload)
    finally:
        lock.rmdir()

if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print('Upgrade stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
