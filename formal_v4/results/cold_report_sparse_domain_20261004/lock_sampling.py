"""Freeze generation, geometry, classifier selection and finite validation gates."""
import json,hashlib,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sources=['public_design.py','sparse_world.py','sensor_core.py','build_dataset.py','train.py','report_core.py','check_pilot_operator.py','public_design_cache.pkl','public_design_manifest.json','pilot_operator_checks.json']
out=dict(created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),trial='new sparse public sampling domain; old fixed high-altitude trial immutable',
    splits={'pilot':[810000,810003],'train':[820000,820063],'cal':[830000,830007],'val':[840000,840007],'test':[850000,850015]},
    action_design='L1/L2 public original strong actions and times fixed; newworld does not replan physical actions; not production strong rollout',
    public_feedback='official runner v4_runner.py:820-829: actual hit target_ids and six-decimal scores; no factor/quality/prog_mult/valid input',
    hit_geometry='public assigned candidates -> per-world independent official stress pointing offset -> official start hit and minimum altitude; target H depends only public observed ids and RA/Dec',
    offset_prior='official sha256-v1 v4.stress.pointing_offset; stress enabled in all new worlds; maxabs alt/az .002rad at survey start; earthquake does not alter pointing',
    data_loss='not simulated; actor clears sparse history on public state_resync and falls back faultv1 until support rebuilt; scientific max-factor opportunity only approximated by fixed-path best ledger',
    weather_prior='independent official events/weather/forecasts/bulletins; fault count probabilities0/1/2=.25/.50/.25; quake count uniform0..2; each weather kind count uniform0..3; official terrain/rocket distributions',
    sampling='all public score feedback including zero/saturated; keep token if >=3 observed hit ids, distinct starting slot; random world dropout0,.15,.35; 8 latest tokens retain directional/terrain notices',
    feature_dim=1568,classifier='ordinary CUDA MLP1568-128-128-1 AdamW .0007 1e-4 16epochs; select minimum calNLL; then one cal logit affine LBFGS; seed82191',
    dp='1024 epochs p15 x quake3 x correct_count3 q0/1/2; paired sameworld next score under report vs wait, shrink32; correct publiccount+1 false/waitsame; max2 independent faults; free-only candidate fixed',
    gates=['all official six-decimal scores equal','newworld assigned->actual geometry exact','history observed-ids-only, all-zero feedback retained','report/reset continuation sameworld recomputed','all Krows normalize and count transitions exact','exhaustive small Bellman tree matches','cal/val finite outputs and beats constant-prior NLL','GPU export finite and maxlogit deviation<1e-4','actor public feature adapter matches host fixture','unsupported actor states fallback frozen faultv1','freeze model/package/source before one test domain; test never chooses params'],
    source_sha256={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources})
(ROOT/'SAMPLING_LOCK.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
