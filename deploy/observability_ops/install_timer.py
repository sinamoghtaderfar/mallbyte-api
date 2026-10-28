#!/usr/bin/env python3
"""Install/uninstall a per-user host timer, no sudo and no Docker socket mounts."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
user_dir = Path.home() / '.config/systemd/user'
service = 'mallbyte-observability-ops.service'
timer = 'mallbyte-observability-ops.timer'


def main():
    if Path('/.dockerenv').exists():
        raise SystemExit('Install on Docker host, not inside container')
    p = argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--install', action='store_true')
    g.add_argument('--uninstall', action='store_true')
    o=p.parse_args()
    if o.install:
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / service).write_text(f'''[Unit]
Description=MallByte independently-approved Observability restart executor
After=docker.service

[Service]
Type=oneshot
TimeoutStartSec=300
WorkingDirectory={root}
ExecStart={sys.executable} {root / 'deploy/observability_ops/host_runner.py'}
Environment=PATH=/usr/local/bin:/usr/bin:/bin
NoNewPrivileges=true
PrivateTmp=false
''')
        (user_dir / timer).write_text(f'''[Unit]
Description=Poll separately approved MallByte Celery restart requests every minute

[Timer]
OnBootSec=1min
OnUnitInactiveSec=1min
Persistent=true
Unit={service}

[Install]
WantedBy=timers.target
''')
        for cmd in (['systemctl','--user','daemon-reload'],
                    ['systemctl','--user','enable','--now',timer]):
            subprocess.run(cmd,check=True)
        print('Timer enabled. Check: systemctl --user list-timers --all | grep mallbyte-observability')
        print('A user timer normally runs only while the user systemd manager is active.')
        print('For an unattended dedicated host, arrange linger using your host security policy.')
    else:
        subprocess.run(['systemctl','--user','disable','--now',timer],check=False)
        for name in [service,timer]:
            (user_dir/name).unlink(missing_ok=True)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        print('Runner timer removed. Already approved operations remain in DB; review them manually.')

if __name__=='__main__': main()
