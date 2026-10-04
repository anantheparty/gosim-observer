"""Explicit limitations of scalar/marginal mathematical lifting, host only."""
from pathlib import Path
import sys,json
sys.dont_write_bytecode=True
import numpy as np
from datetime import timedelta
from integral_audit import (OFFICIAL,integral_weights,settle,SlotTruth,WeatherTruth,
    altaz_to_radec,datetime,timezone,program_band)
ROOT=Path(__file__).resolve().parent


def main():
    config=json.loads((OFFICIAL/'challenge/reference/v4/v4_score_config.json').read_text())
    site={'latitude_deg':-24.6157,'longitude_deg':-70.3976}
    origin=datetime(2026,11,7,1,tzinfo=timezone.utc)
    start=origin+timedelta(seconds=899);end=start+timedelta(seconds=3600)
    ra,dec=altaz_to_radec(80.,180.,start,site['latitude_deg'],site['longitude_deg'])
    target={'target_id':'fifth','ra_deg':ra,'dec_deg':dec,'feature_flux':.1,'science_weight':1.}
    hb,he=integral_weights(start,end,origin,target,site,config)
    fifth=[]
    for last in [.2,1.4]:
        c=np.array([.65]*4+[last]);z=c*.95;op=np.ones(5)
        gains=[];q=None
        for p in range(3):
            gain,factor,qband=settle(c,z,op,hb,he,.1,1.,0.,3600,p,config)
            gains.append(float(gain));q=float(qband)
        fifth.append({'last_C':last,'first_four_C':c[:4].tolist(),'qband':q,
                      'program':program_band(q,config),'science_by_program':gains,
                      'chosen_program':['DARK','BRIGHT','BACKUP'][int(np.argmax(gains))]})
    assert fifth[0]['chosen_program']!=fifth[1]['chosen_program']
    h=np.array([.72,.75]);center=.4/h.mean()
    first=np.array([center-.06,center+.06]);second=first[::-1]
    qfirst=float((first*h).mean());qsecond=float((second*h).mean())
    assert first.mean()==second.mean()
    assert program_band(qfirst,config)!=program_band(qsecond,config)
    # Same one-slot C/Z and open marginals do not imply the same joint science.
    c=np.array([[.7],[.7]]); z=np.array([[.7],[.07]])
    op_a=np.array([[1.],[0.]]);op_b=np.array([[0.],[1.]])
    joint=[]
    for op in [op_a,op_b]:
        gain,*_=settle(c,z,op,[.75],[.75],.4,1.,.2,900,1,config)
        joint.append(float(gain.mean()))
    assert joint[0]!=joint[1]
    result={'fifth_slot':{'duration':3600,'start_fraction':899,'weather_slots':len(hb),
                         'same_first_four':True,'worlds':fifth},
      'scalar_Cbar_not_sufficient':{'H_by_slot':h.tolist(),'C_paths':[first.tolist(),second.tolist()],
         'same_Cbar':float(first.mean()),'qbands':[qfirst,qsecond],
         'programs':[program_band(qfirst,config),program_band(qsecond,config)],
         'scope':'algebraic weights example; no claim these exact H values came from one official field'},
      'closure_quality_joint_not_marginals':{'C':[.7,.7],'Z':[.7,.07],
            'open_A':[1,0],'open_B':[0,1],'same_C_Z_open_marginals':True,'expected_gain':joint},
      'claim':'existence proofs of missing sufficient information; no actual-card regret or production result'}
    (ROOT/'counterexamples.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__':main()
