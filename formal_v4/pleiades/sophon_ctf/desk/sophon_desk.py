#!/usr/bin/env python3
"""sophon_desk.py METHOD PATH [JSON_BODY] : call one Johnny's-desk route (/functions/v1/sophon/...) as the logged-in
team member from the site (x-sophon-site: 1); prints status and body with any JWT redacted; appends to desk_calls.jsonl."""
import json, os, re, sys, time, urllib.request, urllib.error
sys.dont_write_bytecode = True
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools')
from gosim_platform import Client
method, path = sys.argv[1].upper(), sys.argv[2]
assert path.startswith('/functions/v1/sophon'), 'sophon routes only'
body = sys.argv[3] if len(sys.argv) > 3 else None
c = Client()
c.login(os.environ['GOSIM_EMAIL'], os.environ['GOSIM_PASSWORD'])
hdr = {'apikey': c.key, 'Authorization': 'Bearer ' + c.jwt, 'x-sophon-site': '1'}
data = None
if body is not None:
    data = json.dumps(json.loads(body)).encode(); hdr['Content-Type'] = 'application/json'
req = urllib.request.Request(c.url + path, data=data, method=method, headers=hdr)
try:
    with c.opener.open(req, timeout=60) as r:
        st, raw = r.status, r.read()
except urllib.error.HTTPError as e:
    st, raw = e.code, e.read()
text = raw.decode('utf-8', 'replace').replace(c.jwt, '[redacted-jwt]')
text = re.sub(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+', '[redacted-jwt]', text)
print(method, path, body or '', '->', st, text[:4000])
with open('/home/shu/kamico/observer/work/sophon_desk/desk_calls.jsonl', 'a') as f:
    f.write(json.dumps({'t': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'method': method, 'path': path, 'body': body, 'status': st, 'reply': text[:8000]}, ensure_ascii=False) + '\n')
