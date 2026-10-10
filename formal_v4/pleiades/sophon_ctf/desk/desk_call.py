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
hdr = {'apikey': c.key, 'Authorization': 'Bearer ' + c.jwt}
if os.environ.get('SOPHON_OMIT_SITE_HEADER') != '1':
    hdr['x-sophon-site'] = '1'
data = None
if body is not None:
    data = json.dumps(json.loads(body)).encode(); hdr['Content-Type'] = 'application/json'
req = urllib.request.Request(c.url + path, data=data, method=method, headers=hdr)
try:
    with c.opener.open(req, timeout=60) as r:
        st, raw, response_headers = r.status, r.read(), r.headers
except urllib.error.HTTPError as e:
    st, raw, response_headers = e.code, e.read(), e.headers
# Response metadata only: never serialize authentication or cookie values.
response_header_names = sorted({k.lower() for k in response_headers.keys()}) if response_headers else []
response_cookie_names = []
for cookie_line in response_headers.get_all('Set-Cookie', []) if response_headers else []:
    match = re.match(r'\s*([A-Za-z0-9_-]{1,80})=', cookie_line)
    if match:
        response_cookie_names.append(match.group(1))
response_flag_codes = set()
for k, v in response_headers.items() if response_headers else []:
    if any(word in k.lower() for word in ('auth', 'cookie', 'token', 'key')):
        continue
    response_flag_codes.update(re.findall(r'SOPHON\{[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{20}\}', v))
text = raw.decode('utf-8', 'replace').replace(c.jwt, '[redacted-jwt]')
text = re.sub(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+', '[redacted-jwt]', text)
print(method, path, body or '', '->', st, text[:4000])
print('Response metadata:', json.dumps({'header_names': response_header_names, 'cookie_names': response_cookie_names, 'flag_codes': sorted(response_flag_codes)}))
with open('/home/shu/kamico/observer/work/sophon_desk/desk_calls.jsonl', 'a') as f:
    f.write(json.dumps({'t': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'method': method, 'path': path, 'body': body, 'status': st, 'reply': text[:8000], 'site_header_present': 'x-sophon-site' in hdr, 'response_header_names': response_header_names, 'response_cookie_names': response_cookie_names, 'response_flag_codes': sorted(response_flag_codes)}, ensure_ascii=False) + '\n')
