#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
version=$(cat VERSION)
mkdir -p dist
# Explicit allowlist: credentials, local config and build contexts never enter downloads.
python3 - "$version" <<'PY'
import pathlib, sys, zipfile, hashlib
root=pathlib.Path('.')
version=sys.argv[1]
name=f'mofis-deploy-{version}'
files=['VERSION','README.md','README.zh-CN.md','compose.yaml','compose.postgres.yaml','configure.sh','manage.sh','postgres/10-create-mof.sh','scripts/config-common.sh','scripts/repair.sh','scripts/upgrade.py']
archive=root/'dist'/f'{name}.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as out:
 for file in files:
  if file == 'compose.postgres.yaml' and not (root/file).exists():
   out.writestr(f'{name}/{file}', '# MOFIS_LEGACY_UPGRADE_BRIDGE\nservices:\n  postgres:\n    image: postgres:16-alpine\n')
  else:
   out.write(file,f'{name}/{file}')
(root/'dist'/'SHA256SUMS').write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n')
print(archive)
PY
