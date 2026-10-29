"""Migration UX tests with fake Docker; never inspect a developer's actual volumes."""
import os, pathlib, shutil, subprocess, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='mofis-reuse-test-') as tmp:
    base = pathlib.Path(tmp)
    old = base/'old'; old.mkdir()
    # Must remain data, never evaluated as shell commands.
    password = 'a'*64
    (old/'.env').write_text(f'MOF_DB_PASSWORD={password}\nUNRELATED=$(touch {base}/injected)\n')
    fake = base/'bin'; fake.mkdir()
    docker = fake/'docker'
    docker.write_text('#!/bin/sh\ncase "$1 $2" in\n "info ") exit 0;;\n "volume ls") echo mofis-shared-db_pgdata;;\n "ps -a") printf "%s\\n" "$TEST_OLD_DIR";;\n *) exit 1;;\nesac\n')
    docker.chmod(0o755)
    env = {**os.environ,'PATH':str(fake)+':'+os.environ['PATH'],'TEST_OLD_DIR':str(old)}
    def directory_hint(paths):
        return subprocess.run(
            ['sh','-c','. "$1"; old_directory','sh',str(root/'scripts/config-common.sh')],
            cwd=base,env={**env,'TEST_OLD_DIR':'\n'.join(map(str,paths))},
            text=True,capture_output=True,check=True).stdout.strip()
    missing=base/'deleted-deployment'
    empty=base/'no-credentials'; empty.mkdir()
    assert directory_hint([missing])==''
    assert directory_hint([empty])==''
    assert directory_hint([base])==''  # Never recommend the current directory.
    assert directory_hint([missing,empty,old])==str(old)
    def setup(name, answers):
        target=base/name; target.mkdir()
        for f in ['configure.sh','VERSION']: shutil.copy(root/f,target/f)
        shutil.copytree(root/'scripts',target/'scripts')
        result=subprocess.run(['sh','configure.sh'],cwd=target,env=env,input=answers,text=True,capture_output=True,check=True)
        return target,result
    reused,result=setup('reuse',f'1\n1\n2\nexample.com\n\n')
    assert (reused/'config/db-password').read_text()==password
    assert (reused/'config/client-password').read_text()==password
    config=(reused/'.env').read_text()
    assert 'COMPOSE_PROJECT_NAME=mofis-shared-db' in config
    assert 'PG_DATA_VOLUME=mofis-shared-db_pgdata' in config
    assert password not in result.stdout+result.stderr
    assert 'connectivity has not been verified' in result.stderr
    assert 'loaded automatically' in result.stderr
    assert not (base/'injected').exists()
    independent,_=setup('new','1\n2\n2\nexample.com\n\n')
    config=(independent/'.env').read_text()
    assert 'SSH_PORT=2223' in config
    assert 'COMPOSE_PROJECT_NAME=mofis-db-' in config
    assert 'PG_DATA_VOLUME=mofis-shared-db_pgdata' not in config
    assert (independent/'config/db-password').read_text()!=password
    # Repair imports backend credentials only; retain the MOFIS-facing password and inode.
    (reused/'config/db-password').write_text('incorrect')
    inode=(reused/'config/db-password').stat().st_ino
    client=(reused/'config/client-password').read_text()
    result=subprocess.run(['sh','scripts/repair.sh'],cwd=reused,env=env,input='1\n\n',text=True,capture_output=True,check=True)
    assert (reused/'config/db-password').read_text()==password
    assert (reused/'config/db-password').stat().st_ino==inode
    assert (reused/'config/client-password').read_text()==client
    assert password not in result.stdout+result.stderr
    # Missing old directories offer data-preserving recovery without an old password.
    env['TEST_OLD_DIR']=str(missing)
    recovered,result=setup('recover','1\n1\n\n2\nexample.com\n\n')
    assert (recovered/'config/reset-db-password').exists()
    assert len((recovered/'config/db-password').read_text())==64
    assert 'Other clients' in result.stderr
    env['TEST_OLD_DIR']=str(old)
    # New-format credential imports work too.
    (old/'config').mkdir()
    (old/'config/db-password').write_text('b'*64)
    (old/'config/client-password').write_text('c'*64)
    imported,_=setup('modern','1\n1\n2\nexample.com\n\n')
    assert (imported/'config/db-password').read_text()=='b'*64
    assert (imported/'config/client-password').read_text()=='c'*64
print('PASS: valid directory hints, legacy/current password import, separate volume, safe parsing and non-destructive repair.')
