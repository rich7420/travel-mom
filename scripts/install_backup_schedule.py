"""Create a per-user macOS launchd backup job; --install loads this project-specific job."""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def job_config(repo, python):
    repo=Path(repo).resolve();label='com.travelmom.backup.'+hashlib.sha256(str(repo).encode()).hexdigest()[:10]
    return {'Label':label,'ProgramArguments':[str(Path(python).absolute()),'-m','scripts.backup_bundle','run','--env-file',str(repo/'.env')],
            'WorkingDirectory':str(repo),'StartInterval':21600,'RunAtLoad':True,'ProcessType':'Background',
            'StandardOutPath':str(repo/'data'/'backup-service.log'),'StandardErrorPath':str(repo/'data'/'backup-service-error.log')}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--install',action='store_true');parser.add_argument('--output');args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1];config=job_config(repo,sys.executable)
    target=Path(args.output) if args.output else (Path.home()/'Library'/'LaunchAgents' if args.install else repo/'data')/f"{config['Label']}.plist"
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink():raise ValueError('Job file must not be a symlink')
    if args.install and target.exists():raise FileExistsError('Job already exists; inspect it before replacing')
    target.write_bytes(plistlib.dumps(config));os.chmod(target,0o600)
    if args.install:
        if sys.platform!='darwin':raise ValueError('Installation requires macOS launchd; use your service scheduler on other hosts')
        if not (repo/'.env').is_file():raise ValueError('Configure .env and encryption key first')
        domain=f'gui/{os.getuid()}'
        # Never unload or overwrite another project/user job.
        if subprocess.run(['launchctl','print',domain+'/'+config['Label']],capture_output=True).returncode==0:
            raise ValueError('This project backup job is already loaded')
        subprocess.run(['launchctl','bootstrap',domain,str(target.resolve())],check=True)
        print('Installed per-user backup every 6 hours:',config['Label'])
    else:print('Generated job:',target)


if __name__=='__main__':main()
