import re, zipfile, json, glob, sys
M = {'.-':'A','-...':'B','-.-.':'C','-..':'D','.':'E','..-.':'F','--.':'G','....':'H','..':'I','.---':'J','-.-':'K','.-..':'L','--':'M','-.':'N','---':'O','.--.':'P','--.-':'Q','.-.':'R','...':'S','-':'T','..-':'U','...-':'V','.--':'W','-..-':'X','-.--':'Y','--..':'Z',
     '-----':'0','.----':'1','..---':'2','...--':'3','....-':'4','.....':'5','-....':'6','--...':'7','---..':'8','----.':'9','-..-.':'/','---...':':','-....-':'-','.-.-.-':'.','--..--':','}
PAIRS = [('♪', '♫'), ('·', '—'), ('嘀', '嗒'), ('口', '曰'), ('短', '长'), ('ti', 'TA'), ('.', '-'), ('•', '–')]
def decode(s):
    for a, b in PAIRS:
        if s.count(a) + s.count(b) >= 8 and (a in s and b in s):
            t = s.replace(b, '-').replace(a, '.') if a != '.' else s
            words = re.split(r'\s*/\s*', t)
            out = []
            for w in words:
                toks = re.findall(r'[.\-]+', w)
                out.append(''.join(M.get(k, '?') for k in toks))
            return ' '.join(out)
    return None
for zf in glob.glob('/home/shu/kamico/observer/work/online/c28b_49fd/*/result.zip'):
    z = zipfile.ZipFile(zf)
    nm = [n for n in z.namelist() if n.endswith('messages.jsonl')]
    if not nm: continue
    wf = json.loads(z.read([n for n in z.namelist() if n.endswith('workflow_result.json')][0]))
    n = 0
    for l in z.read(nm[0]).decode().splitlines():
        if '"observation_request"' not in l: continue
        m = json.loads(l)
        for e in (m.get('reason') or '').split('\n'):
            if any(k in e for k in ('摩斯', '换个写法')):
                d = decode(e.split('：', 1)[-1])
                n += 1
                if n <= 6:
                    print(wf['scenario'], m['issued_at_utc'][:10], '|', d, '|', e[:60])
    print(wf['scenario'], 'morse entries', n)
