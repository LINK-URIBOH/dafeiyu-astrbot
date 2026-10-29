"""Read-only protocol health. Never restart QQ or enable a legacy gateway."""
import json
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parents[1]


def backend():
    path = BASE / 'gateway.json'
    return json.loads(path.read_text()).get('backend', 'napcat') if path.exists() else 'napcat'


def snowluma_health():
    # Query only a loopback OneBot listener inside the container. The token
    # remains in the process and never appears in argv or returned diagnostics.
    code = r'''
const fs=require('fs');
(async()=>{
 const dir='/app/data/config';
 const files=fs.readdirSync(dir).filter(x=>/^onebot_\d+\.json$/.test(x));
 if(files.length!==1) throw Error('account config missing');
 const c=JSON.parse(fs.readFileSync(dir+'/'+files[0],'utf8'));
 const h=c.networks.httpServers.find(x=>x.enabled!==false);
 if(!h) throw Error('health listener missing');
 const r=await fetch('http://127.0.0.1:'+h.port+'/',{
  method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+h.accessToken},
  body:JSON.stringify({action:'get_status',params:{}}),signal:AbortSignal.timeout(10000)});
 const d=await r.json();
 console.log(JSON.stringify({ok:r.ok&&d.retcode===0,online:d.data?.online===true,good:d.data?.good===true}));
})().catch(()=>{console.log(JSON.stringify({ok:false,online:false,good:false}));process.exitCode=1});
'''
    try:
        r = subprocess.run(['docker', 'exec', 'dafeiyu-snowluma', 'node', '-e', code],
                           capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout.strip())
        return bool(d.get('ok') and d.get('online') and d.get('good'))
    except Exception:
        return False


if __name__ == '__main__':
    raise SystemExit(0 if snowluma_health() else 1)
