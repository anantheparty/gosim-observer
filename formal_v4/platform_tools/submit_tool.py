#!/usr/bin/env python3
"""Write-capable platform tool: upload a project ZIP, wait for preparation, approve, start an online evaluation,
poll and download results. Credentials from GOSIM_EMAIL / GOSIM_PASSWORD (never written to disk).

usage:
  submit_tool.py upload  --zip FILE --title TITLE            -> prints revision_id (uses 1 of 40 preparations/day)
  submit_tool.py wait    --revision ID                       -> polls until reviewable/failed
  submit_tool.py approve --revision ID                       -> confirms (no quota)
  submit_tool.py evaluate --revision ID [--repeat]           -> starts an online evaluation (1 of 40/day)
  submit_tool.py status  [--batch ID]                        -> batches and card scores
  submit_tool.py fetch   --batch ID --out DIR                -> per-card result ZIPs + agent logs
  submit_tool.py full    --zip FILE --title TITLE            -> upload + wait + approve + evaluate
  submit_tool.py env                                         -> team variables: names, flags and hints only
  submit_tool.py evidence --revision ID --notes-file FILE    -> architecture / reproduction notes on the submission
  submit_tool.py setvar  --name NAME --from-env VAR [--plain] -> save a team variable (value read from the
                                                                environment, never from the command line);
                                                                tagged as a model variable
Evaluations run without the team's model variables (no_model) unless --with-model is given.
"""
import os
import argparse
import json
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gosim_platform import Client, PlatformError  # noqa: E402

ONLINE_PHASE = '049d6029-343d-4d16-80d5-94b56b350301'


class WriteClient(Client):
    def portal_w(self, action, **fields):
        res = self._json('POST', '/functions/v1/observer-portal', body={'action': action, **fields})
        if isinstance(res, dict) and res.get('error'):
            raise PlatformError(400, str(res['error']), '/functions/v1/observer-portal:' + action)
        return res.get('data') if isinstance(res, dict) else res

    def upload_zip(self, path: Path):
        info = self.portal_w('upload', purpose='source')
        up_path, token = info['path'], info['token']
        boundary = uuid.uuid4().hex
        data = path.read_bytes()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="cacheControl"\r\n\r\n3600\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name=""; filename="x.zip"\r\n'
                f'Content-Type: application/zip\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        url = (f'{self.url}/storage/v1/object/upload/sign/observer-staging/{urllib.parse.quote(up_path)}'
               f'?token={urllib.parse.quote(token)}')
        self._send('PUT', url, data=body, headers={'x-upsert': 'false',
                                                   'Content-Type': f'multipart/form-data; boundary={boundary}'})
        return info['id']


def find_revision(lst, rid):
    for p in lst.get('projects', []) or []:
        for r in p.get('observer_revisions', []) or []:
            if r.get('id') == rid:
                return r
    return None


def cmd_upload(c, a):
    upload_id = c.upload_zip(Path(a.zip))
    for attempt in range(10):
        try:
            res = c.portal_w('submit_zip', title=a.title[:100], upload_id=upload_id)
            break
        except PlatformError as exc:
            if 'upload_not_finished' in str(exc):
                time.sleep(3)
                continue
            raise
    print(json.dumps(res))
    return res['revision_id']


