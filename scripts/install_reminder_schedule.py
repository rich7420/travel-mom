"""Generate or install this workspace's independent macOS reminder supervisor."""

import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def job_config(repo, python):
    repo = Path(repo).resolve()
    label = (
        "com.travelmom.reminders." + hashlib.sha256(str(repo).encode()).hexdigest()[:10]
    )
    return {
        "Label": label,
        "ProgramArguments": [
            str(Path(python).absolute()),
            "-m",
            "scripts.run_reminders",
            "--loop",
            "--env-file",
            str(repo / ".env"),
        ],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(repo / "data" / "reminder-service.log"),
        "StandardErrorPath": str(repo / "data" / "reminder-service-error.log"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    config = job_config(repo, sys.executable)
    if args.install:
        if sys.platform != "darwin":
            raise ValueError("Installation requires macOS launchd")
        if not (repo / ".env").is_file():
            raise ValueError("Configure .env and encryption key first")
        domain = f"gui/{os.getuid()}"
        if (
            subprocess.run(
                ["launchctl", "print", domain + "/" + config["Label"]],
                capture_output=True,
            ).returncode
            == 0
        ):
            raise ValueError("This project reminder job is already loaded")
    target = (
        Path(args.output)
        if args.output
        else (
            Path.home() / "Library" / "LaunchAgents" if args.install else repo / "data"
        )
        / f"{config['Label']}.plist"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(target):
        raise FileExistsError("Refusing existing job file")
    with target.open("xb") as handle:
        handle.write(plistlib.dumps(config))
    os.chmod(target, 0o600)
    if args.install:
        subprocess.run(
            ["launchctl", "bootstrap", domain, str(target.resolve())], check=True
        )
    print("Installed job:" if args.install else "Generated job:", target)


if __name__ == "__main__":
    main()
