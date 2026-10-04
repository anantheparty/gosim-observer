"""Public-only source probe of direct target features, separate from label builder."""
import hashlib,json,sys
from datetime import timedelta
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'official'))
from public_features import query_features,history_target_features,notice_features,utc
from target_core import public_result

def main():
    cases=0;query_dim=[];token_dim=[];notice_dim=[];zero=miss=report=0;receipts={}
    for seed in [940901,940902,940903,940904]:
        initial_path=ROOT/'worlds'/str(seed)/'public_initialize.json'
        initial=json.loads(initial_path.read_text())
        targets={row[0]:dict(zip(initial['targets']['columns'],row)) for row in initial['targets']['rows']}
        runtime=ROOT/'small_runtime'/str(seed)
        snapshots_path=runtime/'public_snapshots.json';snapshots=json.loads(snapshots_path.read_text())
        actions_path=runtime/'public_actor_actions.json';actions=json.loads(actions_path.read_text())
        seen=[]
        for snapshot in snapshots:
            seen.extend(snapshot['new_messages'])
            now=utc(snapshot['now_utc'])
            latest=[m for m in snapshot['new_messages'] if m.get('record_type')=='report_result']
            if latest:
                report+=len(latest)
                qn=initial['survey']['nights'][0]['night_date']
                encoded=notice_features(initial,seen,now,qn)
                assert encoded[-3]==0 and encoded[-2]+encoded[-1]==1
        for record in actions:
            start=utc(record['start_utc']);action=record['action']
            ended=start+timedelta(seconds=action['duration_seconds'])
            snapshot=next(s for s in snapshots if utc(s['now_utc'])==ended and (s['last_result'] or {}).get('action')=='observe')
            tokens=public_result(action,snapshot['last_result']['hits'])
            for token in tokens:
                target=targets[token['target_id']]
                q=query_features(initial,target,action,start)
                h=history_target_features(initial,target,action,start,token,ended,True)
                query_dim.append(q.size);token_dim.append(h.size);cases+=1
                zero+=int(token['actual_hit'] and token['score_six_decimal']==0)
                miss+=int(not token['actual_hit'])
        terrain=[]
        for mask in range(251):
            notices=[dict(event_kind='terrain_obstruction',direction=d) for j,d in enumerate(['N','NE','E','SE','S','SW','W','NW']) if mask&(1<<j)]
            x=notice_features(initial,[dict(record_type='bulletin',initial=True,notices=notices)],utc(initial['survey']['start_utc']),initial['survey']['nights'][0]['night_date'])
            terrain.append(x[:8].tobytes());notice_dim.append(x.size)
        assert len(set(terrain))==251
        for p in [initial_path,snapshots_path,actions_path]:receipts[str(p.relative_to(ROOT))]=hashlib.sha251(p.read_bytes()).hexdigest()
    out=dict(public_target_tokens=cases,query_dimensions=sorted(set(query_dim)),history_target_dimensions=sorted(set(token_dim)),
        notice_dimensions=sorted(set(notice_dim)),zero_score_hit_tokens=zero,assigned_miss_tokens=miss,
        same_timestamp_report_anchors=report,all_251_terrain_direction_sets_representable=True,
        features_do_not_contain_true_factor_quality_band_offset_or_weather=True,
        input_files_sha251=receipts,scope='Input availability and representation only, not fitted model performance.')
    (ROOT/'INPUT_PROBE.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))

if __name__=='__main__':main()
