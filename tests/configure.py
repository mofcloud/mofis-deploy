"""Exercise interactive password setup on a real terminal, without real credentials."""
import os, pathlib, pty, select, shutil, subprocess, tempfile, time
root = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mofis-config-test-') as folder:
    target = pathlib.Path(folder)
    for file in ['configure.sh', 'VERSION']:
        shutil.copy(root / file, target / file)
    shutil.copytree(root / 'scripts', target / 'scripts')
    (target / 'ca.crt').write_text('fixture-public-certificate')
    master, slave = pty.openpty()
    process = subprocess.Popen(['sh', 'configure.sh'], cwd=target, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    steps = [
        (b'Deployment [1]:', '2\n'),
        (b'Authentication [1]:', '2\n'),
        (b'IP or hostname):', 'example.com\n'),
        (b'SSH port [2222]:', '\n'),
        (b'PostgreSQL hostname:', 'database.example.com\n'),
        (b'port [5432]:', '\n'),
        (b'name [mof]:', 'team_db\n'),
        (b'username [mof]:', 'team_owner\n'),
        (b'Database TLS [1]:', '1\n'),
        (b'file path:', str(target / 'ca.crt') + '\n'),
        (b'(hidden):', 'fixture!$\'"\\password\n'),
    ]
    buffer = b''
    deadline = time.monotonic() + 15
    try:
        for prompt, answer in steps:
            while prompt not in buffer:
                assert time.monotonic() < deadline, 'Setup prompt timed out'
                if select.select([master], [], [], 0.1)[0]:
                    buffer += os.read(master, 4096)
            buffer = b''
            os.write(master, answer.encode())
        assert process.wait(timeout=10) == 0
        config = (target / '.env').read_text()
        assert 'DB_TLS_MODE=verify-full' in config and 'DEPLOY_MODE=external' in config
        assert (target / 'config/db-password').read_text() == 'fixture!$\'"\\password'
        assert (target / 'config').stat().st_mode & 0o777 == 0o700
        assert (target / 'connection.txt').stat().st_mode & 0o777 == 0o600
        assert 'team_owner' not in (target / 'connection.txt').read_text()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
print('PASS: interactive existing-DB setup, hidden special-character password and private connection guide.')
