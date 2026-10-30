"""Ensure registry progress and failures are visible before any DB startup."""
import os, pathlib, shutil, subprocess, tempfile

root = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mofis-start-test-') as tmp:
    base = pathlib.Path(tmp)
    shutil.copy(root/'manage.sh', base/'manage.sh')
    (base/'.env').write_text('DEPLOY_MODE=full\n')
    (base/'compose.postgres.yaml').write_text('# MOFIS_LEGACY_UPGRADE_BRIDGE\nservices: {}\n')
    binary = base/'bin'; binary.mkdir()
    docker = binary/'docker'
    docker.write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$TEST_CALLS"
case "$*" in
  *'--pull'*) echo 'unknown flag: --pull' >&2; exit 1;;
  *'run --rm'*)
    if [ "$TEST_RUN_FAIL" = yes ]; then echo 'unknown flag: --example' >&2; exit 1; fi;;
  *'config --images'*) echo ghcr.io/mofcloud/pgbouncer:test;;
  'image inspect '*) test "$TEST_CACHED" = yes;;
  'pull '*) echo 'Download progress visible'; test "$TEST_PULL_FAIL" = no;;
  *) exit 0;;
esac
''')
    docker.chmod(0o755)
    def start(cached, fail, run_fail='no'):
        calls = base/'calls'; calls.write_text('')
        env = {**os.environ, 'PATH':str(binary)+':'+os.environ['PATH'],
               'TEST_CACHED':cached, 'TEST_PULL_FAIL':fail, 'TEST_RUN_FAIL':run_fail, 'TEST_CALLS':str(calls)}
        result = subprocess.run(['sh','manage.sh','start'], cwd=base,env=env,text=True,capture_output=True,timeout=10)
        return result,calls.read_text()
    result,calls = start('no','yes')
    assert result.returncode != 0
    assert 'COMPOSE_PROFILES=managed-db' in (base/'.env').read_text()
    assert not (base/'compose.postgres.yaml').exists()
    assert 'Download progress visible' in result.stdout
    assert 'Image download failed' in result.stderr
    assert ' up ' not in calls and ' run ' not in calls
    result,calls = start('no','no')
    assert result.returncode == 0
    assert 'Download progress visible' in result.stdout
    assert all(f'[{step}/4]' in result.stderr for step in range(1,5))
    assert '--pull' not in calls
    result,calls = start('yes','yes')
    assert result.returncode == 0
    assert '\npull ' not in '\n'+calls
    result,calls = start('yes','no','yes')
    assert result.returncode != 0
    assert 'command compatibility error' in result.stderr
    assert 'Cannot connect to PostgreSQL' not in result.stderr
    assert '[4/4]' not in result.stderr
print('PASS: visible image downloads, actionable download errors and cached offline startup.')
