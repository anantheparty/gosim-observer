"""Exact public-score feasibility for constant C/E within one weather slot.

This offline audit uses official L1/L2 truth only after inference for validation.
No production imports, fitting priors, hidden features, seeds, network, or LLM.
"""
from __future__ import annotations

import bisect
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstream/gosim-observer-examples/runner"))
from challenge.v4_fiber_map import radec_to_altaz
from challenge.v4_scorer import lunar_quality_factor
from challenge.tile_geometry_simulator import _normalized_airmass

PROGRAMS = ("DARK", "BRIGHT", "BACKUP")
MULT = {"DARK": 1.2, "BRIGHT": 1.12, "BACKUP": 1.06}


def feasible(records):
    """Enumerate exact C intervals and intersect rounded score constraints on Z.

    Record fields: score, weight, a=flux*duration*H/450, H, program.
    Efficiency range [0,1] is conservative. Intervals use their interior pattern;
    isolated threshold endpoints belong to the upper interval by scorer convention.
    """
    edges = sorted({0.0, *(t / r["H"] for r in records for t in (.4, .65))})
    edges.append(math.inf)
    out = []
    for left, right in zip(edges, edges[1:]):
        mid = (left + right) / 2 if math.isfinite(right) else left + 1
        zlo, zhi = 0.0, math.inf
        pattern = []
        for r in records:
            q = mid * r["H"]
            band = "DARK" if q >= .65 else "BRIGHT" if q >= .4 else "BACKUP"
            m = MULT[r["program"]] if band == r["program"] else 1.0
            pattern.append(m)
            lo = max(0.0, r["score"] - .500001e-6) / r["weight"]
            hi = (r["score"] + .500001e-6) / r["weight"]
            if lo > m:
                zlo, zhi = 1.0, 0.0
                break
            zlo = max(zlo, lo / (m * r["a"]))
            if hi < m:
                zhi = min(zhi, hi / (m * r["a"]))
        # Z=C*E, with E<=1, requires C>=Z. At the infimum a limit is enough
        # for an upper bound; an isolated excluded endpoint cannot lower E_upper.
        clo = max(left, zlo)
        if zlo <= zhi and clo < right:
            eup = min(1.0, zhi / clo) if clo > 0 else 1.0
            out.append({"C_lower": clo, "C_upper": right,
                        "Z_lower": zlo, "Z_upper": zhi,
                        "E_upper": eup, "multipliers": pattern})
    return out


def contains(states, c, e):
    return any(s["C_lower"] - 1e-10 <= c <= s["C_upper"] + 1e-10
               and s["Z_lower"] - 1e-10 <= c * e <= s["Z_upper"] + 1e-10
               for s in states)


def possible_bands(states, h):
    boundaries=(0,.4/h,.65/h,math.inf)
    bands=('BACKUP','BRIGHT','DARK')
    return {band for left,right,band in zip(boundaries,boundaries[1:],bands)
            if any(max(left,s['C_lower'])<min(right,s['C_upper']) for s in states)}


def synthetic_checks():
    def rec(c, e, h, p, f=.5, t=60, w=1):
        a = f * t * h / 450
        b = "DARK" if c*h >= .65 else "BRIGHT" if c*h >= .4 else "BACKUP"
        m = MULT[p] if p == b else 1
        return dict(score=round(w*min(a*c*e, 1)*m, 6), weight=w, a=a, H=h, program=p)
    checks=[]
    for c in (.3,.5,.8,1.2):
        for e in (.4,.65,.95):
            for h1,h2 in ((.8,.8),(.64,.96),(.9,.7)):
                rs=[rec(c,e,h1,"DARK"),rec(c,e,h2,"BRIGHT",f=4,t=120,w=.3)]
                checks.append(contains(feasible(rs),c,e))
    # Deliberately low scores have no score/weight>1 witness. Both programs
    # nevertheless eliminate a normal-efficiency alias.
    rs=[rec(1,.45,.8,"DARK"),rec(1,.45,.8,"BRIGHT")]
    before=feasible(rs[:1]); after=feasible(rs)
    # A change of E across a slot invalidates the common-state assumption.
    broken=feasible([rec(1,.45,.8,"DARK"),rec(1,.95,.8,"BRIGHT")])
    assert all(checks) and max(s["E_upper"] for s in before) == 1
    assert max(s["E_upper"] for s in after) < .56 and not broken
    return {"true_states_retained":sum(checks),"synthetic_cases":len(checks),
            "single_E_upper":max(s["E_upper"] for s in before),
            "pair_E_upper":max(s["E_upper"] for s in after),
            "different_slot_E_change_infeasible":not broken}


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def readcsv(path):
    with path.open(newline="") as f:return list(csv.DictReader(f))


