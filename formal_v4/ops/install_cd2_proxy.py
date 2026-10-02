#!/usr/bin/env python3
"""Add one authenticated GPU proxy path to the existing CD2 HTTPS site.

Run on CD2 with sudo. The GPU origin remains on loopback and authenticates all
requests. Preserve the existing site, test nginx configuration, and roll back
our insertion if the configuration test fails.
"""
from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess

SITE = Path('/etc/nginx/sites-enabled/elevatia.cn').resolve()
SNIPPET = Path('/etc/nginx/snippets/gosim-observer-gpu.conf')
INSERTION = '    include /etc/nginx/snippets/gosim-observer-gpu.conf;\n'
ANCHOR = '    location / { try_files $uri $uri/ =404; }'
CONFIG = '''location ^~ /gosim-observer-gpu/ {
    proxy_pass http://127.0.0.1:19926/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host "localhost";
    proxy_set_header Authorization $http_authorization;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
    proxy_send_timeout 10s;
    client_max_body_size 12m;
    access_log off;
}
'''


def main():
    old_site = SITE.read_text()
    old_snippet = SNIPPET.read_text() if SNIPPET.exists() else None
    if INSERTION not in old_site and old_site.count(ANCHOR) != 1:
        raise RuntimeError('existing site layout changed; review before editing')
    backup = Path('/var/backups/gosim-observer-relay')
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    shutil.copy2(SITE, backup / ('elevatia.cn.' + stamp))
    SNIPPET.write_text(CONFIG)
    if INSERTION not in old_site:
        SITE.write_text(old_site.replace(ANCHOR, INSERTION + ANCHOR))
    try:
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    except Exception:
        SITE.write_text(old_site)
        if old_snippet is None:
            SNIPPET.unlink(missing_ok=True)
        else:
            SNIPPET.write_text(old_snippet)
        raise
    print('CD2 HTTPS GPU path installed; loopback origin port 19926')


if __name__ == '__main__':
    main()
