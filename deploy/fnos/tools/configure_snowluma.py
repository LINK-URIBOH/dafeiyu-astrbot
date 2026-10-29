"""Incremental deployment. Does not initialize AstrBot or accept SnowLuma terms."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1]
STAGE=BASE
DIGEST='sha256:74d6874a4240636dca700734f31fbce7d0735cbce6bb43780dd8e3788eddccc9'
IMAGE=os.environ.get('SNOWLUMA_IMAGE','motricseven7/snowluma@'+DIGEST)
assert IMAGE.endswith('@'+DIGEST), 'Expected the verified v2.2.1 amd64 digest'
BACK=BASE/'incoming/snowluma-before'

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    path.chmod(0o600)

def run(*args):
    return subprocess.check_output(args,text=True)

def prepare():
    subprocess.run(['docker','image','inspect',IMAGE],check=True,stdout=subprocess.DEVNULL)
    assert not BACK.exists(),'Existing rollback copy; do not overwrite'
    BACK.mkdir(mode=0o700)
    paths=['compose.yaml','.env','tools/heal_ws.py','tools/health.py','tools/backup.sh',
           'versions.lock.json','astrbot/data/cmd_config.json']
    for name in paths:
        p=BASE/name
        if p.exists():
            q=BACK/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    state=[]
    for name in run('docker','ps','-aq').split():
        d=json.loads(run('docker','inspect',name))[0]
        state.append({'id':d['Id'],'name':d['Name'].lstrip('/'),'image':d['Config']['Image'],
                      'started':d['State']['StartedAt'],'running':d['State']['Running'],
                      'restart':d['HostConfig']['RestartPolicy']})
    write(BACK/'containers.json',state)
    configs=BASE/'astrbot/data/config'
    write(BACK/'config-hashes.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in configs.glob('*.json')})
    print('ROLLBACK_COPY_READY')

def install():
    assert BACK.is_dir()
    for n in ['dafeiyu-astrbot','dafeiyu-napcat','napcat']:
        assert run('docker','inspect','-f','{{.State.Running}}',n).strip()=='false'
    creds=json.loads((BASE/'secrets/credentials.json').read_text(encoding='utf-8-sig'))
    access=json.loads((BASE/'secrets/admin-access.json').read_text(encoding='utf-8-sig'))
    robot=str(creds['robot_qq']).strip();assert robot.isdigit()
    for directory in ['data/config','config/QQ','share']:
        (BASE/'snowluma'/directory).mkdir(parents=True,exist_ok=True)
    os.chown(BASE/'snowluma',1000,1000)
    for p in (BASE/'snowluma').rglob('*'):
        os.chown(p,1000,1000);p.chmod(0o700)
    config={'mode':'snapshot','networks':{
        'httpServers':[{'name':'health-local','enabled':True,'host':'127.0.0.1','port':3000,'path':'/',
                        'accessToken':access['onebot_token'],'messageFormat':'array','reportSelfMessage':False}],
        'httpClients':[],'wsServers':[],
        'wsClients':[{'name':'astrbot','enabled':True,'url':'ws://astrbot:6199/ws','role':'Universal',
                      'reconnectIntervalMs':10000,'accessToken':access['onebot_token'],
                      'messageFormat':'array','reportSelfMessage':False}]},
        'statusCommand':{'enabled':False,'swallow':False,'cooldownSeconds':5,'trigger':'#sl'},
        'historySync':{'enabled':False},'notifications':{'channelIds':[]}}
    file=BASE/'snowluma/data/config'/('onebot_'+robot+'.json');write(file,config);os.chown(file,1000,1000)
    for name in ['compose.snowluma.yaml','patches/face_convert_main.py','tools/gateway_health.py','tools/backup_snapshot.py']:
        target=BASE/name;
        if (STAGE/name).resolve()!=target.resolve():shutil.copy2(STAGE/name,target)
        target.chmod(0o644)
    compose=(BASE/'compose.yaml').read_text()
    marker='  napcat:\n'
    assert marker in compose
    compose=compose.replace(marker,marker+'    profiles: [legacy-napcat]\n',1)
    start=compose.index(marker);end=compose.index('  browser:',start)
    section=compose[start:end].replace('restart: unless-stopped',"restart: 'no'")
    compose=compose[:start]+section+compose[end:]
    (BASE/'compose.yaml').write_text(compose)
    import ipaddress
    lan=os.environ.get('DAFEIYU_LAN_IP','').strip()
    if lan:
        assert ipaddress.ip_address(lan).is_private
        over=(BASE/'compose.snowluma.yaml').read_text()
        for port in [5099,6081]:
            line="      - '127.0.0.1:"+str(port)+":"+str(port)+"'"
            extra="      - '"+lan+":"+str(port)+":"+str(port)+"'"
            if extra not in over:over=over.replace(line,line+'\n'+extra)
        (BASE/'compose.snowluma.yaml').write_text(over)
    env=BASE/'.env';text=env.read_text() if env.exists() else ''
    text=re.sub(r'(?m)^(COMPOSE_FILE|SNOWLUMA_IMAGE)=.*\n?','',text)
    env.write_text(text.rstrip()+'\nCOMPOSE_FILE=compose.yaml:compose.cost-report.yaml:compose.snowluma.yaml\nSNOWLUMA_IMAGE='+IMAGE+'\n');env.chmod(0o600)
    healer=BASE/'tools/heal_ws.py';text=healer.read_text()
    text=text.replace('def main():\n','def main():\n    from gateway_health import backend, snowluma_health\n    if backend() == "snowluma":\n        healthy = adapter_connected() and snowluma_health()\n        print("SnowLuma: " + ("connected and online" if healthy else "offline or awaiting login; no QQ restart attempted"))\n        return 0 if healthy else 1\n',1)
    healer.write_text(text)
    health=BASE/'tools/health.py';text=health.read_text().replace("for name in ('dafeiyu-astrbot', 'dafeiyu-napcat', 'dafeiyu-browser'):","from gateway_health import backend\nfor name in ('dafeiyu-astrbot', 'dafeiyu-snowluma' if backend() == 'snowluma' else 'dafeiyu-napcat', 'dafeiyu-browser'):")
    health.write_text(text)
    backup=BASE/'tools/backup.sh';text=backup.read_text()
    text,n=re.subn(r'(?m)^tar -czf .*$', 'python3 tools/backup_snapshot.py "$TEMP"',text)
    assert n==1;backup.write_text(text)
    write(BASE/'gateway.json',{'backend':'snowluma','version':'2.2.1','image':IMAGE})
    lock=BASE/'versions.lock.json';data=json.loads(lock.read_text());data['qq_gateway']={'backend':'snowluma','version':'2.2.1','image':IMAGE,'previous':'napcat 4.18.37','face_patch_sha256':hashlib.sha256((BASE/'patches/face_convert_main.py').read_bytes()).hexdigest()};write(lock,data)
    d=json.loads(subprocess.check_output(['docker','compose','--profile','legacy-napcat','config','--format','json'],cwd=BASE,text=True))
    assert d['services']['napcat']['profiles']==['legacy-napcat']
    assert d['services']['napcat']['restart']=='no'
    targets=[v for v in d['services']['astrbot']['volumes'] if v['target']=='/app/.config/QQ']
    assert len(targets)==1 and '/snowluma/' in targets[0]['source']
    assert {x['target'] for x in d['services']['snowluma']['ports']}=={5099,6081}
    print('INCREMENTAL_CONFIG_READY')

if __name__=='__main__':
    {'prepare':prepare,'install':install}[sys.argv[1]]()
