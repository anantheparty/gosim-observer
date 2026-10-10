#!/usr/bin/env python3
"""sophon_flag.py FLAG : hand one flag to the Sophon desk and print the reply (never prints credentials)."""
import json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '/home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools')
from gosim_platform import Client, PlatformError
c = Client()
c.login(os.environ['GOSIM_EMAIL'], os.environ['GOSIM_PASSWORD'])
flag = sys.argv[1]
try:
    st, h, raw = c._send('POST', c.url + '/functions/v1/sophon/desk/flag', body={'flag': flag}, headers={'x-sophon-site': '1'})
    print(flag, '->', st, raw.decode('utf-8', 'replace')[:1500])
except PlatformError as e:
    print(flag, '-> ERR', e)