def geometry(target, start, duration, site, score_config):
    end=start+timedelta(seconds=duration); cursor=start; total=0; altmin=90
    while cursor<end:
        piece_end=min(end,cursor+timedelta(seconds=120)); mid=cursor+(piece_end-cursor)/2
        alt,_=radec_to_altaz(float(target['ra_deg']),float(target['dec_deg']),mid,
                           site['latitude_deg'],site['longitude_deg'])
        lunar=lunar_quality_factor(float(target['ra_deg']),float(target['dec_deg']),mid,site,score_config)
        total+=(piece_end-cursor).total_seconds()*lunar/_normalized_airmass(alt)**.6
        altmin=min(altmin,alt);cursor=piece_end
    return total/duration,altmin


def audit(card, trace):
    base=ROOT/'upstream/gosim-observer-examples/local-cards'/card
    config=json.loads((base/'config/v4_scenario.json').read_text())
    score_config=json.loads((base/'config/v4_score_config.json').read_text())
    targets={r['target_id']:r for r in readcsv(base/'public/targets.csv')}
    slots=readcsv(base/'truth/v4_slots.csv'); starts=[utc(r['timestamp_utc']) for r in slots]
    truth={r['slot_id']:r for r in readcsv(base/'truth/v4_weather_truth.csv')}
    bulletins={r['slot_id']:r for r in map(json.loads,(base/'public/v4_bulletins.jsonl').read_text().splitlines())}
    obs=defaultdict(list)
    for r in readcsv(trace/'observations.csv'):obs[int(r['observe_index'])].append(r)
    faults=[r for r in readcsv(base/'truth/v4_events.csv') if r['event_type']=='instrument_fault']
    report_results={r['issued_at_utc']:r for r in map(json.loads,(trace/'messages.jsonl').read_text().splitlines())
                    if r.get('record_type')=='report_result'}
    repaired=set();counts=defaultdict(int); groups={}; details=[]; probes=[]; seen_slots=set()
    fault_steps=[]; natural_band_reductions=[]
    for d in readcsv(trace/'decisions.csv'):
        if d['action']=='report':
            if report_results.get(d['start_utc'],{}).get('correct'):
                for fault in faults:
                    if utc(fault['actual_start_utc'])<=utc(d['start_utc'])<utc(fault['actual_end_utc']):
                        repaired.add(fault['event_id'])
            groups.clear();continue
        if d['action']!='observe':continue
        counts['observe']+=1
        start,end=utc(d['start_utc']),utc(d['end_utc']);duration=float(d['duration_seconds'])
        k=bisect.bisect_right(starts,start)-1
        if k<0 or end>starts[k]+timedelta(seconds=900):
            counts['cross_slot_excluded']+=1;continue
        slot=slots[k]['slot_id'];notices=bulletins[slot]['notices']
        if any(n['event_kind']!='terrain_obstruction' for n in notices):
            counts['notice_excluded']+=1;continue
        rs=[];alts=[]
        for r in obs[int(d['observe_index'])]:
            t=targets[r['target_id']];H,alt=geometry(t,start,duration,config['site'],score_config)
            # Official reference terrain is restricted below50deg. This audit
            # uses65deg as the existing policy's clean high-altitude guard.
            if alt<65 or float(r['score'])<=0:continue
            rs.append(dict(target_id=r['target_id'],score=float(r['score']),weight=float(t['science_weight']),
                           a=float(t['feature_flux'])*duration*H/450,H=H,program=d['program']))
            alts.append(alt)
        if len(rs)<3:
            counts['few_clean_hits_excluded']+=1;continue
        counts['clean_exposures']+=1
        seen_slots.add(slot)
        state=groups.setdefault(slot,{'records':[],'programs':set(),'indices':[],'validated':True})
        state['records']+=rs;state['programs'].add(d['program']);state['indices'].append(int(d['observe_index']))
        one=feasible(rs);joint=feasible(state['records'])
        counts['joint_steps']+=1
        if not joint:
            counts['infeasible_joint_steps']+=1;continue
        tw=truth[slot]
        c=float(tw['transparency'])*float(tw['sky_quality'])/(float(tw['seeing_arcsec'])*.68)
        etrue=float(tw['instrument_efficiency']);active_fault=False
        for fault in faults:
            if utc(fault['actual_start_utc'])<=start<utc(fault['actual_end_utc']):
                if fault['event_id'] in repaired:
                    etrue=min(1,etrue/float(fault['instrument_efficiency_multiplier']))
                else:active_fault=True
        if not any(s['C_lower']-1e-8<=c<=s['C_upper']+1e-8 for s in joint):
            counts['truth_C_excluded']+=1
        if not contains(joint,c,etrue):counts['truth_CE_excluded']+=1
        e_one=max((s['E_upper'] for s in one),default=None)
        e_joint=max(s['E_upper'] for s in joint)
        if len(state['indices'])>1 and len(state['programs'])>1:
            counts['natural_multiprogram_steps']+=1
            one_bands=possible_bands(one,.95);joint_bands=possible_bands(joint,.95)
            if len(joint_bands)<len(one_bands):
                natural_band_reductions.append({'slot':slot,'observe_index':int(d['observe_index']),
                                               'single_bands_at_H_.95':sorted(one_bands),
                                               'joint_bands_at_H_.95':sorted(joint_bands)})
        if active_fault:
            fault_steps.append({'slot':slot,'observe_index':int(d['observe_index']),
                                'E_true':etrue,'E_upper':e_joint,'programs':sorted(state['programs'])})
        if e_one is not None and e_one>=.8 and e_joint<.8:
            details.append({'slot':slot,'observe_index':int(d['observe_index']),
                            'indices':state['indices'][:], 'programs':sorted(state['programs']),
                            'single_E_upper':e_one,'joint_E_upper':e_joint,
                            'C_true':c,'C_interval_count':len(joint),
                            'C_lower':min(s['C_lower'] for s in joint),
                            'C_upper':max(s['C_upper'] for s in joint),
                            'same_current_program':len(state['programs'])==1})
        # Offline feasibility labels for an additional same-target60s observation.
        # Its score is synthetic truth ONLY after the public pre-probe set is built.
        # This is an information-opportunity audit, not executed or a score claim.
        if e_joint>=.8 and end+timedelta(seconds=60)<=starts[k]+timedelta(seconds=900):
            counts['public_probe_eligible']+=1
            for program in PROGRAMS:
                if program==d['program']:continue
                prs=[]
                for r in rs:
                    t=targets[r['target_id']];H,alt=geometry(t,end,60,config['site'],score_config)
                    if alt<65:continue
                    a=float(t['feature_flux'])*60*H/450
                    band='DARK' if c*H>=.65 else 'BRIGHT' if c*H>=.4 else 'BACKUP'
                    m=MULT[program] if program==band else 1
                    prs.append(dict(score=round(r['weight']*min(a*c*etrue,1)*m,6),
                                    weight=r['weight'],a=a,H=H,program=program))
                pj=feasible(state['records']+prs)
                pup=max((s['E_upper'] for s in pj),default=None)
                counts['hypothetical_program_probes']+=1
                if pup is not None and pup<.8:
                    probes.append({'slot':slot,'observe_index':int(d['observe_index']),
                                   'declared_program':d['program'],'probe_program':program,
                                   'pre_E_upper':e_joint,'post_E_upper':pup,'E_true':etrue,
                                   'active_unrepaired_fault_label':active_fault,
                                   'probe_score_sum_label':sum(r['score'] for r in prs),
                                   'existing_single_witness':e_one is not None and e_one<.8})
    counts['clean_slots']=len(seen_slots)
    counts['probe_new_witnesses']=len(probes)
    counts['probe_fault_witnesses']=sum(p['active_unrepaired_fault_label'] for p in probes)
    counts['clean_active_fault_steps']=len(fault_steps)
    counts['natural_future_band_reductions_at_H_.95']=len(natural_band_reductions)
    counts['infeasible_joint_steps']+=0;counts['truth_CE_excluded']+=0;counts['truth_C_excluded']+=0
    return {'card':card,'trace':str(trace),'counts':dict(counts),'new_joint_witnesses':details,
            'hypothetical_probe_witnesses':probes,'active_fault_clean_steps':fault_steps,
            'natural_band_reductions':natural_band_reductions}


def main():
    out=ROOT/'results/band_identification_20261004';out.mkdir(exist_ok=True)
    results={'checks':synthetic_checks(),'audits':[
        audit('L1',ROOT/'results/global_field_20261004/v2/ready_phase_reference/L1'),
        audit('L2',ROOT/'results/objective_graph_20261004/program_pair/control/L2')]}
    (out/'audit.json').write_text(json.dumps(results,indent=2,allow_nan=False))
    print(json.dumps({'checks':results['checks'],'audits':[{'card':r['card'],'counts':r['counts'],
                    'new_witnesses':len(r['new_joint_witnesses']),
                    'first_witnesses':r['new_joint_witnesses'][:3],
                    'first_probe_witnesses':r['hypothetical_probe_witnesses'][:3]} for r in results['audits']]},indent=2))


if __name__=='__main__':main()
