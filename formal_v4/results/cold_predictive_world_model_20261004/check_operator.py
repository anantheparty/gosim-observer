"""Independent official scorer/closure/program/cap/best operation verification."""
import sys,json,math
from pathlib import Path
from datetime import datetime,timedelta,timezone
import numpy as np
from predictive_core import utility_samples
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'official'))
from challenge.v4_scorer import SlotTruth,WeatherTruth,score_target_exposure,program_band
from challenge.tile_geometry_simulator import _normalized_airmass

def main():
    rng=np.random.default_rng(8014)
    config=json.loads((ROOT/'official/challenge/reference/v4/v4_score_config.json').read_text())
    config.pop('lunar_model',None)
    maximum=0.;cases=0
    start0=datetime(2026,10,10,0,0,tzinfo=timezone.utc)
    for trial in range(300):
        fractional=float(rng.integers(0,900));duration=int(rng.integers(60,2700))
        st=start0+timedelta(seconds=fractional);en=st+timedelta(seconds=duration)
        c=rng.uniform(.15,1.6,4);e=rng.uniform(.2,1.,4);op=rng.random(4)>.1
        truths=[SlotTruth(str(k),start0+timedelta(seconds=k*900),start0+timedelta(seconds=(k+1)*900),bool(op[k]),1.,c[k]*config['q0'],1.,e[k]) for k in range(4)]
        weather=WeatherTruth(truths,[]);segments=list(weather.segments(st,en))
        alt=float(rng.uniform(55,89));h=_normalized_airmass(alt)**(-float(config['airmass_exponent']))
        w=rng.uniform(.3,1.7,16);flux=rng.lognormal(-.7,.7,16);best=rng.uniform(0.,1.,16)*w
        program=int(rng.integers(3));programname=['DARK','BRIGHT','BACKUP'][program]
        seconds=np.asarray([max(0.,min(duration+fractional,(k+1)*900)-max(fractional,k*900)) for k in range(4)])
        gain,factor,qband=utility_samples(c[None,:],(c*e)[None,:],op[None,:],w,flux,best,np.full((4,16),h),seconds,duration,program)
        official=[]
        for j in range(16):
            target={'target_id':str(j),'feature_flux':float(flux[j]),'science_weight':float(w[j])}
            bandq=weather.band_quality(st,en,config,lambda _:alt)
            band=program_band(bandq,config)
            multiplier=config['program']['multipliers'][programname] if band==programname else config['program']['mismatch_multiplier']
            result=score_target_exposure(target,segments,[],weather,duration,multiplier,config,st,lambda _:(alt,0.))
            maximum=max(maximum,abs(result.factor-factor[0,j]),abs(bandq-qband[0,j]))
            official.append(max(0.,result.score-best[j]));cases+=1
        maximum=max(maximum,abs(sum(official)-gain[0]))
    # A distributional decision can change even with unchanged quality mean.
    c=np.array([[.35]*4,[.85]*4]);z=.95*c;opened=np.ones((2,4));seconds=np.array([900.,0,0,0])
    expected=[];plug=[]
    for p in range(3):
        expected.append(float(utility_samples(c,z,opened,[1],[.45],[.15],np.ones((4,1)),seconds,900,p)[0].mean()))
        plug.append(float(utility_samples(c.mean(0)[None,:],z.mean(0)[None,:],opened[:1],[1],[.45],[.15],np.ones((4,1)),seconds,900,p)[0].mean()))
    result={'official_target_cases':cases,'maximum_abs_error':float(maximum),'official_mesh_gate':bool(maximum<1e-10),
            'shared_weather_samples':True,'sample_prefix_is_independent_of_candidate_duration':True,
            'distribution_vs_mean_program_expected':expected,'distribution_vs_mean_program_plugin':plug,
            'different_program_optimum':int(np.argmax(expected))!=int(np.argmax(plug))}
    (ROOT/'operator_gate.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
