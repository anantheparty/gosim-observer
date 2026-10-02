#!/usr/bin/env python3
"""Add the compatible API facade beside the existing authenticated GPU route."""
from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess

SNIPPET = Path('/etc/nginx/snippets/gosim-observer-gpu.conf')
PREFIX = '''location ^~ /gosim-observer-gpu/v1/ {
    proxy_pass http://127.0.0.1:19928/v1/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host "localhost";
    proxy_set_header Authorization $http_authorization;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
    proxy_send_timeout 10s;
    client_max_body_size 64k;
    access_log off;
}
'''


def main():
    old = SNIPPET.read_text()
    if '/gosim-observer-gpu/v1/' in old:
        raise RuntimeError('adapter route already exists; inspect before updating')
    if 'proxy_pass http://127.0.0.1:19926/;' not in old:
        raise RuntimeError('existing relay changed; inspect before updating')
    backup = Path('/var/backups/gosim-observer-relay')
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    shutil.copy2(SNIPPET, backup / ('gpu-snippet.' + stamp))
    SNIPPET.write_text(PREFIX + old)
    try:
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    except Exception:
        SNIPPET.write_text(old)
        raise
    print('Compatible API installed; existing GPU RPC route preserved')


if __name__ == '__main__':
    main()
