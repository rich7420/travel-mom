"""Exercise a built image under compose-equivalent hardening with synthetic data.

Run: python scripts/verify_container.py --image travel-mom-verify:local
Requires Docker and httpx. Creates labelled disposable containers/volumes only.
Uses an ephemeral LOOPBACK port; never binds the live preview port.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',default='data/lifecycle-review/container.json')
    args=parser.parse_args()
    owner='mom-verify-'+uuid4().hex[:12]; token=secrets.token_hex(32)
    containers,volumes,checks=[],[],[]
    from cryptography.fernet import Fernet
    encryption_key=Fernet.generate_key().decode()
    def docker(*parts):
        result=subprocess.run(['docker',*parts],text=True,capture_output=True,check=True)
        return result.stdout.strip()
    def check(label,condition=True):
        if not condition:raise RuntimeError(label)
        checks.append(label)
    def volume(suffix):
        name=owner+'-'+suffix
        docker('volume','create','--label','mom.verify.owner='+owner,name);volumes.append(name)
        return name
    def run(name,vol,command=(),source=None,server=False):
        name=owner+'-'+name
        params=['run','-d','--name',name,'--label','mom.verify.owner='+owner,'--read-only','--tmpfs','/tmp:rw,size=64m',
                '-e','PII_FERNET_KEY='+encryption_key,'--cap-drop','ALL','--security-opt','no-new-privileges','-v',vol+':/data']
        if source:params+=['-v',source+':/source:ro']
        if server:params+=['-p','127.0.0.1::8000','-e','APP_ENV=production','-e','AUTH_MODE=token',
                          '-e','OPENCLAW_ENABLED=false','-e','TRAVEL_DESK_ADMIN_TOKEN='+token]
        containers.append(name);docker(*params,args.image,*command)
        return name
    def wait_job(name):
        code=docker('wait',name)
        if code!='0':raise RuntimeError('Disposable job failed: '+docker('logs',name))
    def endpoint(name):
        port=docker('port',name,'8000/tcp').split(':')[-1]
        base='http://127.0.0.1:'+port
        for _ in range(150):
            try:
                if httpx.get(base+'/livez',timeout=.5).status_code==200:return base
            except httpx.HTTPError:pass
            time.sleep(.2)
        raise RuntimeError('Container did not become live: '+docker('logs',name))
    try:
        source=volume('source'); restored=volume('restored')
        live=run('app',source,server=True);base=endpoint(live)
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token},timeout=10) as api:
            check('production rejects unsigned API',httpx.get(base+'/api/cases').status_code==401)
            case=api.post('/api/cases',json={'customer_name':'容器合成驗證','destination':'東京'}).json()
            check('nonroot can write mounted SQLite',case.get('id') is not None)
            check('Mom, admin and guide assets serve',all(api.get(p).status_code==200 for p in ('/','/admin','/static/guide.html')))
            check('oversized actual body rejected',api.post('/api/cases',content=b'x'*1_100_000,headers={'Content-Type':'application/json'}).status_code==413)
            from datetime import datetime, timezone
            def lifecycle(action,extra=None):
                state=api.get(f"/api/mom/cases/{case['id']}/operations").json()['lifecycle']['expected_state']
                return api.post(f"/api/mom/cases/{case['id']}/lifecycle/{action}",json={
                    'request_id':str(uuid4()),'expected_state':state,'reference':'synthetic checked dialogue',
                    'occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,'reason':'synthetic recovery evidence',**(extra or {})})
            check('container closes and reopens with evidence',lifecycle('close',{'outcome':'withdrawn'}).status_code==200 and lifecycle('reopen').status_code==200)
            # Modest concurrent HTTP smoke, not a throughput benchmark.
            def create(i):
                r=api.post('/api/cases',json={'customer_name':f'負載合成{i}','destination':'大阪'})
                if r.status_code!=200:raise RuntimeError(r.text)
                return r.json()['id']
            with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(create,range(100)))
            check('100 synthetic writes across 8 workers',len(set(ids))==100)
        inspect=json.loads(docker('inspect',live))[0]
        check('compose-equivalent hardening active',inspect['Config']['User']=='travel' and inspect['HostConfig']['ReadonlyRootfs'] and inspect['HostConfig']['CapDrop']==['ALL'] and 'no-new-privileges' in inspect['HostConfig']['SecurityOpt'])
        docker('restart',live);base=endpoint(live)
        check('container restart preserves all 101 cases',len(httpx.get(base+'/api/cases',headers={'Authorization':'Bearer '+token}).json())==101)
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token}) as api:
            private_path=f"/api/mom/cases/{case['id']}"
            t=api.post(private_path+'/travellers',json={'request_id':str(uuid4()),'name':'Synthetic encrypted traveller','category':'adult','date_of_birth':'1990-01-01','passport_number':'SYNTHETIC123','passport_expiry':'2030-01-01','nationality':'TW'}).json()
            check('container encrypted traveller write',bool(t.get('id')))
            doc=api.post(private_path+'/documents',json={'request_id':str(uuid4()),'kind':'other','title':'Synthetic original','required':False}).json()
            import base64
            upload=api.post(private_path+f"/documents/{doc['id']}/attachments",params={'request_id':str(uuid4()),'expected_revision':doc['revision']},content=b'%PDF-1.4 synthetic container original',headers={'content-type':'application/pdf','x-file-name':base64.b64encode(b'synthetic.pdf').decode()})
            check('container encrypted original write',upload.status_code==200)
            attachment=upload.json()
        job=run('bundle-backup',source,('python','-m','scripts.backup_bundle','run'))
        wait_job(job);bundle_info=json.loads(docker('logs',job))
        check('encrypted online backup includes originals',bundle_info['attachments']==1)
        encrypted_restored=volume('encrypted-restored')
        bundle_source='/source/backups/'+Path(bundle_info['bundle']).name
        job=run('bundle-restore',encrypted_restored,('python','-m','scripts.backup_bundle','restore','--bundle',bundle_source,'--database','/data/travel_desk.db','--attachments','/data/attachments'),source=source)
        wait_job(job);check('encrypted restore uses new database and file volume')
        encrypted_live=run('encrypted-recovered',encrypted_restored,server=True);encrypted_base=endpoint(encrypted_live)
        with httpx.Client(base_url=encrypted_base,headers={'Authorization':'Bearer '+token}) as recovered_api:
            reveal=recovered_api.get(private_path+f"/travellers/{t['id']}/reveal")
            original=recovered_api.get(private_path+f"/attachments/{attachment['id']}/download")
            check('restored HTTP reveal decrypts passport',reveal.json().get('passport_number')=='SYNTHETIC123')
            check('restored HTTP download decrypts original',original.content==b'%PDF-1.4 synthetic container original')
        # Online backup from the running service's volume; restore copies it to a NEW file.
        job=run('backup',source,('python','scripts/database_backup.py','backup','/data/travel_desk.db','/data/verified-backup.db'))
        wait_job(job);check('live backup integrity and FK checks pass')
        job=run('restore',restored,('python','scripts/database_backup.py','restore','/source/verified-backup.db','/data/travel_desk.db'),source=source)
        wait_job(job);check('restore reads source volume read-only')
        recovered=run('recovered',restored,server=True);recovered_base=endpoint(recovered)
        records=httpx.get(recovered_base+'/api/cases',headers={'Authorization':'Bearer '+token}).json()
        check('restored application serves all original cases',len(records)==101 and case['id'] in {r['id'] for r in records} and set(ids)<={r['id'] for r in records})
        operations=httpx.get(recovered_base+f"/api/mom/cases/{case['id']}/operations",headers={'Authorization':'Bearer '+token}).json()
        check('restored lifecycle history retains both immutable events',len(operations['case_events'])==2 and [e['action'] for e in operations['case_events']]==['close','reopen'])
        script=("import sqlite3; db=sqlite3.connect('/data/travel_desk.db'); "
                "triggers={r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='agency_case_events'\")}; "
                "valid={'immutable_case_event_update','immutable_case_event_delete'}<=triggers; db.close()\n"
                "if not valid: raise SystemExit(1)\n")
        docker('exec',recovered,'python','-c',script)
        check('restored lifecycle immutability triggers persist')
        check('restored application can accept new work' ,httpx.post(recovered_base+'/api/cases',headers={'Authorization':'Bearer '+token},json={'customer_name':'還原後的新案件'}).status_code==200)
        out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({'image':args.image,'synthetic':True,'checks':checks,'load':{'writes':100,'workers':8}},ensure_ascii=False,indent=2))
        print(f'{len(checks)} hardened-container checks passed; original and restored volumes verified')
    finally:
        for name in reversed(containers):
            # Names and ownership labels must both match before removing anything.
            try:
                if docker('inspect','--format','{{index .Config.Labels "mom.verify.owner"}}',name)==owner:docker('rm','-f',name)
            except subprocess.CalledProcessError:pass
        for name in reversed(volumes):
            try:
                if docker('volume','inspect','--format','{{index .Labels "mom.verify.owner"}}',name)==owner:docker('volume','rm',name)
            except subprocess.CalledProcessError:pass


if __name__=='__main__':main()
