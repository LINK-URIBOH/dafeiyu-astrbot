"""Apply the reviewed v4.29.0 fnOS patch set without initializing user data.

Defaults to a read-only plan. Caller owns backup validation, service stop/start,
health checks and acceptance. The returned private before-directory permits a
code-only rollback, preserving messages recorded after the upgrade.
"""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path

MOUNTS={
 'chat_layout.py':'/AstrBot/astrbot/core/pipeline/chat_layout.py',
 'respond_stage.py':'/AstrBot/astrbot/core/pipeline/respond/stage.py',
 'proactive_llm_service.py':'/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/services/llm_service.py',
 'proactive_sender_service.py':'/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/services/sender_service.py',
 'proactive_contact_bridge.py':'/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/services/contact_bridge.py',
}
PATCHES=['face_convert_main.py','stage.py','dashscope_tts.py',*MOUNTS]

def plan(source,base):
    fnos=source/'deploy/fnos'
    subprocess.run([sys.executable,str(fnos/'tools/verify_patches.py')],check=True)
    pairs=[(fnos/'patches'/n,Path('patches')/n) for n in PATCHES]
    for plugin in ('astrbot_plugin_face_convert','astrbot_plugin_schedule_awareness'):
        for name in ('main.py','metadata.yaml'):
            pairs.append((source/'plugin'/plugin/name,Path('astrbot/data/plugins')/plugin/name))
    for name in ('runtime_smoke.py','media_smoke.py','apply_source_update.py','verify_patches.py'):
        pairs.append((fnos/'tools'/name,Path('tools')/name))
    assert all(src.is_file() for src,_ in pairs),'Incomplete source checkout'
    text=(base/'compose.yaml').read_text(encoding='utf-8-sig')
    needle='      - ./patches/stage.py:/AstrBot/astrbot/core/pipeline/result_decorate/stage.py:ro'
    assert needle in text,'Unknown Compose layout; review manually'
    extras=[]
    for name,target in MOUNTS.items():
        line=f'      - ./patches/{name}:{target}:ro'
        if line not in text:
            assert target not in text,'Conflicting mount: '+target
            extras.append(line)
    text=text.replace(needle,needle+(''.join('\n'+line for line in extras)),1)
    old=json.loads((base/'versions.lock.json').read_text(encoding='utf-8-sig'))
    new=json.loads((fnos/'versions.lock.json').read_text(encoding='utf-8'))
    assert old['plugins']==new['plugins'],'Community plugin pins differ; review first'
    if 'runtime' in old:
        assert old['runtime']==new['runtime'],'Core/runtime pins differ; review first'
    old.setdefault('runtime',new['runtime'])
    old['project']=new['project']
    old.setdefault('deployment_adaptations',{})['upstream_update']=new['deployment_adaptations']['upstream_update']
    # Older deployments selected the group in a local helper; retain that exact
    # policy instead of replacing it with a generic helper lacking its env var.
    lock=json.loads((fnos/'patches.lock.json').read_text(encoding='utf-8'))
    for name in lock['files']:
        if Path(name).name not in PATCHES:
            assert (base/name).is_file(),'Missing retained patch: '+name
            lock['files'][name]=hashlib.sha256((base/name).read_bytes()).hexdigest()
    if 'qq_gateway' in old:
        old['qq_gateway']['face_patch_sha256']=lock['files']['patches/face_convert_main.py']
    encode=lambda value:(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    return pairs,{'compose.yaml':text.encode(),'versions.lock.json':encode(old),'patches.lock.json':encode(lock)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--base',type=Path,required=True);p.add_argument('--backup',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    source=a.source.resolve();base=a.base.resolve();pairs,generated=plan(source,base)
    files={str(dst):src.read_bytes() for src,dst in pairs};files.update(generated)
    files={n:v for n,v in files.items() if not (base/n).exists() or (base/n).read_bytes()!=v}
    print('Reviewed code/configuration files to update:',len(files))
    if not a.apply:return
    assert a.backup and a.backup.is_file() and a.backup.stat().st_size>0,'Validated backup required'
    info=json.loads(subprocess.check_output(['docker','inspect','dafeiyu-astrbot']))[0]
    assert not info['State']['Running'],'Stop AstrBot before applying code'
    before=base/'incoming'/('source-update-before-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    before.mkdir(mode=0o700)
    manifest={}
    for name in files:
        dest=base/name;assert not dest.is_symlink(),'Refuse symlink target'
        manifest[name]={'existed':dest.exists()}
        if dest.exists():
            target=before/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,target)
    (before/'files.json').write_text(json.dumps(manifest,indent=2));(before/'files.json').chmod(0o600)
    try:
        for name,content in files.items():
            dest=base/name;dest.parent.mkdir(parents=True,exist_ok=True)
            mode=dest.stat().st_mode & 0o777 if dest.exists() else 0o600
            temp=dest.with_name(dest.name+'.update-tmp');temp.write_bytes(content);temp.chmod(mode);os.replace(temp,dest)
    except BaseException:
        for name,meta in manifest.items():
            if meta['existed']:shutil.copy2(before/name,base/name)
            else:(base/name).unlink(missing_ok=True)
        raise
    print('Code-only rollback directory:',before)
    print('Applied; AstrBot remains stopped. User configuration/databases and QQ untouched.')

if __name__=='__main__':main()