def cmd_wait(c, rid, timeout=1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = find_revision(c.portal('list'), rid)
        st = r.get('status') if r else None
        print(time.strftime('%H:%M:%S'), 'revision', rid[:8], st, flush=True)
        if st in ('reviewable', 'approved', 'failed', 'withdrawn'):
            return r
        time.sleep(20)
    raise SystemExit('timeout waiting for preparation')


def cmd_approve(c, rid):
    r = find_revision(c.portal('list'), rid)
    if not r:
        raise SystemExit('revision not found')
    if r.get('status') == 'approved':
        print('already approved')
        return
    digest = r.get('approval_digest')
    pt = r.get('public_test') or {}
    print('public_test', json.dumps(pt)[:300])
    res = c.portal_w('approve', revision_id=rid, digest=digest)
    print(json.dumps(res)[:500])


def cmd_evaluate(c, rid, repeat=False, phase=None, with_model=False):
    fields = {'phase_id': phase or ONLINE_PHASE, 'revision_id': rid}
    if not with_model:
        fields['no_model'] = True
    if repeat:
        fields['confirm_repeat'] = True
    res = c.portal_w('evaluate', **fields)
    print(json.dumps(res))
    return res.get('batch_id')


def _env_view(te):
    """Team environment without any value: names, flags, hints, mode."""
    def strip(o):
        if isinstance(o, dict):
            return {k: ('<hidden>' if k in ('value', 'plain', 'encrypted', 'ciphertext') else strip(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    return strip(te)


def cmd_env(c):
    print(json.dumps(_env_view(c.portal_w('team_environment')), ensure_ascii=False, indent=1, default=str))


def cmd_setvar(c, name, from_env, plain=False):
    value = os.environ.get(from_env or '', '')
    if not value:
        raise SystemExit(f'environment variable {from_env!r} is empty')
    res = c.portal_w('save_team_variable', name=name, value=value, secret=not plain, model=True)
    value = ''
    print(json.dumps(_env_view(res), ensure_ascii=False, indent=1, default=str)[:3000])


def cmd_evidence(c, rid, notes_file):
    notes = Path(notes_file).read_text(encoding='utf-8').strip()
    if not notes or len(notes) > 8000:
        raise SystemExit('notes must be 1..8000 characters')
    print(json.dumps(c.portal_w('evidence', revision_id=rid, notes=notes, code_url='')))


def cmd_status(c, batch=None, limit=6):
    lst = c.portal('list')
    names = {}
    for p in lst.get('projects', []) or []:
        for r in p.get('observer_revisions', []) or []:
            names[r['id']] = (r.get('title') or p.get('title') or '')[:40]
    out = []
    for b in (lst.get('batches') or [])[:50]:
        if batch and not b['id'].startswith(batch):
            continue
        runs = b.get('observer_runs') or []
        cards = {}
        for r in runs:
            slug = r.get('scenario_slug') or r.get('scenario_id', '')[:6]
            ss = r.get('score_summary') or {}
            cards[slug] = (r.get('status'), r.get('score'), ss.get('required_missing') if isinstance(ss, dict) else None,
                           ss.get('termination_reason') if isinstance(ss, dict) else None,
                           ss.get('accounted_wallclock_seconds') if isinstance(ss, dict) else None)
        out.append({'batch': b['id'][:8], 'status': b.get('status'), 'phase': (b.get('phase_id') or '')[:8],
                    'rev': names.get(b.get('revision_id'), b.get('revision_id', '')[:8]), 'created': b.get('created_at'),
                    'mean': b.get('score'), 'cards': cards})
        if len(out) >= limit:
            break
    print(json.dumps(out, indent=1, default=str))
    print('quota', json.dumps(lst.get('quota'), default=str)[:400])
    return out


def cmd_fetch(c, batch, out):
    lst = c.portal('list')
    for b in lst.get('batches') or []:
        if not b['id'].startswith(batch):
            continue
        for r in b.get('observer_runs') or []:
            slug = r.get('scenario_slug') or r.get('scenario_id')
            d = Path(out) / str(slug)
            d.mkdir(parents=True, exist_ok=True)
            try:
                url = c.portal('download_result', run_id=r['id'])
                url = url.get('url') if isinstance(url, dict) else url
                (d / 'result.zip').write_bytes(c.get_url(url))
            except Exception as exc:
                print('download failed', slug, exc)
            try:
                log = c.portal('agent_log', run_id=r['id'], full=True)
                (d / 'agent_log.json').write_text(json.dumps(log, default=str))
            except Exception as exc:
                print('log failed', slug, exc)
            (d / 'run.json').write_text(json.dumps(r, default=str, indent=1))
        print('fetched', batch, '->', out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd')
    ap.add_argument('--zip')
    ap.add_argument('--title')
    ap.add_argument('--revision')
    ap.add_argument('--batch')
    ap.add_argument('--out')
    ap.add_argument('--repeat', action='store_true')
    ap.add_argument('--phase', default=ONLINE_PHASE, help='phase id (default: online)')
    ap.add_argument('--with-model', action='store_true', help='evaluate with the team model variables')
    ap.add_argument('--name')
    ap.add_argument('--from-env')
    ap.add_argument('--plain', action='store_true', help='store the variable as plain text (not secret)')
    ap.add_argument('--notes-file')
    a = ap.parse_args()
    c = WriteClient()
    c.login()
    if a.cmd == 'upload':
        cmd_upload(c, a)
    elif a.cmd == 'wait':
        r = cmd_wait(c, a.revision)
        print(json.dumps({k: r.get(k) for k in ('status', 'error', 'public_test')}, default=str)[:800])
    elif a.cmd == 'approve':
        cmd_approve(c, a.revision)
    elif a.cmd == 'evaluate':
        cmd_evaluate(c, a.revision, a.repeat, a.phase, a.with_model)
    elif a.cmd == 'evidence':
        cmd_evidence(c, a.revision, a.notes_file)
    elif a.cmd == 'env':
        cmd_env(c)
    elif a.cmd == 'setvar':
        cmd_setvar(c, a.name, a.from_env, a.plain)
    elif a.cmd == 'status':
        cmd_status(c, a.batch)
    elif a.cmd == 'fetch':
        cmd_fetch(c, a.batch, a.out)
    elif a.cmd == 'full':
        rid = cmd_upload(c, a)
        r = cmd_wait(c, rid)
        if r.get('status') != 'reviewable':
            print(json.dumps(r, default=str)[:1500])
            raise SystemExit('preparation failed')
        cmd_approve(c, rid)
        print('batch', cmd_evaluate(c, rid, with_model=a.with_model))
    else:
        raise SystemExit('unknown command')


if __name__ == '__main__':
    main()
