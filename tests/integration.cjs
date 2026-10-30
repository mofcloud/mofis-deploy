const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync: exec, spawnSync } = require('node:child_process');
const assert = require('node:assert/strict');
const net = require('node:net');
const { Client: SSH } = require('ssh2');
const { Client: PG } = require('pg');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'mofis-deploy-test-'));
const project = `mofis-deploy-test-${process.pid}`;
let port;
const clients = new Set();
const run = (cmd,args,opts={}) => exec(cmd,args,{cwd:temp,stdio:'pipe',timeout:240000,...opts});
const compose = (...args) => run('docker',['compose','-p',project,'-f','compose.yaml','-f','compose.build.yaml',...args]);
async function freePort(){ const s=net.createServer(); await new Promise(r=>s.listen(0,'127.0.0.1',r)); const p=s.address().port; await new Promise(r=>s.close(r)); return p; }
function connect(auth){return new Promise((resolve,reject)=>{const s=new SSH();clients.add(s);s.once('close',()=>clients.delete(s));s.once('ready',()=>resolve(s));s.once('error',reject);s.connect({host:'127.0.0.1',port,username:'tunnel',readyTimeout:8000,...auth});});}
function channel(s,host='pgbouncer',port=6432){return new Promise((resolve,reject)=>s.forwardOut('127.0.0.1',0,host,port,(e,ch)=>e?reject(e):resolve(ch)));}
async function query(s,sql){const stream=await channel(s);stream.setNoDelay=()=>{};stream.setKeepAlive=()=>{};stream.connect=()=>process.nextTick(()=>stream.emit('connect'));const db=new PG({stream,user:'mof',password:fs.readFileSync(path.join(temp,'config/client-password'),'utf8'),database:'mof',connectionTimeoutMillis:8000,query_timeout:10000});try{await db.connect();return await db.query(sql);}finally{await db.end();}}
(async()=>{
 try{
  for(const f of ['compose.yaml','compose.postgres.yaml','compose.build.yaml','configure.sh','manage.sh','VERSION','README.md','README.zh-CN.md']) fs.copyFileSync(path.join(root,f),path.join(temp,f));
  for(const dir of ['images','postgres','scripts']) fs.cpSync(path.join(root,dir),path.join(temp,dir),{recursive:true});
  for(const f of ['configure.sh','manage.sh','images/ssh/entrypoint.sh','images/pgbouncer/entrypoint.sh','postgres/10-create-mof.sh']) run('sh',['-n',f]);
  run('ssh-keygen',['-q','-t','ed25519','-N','','-f',path.join(temp,'key')]);
  const publicKey=fs.readFileSync(path.join(temp,'key.pub'),'utf8').trim();
  run('sh',['configure.sh'],{input:`1\n1\n${publicKey}\n127.0.0.1\n\n`});
  assert.equal(fs.statSync(path.join(temp,'config')).mode & 0o777,0o700);
  assert.equal(fs.statSync(path.join(temp,'connection.txt')).mode & 0o777,0o600);
  assert.notEqual(spawnSync('sh',['configure.sh'],{cwd:temp,input:'\n'}).status,0);
  port=await freePort();
  fs.appendFileSync(path.join(temp,'.env'),`\nSSH_BIND_ADDRESS=127.0.0.1\nSSH_PORT=${port}\n`);
  fs.appendFileSync(path.join(temp,'.env'),`\nPG_DATA_VOLUME=${project}_pgdata\nCOMPOSE_PROJECT_NAME=${project}\n`);
  const config=JSON.parse(compose('config','--format','json').toString());
  assert(!fs.existsSync(path.join(temp,'compose.postgres.yaml')));
  assert(!config.services.postgres.ports);assert(!config.services.pgbouncer.ports);
  const external=JSON.parse(run('docker',['compose','-p',project,'-f','compose.yaml','config','--format','json'],{env:{...process.env,COMPOSE_PROFILES:''}}).toString());assert(!external.services.postgres);
  console.log('Configuration validation passed.');
  console.log('Building local test images and starting PostgreSQL + pooler + SSH...');
  compose('up','-d','--build','--wait','--wait-timeout','180');
  run('sh',['manage.sh','start']);
  compose('exec','-T','postgres','psql','-U','postgres','-d','mof','-c','CREATE TABLE public.repair_probe(value int); INSERT INTO public.repair_probe VALUES (73)');
  const originalPassword=fs.readFileSync(path.join(temp,'config/db-password'));
  fs.mkdirSync(path.join(temp,'original/config'),{recursive:true});
  fs.writeFileSync(path.join(temp,'original/config/db-password'),originalPassword);
  fs.writeFileSync(path.join(temp,'config/db-password'),'incorrect');
  const failed=spawnSync('sh',['manage.sh','start'],{cwd:temp,encoding:'utf8',timeout:45000});
  assert.equal(failed.status,1);
  assert.match(failed.stderr,/manage.sh repair/);
  run('sh',['manage.sh','repair'],{input:'1\n'+path.join(temp,'original')+'\n'});
  assert.deepEqual(fs.readFileSync(path.join(temp,'config/db-password')),originalPassword);
  assert.equal(compose('exec','-T','postgres','psql','-U','postgres','-d','mof','-Atqc','SELECT value FROM public.repair_probe').toString().trim(),'73');
  console.log('Fast password diagnosis and repair passed without resetting the database role.');
  // Forgotten password recovery must rotate only the backend password, retaining data and client credentials.
  const clientBeforeRecovery=fs.readFileSync(path.join(temp,'config/client-password'));
  run('sh',['manage.sh','repair'],{input:'2\n'});
  assert.notDeepEqual(fs.readFileSync(path.join(temp,'config/db-password')),originalPassword);
  assert.deepEqual(fs.readFileSync(path.join(temp,'config/client-password')),clientBeforeRecovery);
  assert(!fs.existsSync(path.join(temp,'config/reset-db-password')));
  assert.equal(compose('exec','-T','postgres','psql','-U','postgres','-d','mof','-Atqc','SELECT value FROM public.repair_probe').toString().trim(),'73');
  console.log('Forgotten password recovery passed with stored data and MOFIS credentials preserved.');
  // Upgrade the running deployment through the offline CLI, preserving its volume and SSH identity.
  const releaseVersion=fs.readFileSync(path.join(temp,'VERSION'),'utf8').trim();
  const fingerprintBefore=compose('exec','-T','ssh','ssh-keygen','-lf','/etc/ssh/host_keys/ssh_host_ed25519_key.pub').toString();
  run('sh',['scripts/package.sh']);
  fs.writeFileSync(path.join(temp,'VERSION'),'0.0.0\n');
  run('sh',['manage.sh','upgrade','--archive',`dist/mofis-deploy-${releaseVersion}.zip`,'--checksum','dist/SHA256SUMS']);
  assert.equal(fs.readFileSync(path.join(temp,'VERSION'),'utf8').trim(),releaseVersion);
  assert.equal(compose('exec','-T','postgres','psql','-U','postgres','-d','mof','-Atqc','SELECT value FROM public.repair_probe').toString().trim(),'73');
  assert.equal(compose('exec','-T','ssh','ssh-keygen','-lf','/etc/ssh/host_keys/ssh_host_ed25519_key.pub').toString(),fingerprintBefore);
  console.log('Offline in-place upgrade passed with data and SSH fingerprint preserved.');
  let ssh=await connect({privateKey:fs.readFileSync(path.join(temp,'key'))});
  assert.equal((await query(ssh,'SELECT current_user AS name')).rows[0].name,'mof');
  await query(ssh,'CREATE SCHEMA mof; CREATE TABLE mof.persistence(id int); INSERT INTO mof.persistence VALUES (7)');
  await query(ssh,"BEGIN; SET LOCAL search_path=mof; SELECT * FROM persistence; COMMIT;");
  await assert.rejects(channel(ssh,'postgres',5432));
  await new Promise((resolve,reject)=>ssh.exec('echo forbidden',(e,ch)=>{if(e)resolve();else{ch.close();reject(Error('Shell access unexpectedly allowed'));}}));
  ssh.end();
  // Plain Compose commands must include the managed PostgreSQL without -f flags.
  run('docker',['compose','down']);
  const remaining=run('docker',['ps','-aq','--filter',`label=com.docker.compose.project=${project}`]).toString().trim();
  assert.equal(remaining,'');
  run('sh',['manage.sh','start']);
  assert.equal(compose('exec','-T','postgres','psql','-U','postgres','-d','mof','-Atqc','SELECT id FROM mof.persistence').toString().trim(),'7');
  assert.equal(compose('exec','-T','ssh','ssh-keygen','-lf','/etc/ssh/host_keys/ssh_host_ed25519_key.pub').toString(),fingerprintBefore);
  console.log('Plain docker compose down removed all managed services; restart retained data and SSH identity.');
  // Reuse the same persisted DB as an existing backend, with a different owner/password.
  // This exercises libpq quoting of punctuation in real backend credentials.
  const backendPassword = `test\\value$"qu'ote`;
  compose('exec','-T','postgres','psql','-U','postgres','-c',`CREATE USER external_owner PASSWORD '${backendPassword.replaceAll("'","''")}'; GRANT CONNECT ON DATABASE mof TO external_owner;`);
  fs.writeFileSync(path.join(temp,'config/db-password'),backendPassword);
  fs.appendFileSync(path.join(temp,'.env'),'\nDEPLOY_MODE=external\nCOMPOSE_PROFILES=\nDB_USER=external_owner\n');
  // Drop the PG override: the existing postgres container is deliberately left running.
  run('docker',['compose','-p',project,'-f','compose.yaml','-f','compose.build.yaml','up','-d','--wait','--wait-timeout','90']);
  ssh=await connect({privateKey:fs.readFileSync(path.join(temp,'key'))});
  assert.equal((await query(ssh,'SELECT current_user AS name')).rows[0].name,'external_owner');ssh.end();console.log('Existing database and special-character password passed.');
  // Verify TLS on the real external database hop, including the copied CA permissions.
  run('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=postgres','-addext','subjectAltName=DNS:postgres','-keyout','server.key','-out','server.crt']);
  compose('cp','server.key','postgres:/tmp/test-server.key');
  compose('cp','server.crt','postgres:/tmp/test-server.crt');
  compose('exec','-T','-u','0','postgres','sh','-c','chown postgres:postgres /tmp/test-server.key /tmp/test-server.crt && chmod 600 /tmp/test-server.key');
  for(const setting of ["ssl_cert_file = '/tmp/test-server.crt'", "ssl_key_file = '/tmp/test-server.key'", "ssl = on"])
    compose('exec','-T','postgres','psql','-U','postgres','-c',`ALTER SYSTEM SET ${setting}`);
  compose('exec','-T','postgres','psql','-U','postgres','-c','SELECT pg_reload_conf()');
  fs.copyFileSync(path.join(temp,'server.crt'),path.join(temp,'config/db-ca.crt'));
  fs.appendFileSync(path.join(temp,'.env'),'\nDB_TLS_MODE=verify-full\n');
  run('docker',['compose','-p',project,'-f','compose.yaml','-f','compose.build.yaml','up','-d','--wait','--wait-timeout','90']);
  ssh=await connect({privateKey:fs.readFileSync(path.join(temp,'key'))});
  assert.equal((await query(ssh,'SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')).rows[0].ssl,true);ssh.end();
  console.log('External PostgreSQL certificate verification passed.');
  // Password auth, with public key auth disabled.
  fs.appendFileSync(path.join(temp,'.env'),'\nSSH_AUTH_MODE=password\n');
  run('docker',['compose','-p',project,'-f','compose.yaml','-f','compose.build.yaml','up','-d','--wait','--wait-timeout','90']);
  await assert.rejects(connect({password:'wrong'}));
  await assert.rejects(connect({privateKey:fs.readFileSync(path.join(temp,'key'))}));
  const password=fs.readFileSync(path.join(temp,'config/ssh-password'),'utf8');
  ssh=await connect({password});
  assert.equal((await query(ssh,'SELECT 42 AS value')).rows[0].value,42);ssh.end();
  compose('restart');
  await new Promise(r=>setTimeout(r,3000));
  ssh=await connect({password});
  // Dedicated DB and stored data survived container restart.
  assert.equal((await query(ssh,'SELECT count(*)::int AS n FROM pg_database WHERE datname = \'mof\'')).rows[0].n,1);ssh.end();
  assert.equal(compose('exec','-T','postgres','psql','-U','postgres','-d','mof','-Atqc','SELECT id FROM mof.persistence').toString().trim(),'7');
  console.log('PASS: full/existing DB, key/password auth, wrong credentials, forwarding restrictions, SQL transactions and restart persistence.');
 } catch(e){console.error(e.message); process.exitCode=1;}
 finally {for(const s of clients)s.destroy();try{fs.appendFileSync(path.join(temp,'.env'),'\nCOMPOSE_PROFILES=managed-db\n');compose('down','--volumes','--remove-orphans');}catch{}fs.rmSync(temp,{recursive:true,force:true});}
})();
