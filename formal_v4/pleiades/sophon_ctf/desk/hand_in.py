#!/usr/bin/env python3
"""hand_in.py FLAG : hand one SOPHON{...} string to the Sophon desk and print the reply.
Credentials come from the environment set by hand_in.sh; they are never printed."""
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools')
from gosim_platform import Client, PlatformError
flag = sys.argv[1]
c = Client()
c.login(os.environ['GOSIM_EMAIL'], os.environ['GOSIM_PASSWORD'])
try:
    st, h, raw = c._send('POST', c.url + '/functions/v1/sophon/desk/flag', body={'flag': flag}, headers={'x-sophon-site': '1'})
    print(flag, '->', st, raw.decode('utf-8', 'replace')[:1500])
except PlatformError as e:
    print(flag, '-> ERR', e)
