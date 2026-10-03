#!/usr/bin/env python3
"""Reconstruct frozen candidate graphs; no new strategy search or tuning."""
import json, math, time
from pathlib import Path
import probe as m

OUT=Path(__file__).resolve().parent
def main():
    begun=time.perf_counter();cases=[];maximum_error=0.
    for path in sorted(p for p in OUT.glob('L[12]_*.json') if not p.stem.endswith('_graph')):
        x=json.loads(path.read_text());root,cfg,fiber,scoring,targets,nights,grid,initial=m.public(x['card'])
        weather=m.conditional_weather(nights[0]);p=m.CandidateGeometryPlanner(initial)
        rows=[]
        for block in x['blocks']:
            es=m.all_edges(block['action'],m.utc(block['start_utc']),weather,cfg,grid,scoring,targets,p.eq_vectors)
            rows.extend(es[f] for f in range(grid.n_fibers))
        idx={t['target_id']:i for i,t in enumerate(targets)}
        arrays={k:[idx[t] if t is not None else None for t in a] for k,a in x['assignments'].items()}
        for name,a in arrays.items():
            value=m.ledger_value(a,rows,targets,scoring)
            for k,v in value.items():maximum_error=max(maximum_error,abs(v-x['values'][name][k]))
        compact=sorted({t for row in rows for t in row});rev={t:i for i,t in enumerate(compact)}
        weights=[{rev[t]:s+50*(targets[t]['required'] and f>=.5) for t,(f,s) in row.items()} for row in rows]
        mm,core=m.hungarian(weights,len(compact));flow=[compact[t] if t is not None else None for t in mm]
        assert flow==arrays['flow_once'];assert abs(core-x['flow_core_weight'])<1e-9
        changes=[]
        for r,(a,b) in enumerate(zip(arrays['sequential'],arrays['flow_refill'])):
            if a==b:continue
            def detail(t):
                if t is None:return None
                f,s=rows[r][t]
                return dict(target_id=targets[t]['target_id'],factor=f,score=s,required=targets[t]['required'])
            changes.append(dict(resource=r,exposure=r//16,fiber=r%16,start_utc=x['blocks'][r//16]['start_utc'],
                                sequential=detail(a),flow=detail(b)))
        signed={k:x['values']['flow_refill'][k]-x['values']['sequential'][k] for k in x['values']['sequential']}
        all_alignment=[]
        for t in compact:
            qual=[s for row in rows for i,(f,s) in row.items() if i==t and f>=.5]
            nonqual=[s for row in rows for i,(f,s) in row.items() if i==t and f<.5]
            if qual and nonqual and max(nonqual)>min(qual)+1e-12:all_alignment.append(targets[t]['target_id'])
        graph=dict(target_ids=[targets[t]['target_id'] for t in compact],
                   rows=[dict(resource=r,exposure=r//16,fiber=r%16,edges=[[rev[t],f,s] for t,(f,s) in sorted(row.items())]) for r,row in enumerate(rows)])
        m.dump(OUT/(path.stem+'_graph.json'),graph)
        cases.append(dict(case=path.name,flow_minus_sequential=signed,changes=changes,
                          first_action_changes=sum(c['resource']<16 for c in changes),
                          all_targets_witness_alignment_failures=all_alignment))
    result=dict(schema='cold-matching-graph-audit-v1',cases=cases, maximum_official_value_reconstruction_error=maximum_error,
                seconds=time.perf_counter()-begun,all_future_hidden_reads=0,
                statement='reconstructs the predeclared eight frozen synthetic condition domains; not new search or real season evidence')
    assert maximum_error<1e-9
    m.dump(OUT/'AUDIT.json',result)
    print(json.dumps(dict(maximum_error=maximum_error,seconds=result['seconds'],first_action_changes=sum(c['first_action_changes'] for c in cases))))
if __name__=='__main__':main()
