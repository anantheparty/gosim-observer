"""Prospectively frozen offline PRO6000 full/current quotient-density trial."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import copy,hashlib,json,math,sys,time,traceback
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import torch
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import model
from decision import controls,prepare_original_rows
import gpu_math
from numerical_fixture import audit_fixture
HISTORY_DIM=5768
CONTEXT_DIM=5913

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
def check_source():
    lock=json.loads((HERE/'SOURCE_FREEZE.json').read_text())
    assert lock['parent_source_freeze_sha256']==sha(ROOT/'SOURCE_FREEZE.json')
    parent=json.loads((ROOT/'SOURCE_FREEZE.json').read_text())
    for name,value in parent['files'].items():assert sha(ROOT/name)==value
    for name,value in lock['files'].items():assert sha(HERE/name)==value
    return sha(HERE/'SOURCE_FREEZE.json')

def load_world(base,role,index):
    path=base/'datasets'/role/f'{index}.npz'
    with np.load(path,allow_pickle=False) as z:d={k:z[k] for k in z.files}
    ctx=np.concatenate([d['ht'].reshape(32,-1),d['hn'].reshape(32,-1),d['hm'].reshape(32,-1),d['cn'],d['cm']],axis=1)
    assert ctx.shape==(32,CONTEXT_DIM) and d['q'].shape[1]==50
    assert np.isfinite(ctx).all() and np.isfinite(d['q']).all() and np.isfinite(d['R']).all()
    assert np.all(d['R']>=0) and np.all(d['R'][d['R']>0]>1e-30)
    assert np.all(d['scale']>0) and np.all(d['best']>=0)
    receipt=json.loads((base/'datasets'/role/f'{index}_receipt.json').read_text())
    assert receipt['budget_pass'] and receipt['split']==role and receipt['world_index']==index
    assert receipt['npz_sha256']==sha(path)
    card=receipt['public_catalog'];initial=json.loads((ROOT/'public_initializers'/f'{card}.json').read_text())
    ids=[r[initial['targets']['columns'].index('target_id')] for r in initial['targets']['rows']]
    cases=json.loads((base/'datasets'/role/f'{index}_cases.json').read_text())
    actions=json.loads((base/'datasets'/role/f'{index}_point_actions.json').read_text())
    prepare_original_rows(d,cases,actions,ids)
    return dict(data=d,context=ctx,cases=cases,actions=actions,scoring=initial['scoring'],receipt=receipt,
                index=index,role=role,npz_sha256=sha(path))

def load_split(base,role,n):return [load_world(base,role,i) for i in range(n)]

def train_statistics(worlds):
    contexts=np.concatenate([w['context'] for w in worlds]);q=np.concatenate([w['data']['q'] for w in worlds])
    state=np.concatenate([w['data']['state']+32*j for j,w in enumerate(worlds)]).astype(np.int64)
    r=np.concatenate([w['data']['R'] for w in worlds]);band=np.concatenate([w['data']['b'] for w in worlds]).astype(np.int64)
    counts=np.bincount(state,minlength=len(contexts));n=len(q);c=contexts.astype(np.float64)
    cm=counts@c/n;cv=counts@(c*c)/n-cm*cm
    qm=q.mean(axis=0,dtype=np.float64);qv=np.mean(q.astype(np.float64)**2,axis=0)-qm*qm
    mean=np.r_[cm,qm];scale=np.sqrt(np.maximum(0,np.r_[cv,qv]));scale=np.where(scale>0,scale,1.)
    logs=np.log(r[r>0]);lm=float(logs.mean());ls=float(logs.std());ls=ls if ls>0 else 1.
    return dict(contexts=contexts,q=q,state=state,r=r,band=band,mean=mean,scale=scale,
                logr_mean=lm,logr_std=ls,rows=n,world_row_counts=[len(w['data']['R']) for w in worlds])

def normalized(context,q,mean,scale,current):
    # Float64 standardization is rounded once to float32 before either CUDA or
    # NumPy consumes it. Export audit shares these exact decoded float32 inputs.
    c=((context.astype(np.float64)-mean[:CONTEXT_DIM])/scale[:CONTEXT_DIM]).astype(np.float32)
    z=((q.astype(np.float64)-mean[CONTEXT_DIM:])/scale[CONTEXT_DIM:]).astype(np.float32)
    if current:c[:,:HISTORY_DIM]=0
    return c,z

@torch.no_grad()
def forward_world(net,w,stats,current):
    if not len(w['data']['q']):return np.empty((0,39),np.float32)
    c,q=normalized(w['context'],w['data']['q'],stats['mean'],stats['scale'],current)
    ct=torch.from_numpy(c).cuda();qt=torch.from_numpy(q).cuda();state=torch.from_numpy(w['data']['state'].astype(np.int64)).cuda()
    output=[]
    for start in range(0,len(q),2048):
        sl=slice(start,start+2048);x=torch.cat([ct[state[sl]],qt[sl]],dim=1)
        output.append(net(x).cpu().numpy())
    return np.concatenate(output)

@torch.no_grad()
def world_nll(raw,w,stats,temperature=1.,sigma_multiplier=1.):
    total=0.;n=len(raw)
    if not n:return None
    for start in range(0,n,8192):
        sl=slice(start,start+8192)
        a=torch.from_numpy(raw[sl]).cuda();r=torch.from_numpy(w['data']['R'][sl]).cuda();b=torch.from_numpy(w['data']['b'][sl].astype(np.int64)).cuda()
        value=gpu_math.density_nll(a,r,b,stats['logr_mean'],stats['logr_std'],temperature,sigma_multiplier)
        assert torch.isfinite(value).all();total+=float(value.sum())
    return total/n

def layers(net):return [(x.weight.detach().cpu().numpy().astype(np.float32),x.bias.detach().cpu().numpy().astype(np.float32)) for x in net.layers]

def fit_one(kind,train,cal,stats,out,contract):
    limits=json.loads((HERE/'EXECUTION_LOCK.json').read_text())
    current=kind=='current';torch.manual_seed(contract['optimizer']['seed']);torch.cuda.manual_seed_all(contract['optimizer']['seed'])
    net=model.torch_model(stats['logr_mean'],stats['logr_std']).cuda()
    optimizer=torch.optim.AdamW(net.parameters(),lr=contract['optimizer']['lr'],weight_decay=contract['optimizer']['weight_decay'])
    c,q=normalized(stats['contexts'],stats['q'],stats['mean'],stats['scale'],current)
    ctx=torch.from_numpy(c).cuda();query=torch.from_numpy(q).cuda();state=torch.from_numpy(stats['state']).cuda()
    r=torch.from_numpy(stats['r'].astype(np.float32)).cuda();band=torch.from_numpy(stats['band']).cuda()
    del c,q;torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats();started=time.perf_counter()
    history=[];best_loss=math.inf;best_epoch=None;best_state=None
    n=stats['rows'];batch=contract['optimizer']['batch_rows']
    for epoch in range(contract['optimizer']['epochs']):
        net.train();permutation=torch.randperm(n,device='cuda');loss_sum=0.
        for start in range(0,n,batch):
            ii=permutation[start:start+batch];x=torch.cat([ctx[state[ii]],query[ii]],dim=1)
            optimizer.zero_grad(set_to_none=True);loss=net.nll(x,r[ii],band[ii]).mean()
            if not torch.isfinite(loss):raise RuntimeError('nonfinite train loss')
            loss.backward();optimizer.step();loss_sum+=float(loss.detach())*len(ii)
        net.eval();cal_losses=[world_nll(forward_world(net,w,stats,current),w,stats) for w in cal]
        eligible=[x for x in cal_losses if x is not None]
        if not eligible:raise RuntimeError('no calibration science support')
        cal_loss=float(np.mean(eligible));torch.cuda.synchronize();elapsed=time.perf_counter()-started
        entry=dict(epoch=epoch+1,train_rowmean_nll=loss_sum/n,cal_worldmean_nll=cal_loss,cal_world_nll=cal_losses,
                   elapsed_seconds=elapsed,peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated())
        history.append(entry);dump(out/kind/'epoch_metrics.json',history)
        print(json.dumps(dict(model=kind,epoch=epoch+1,cal_nll=cal_loss,elapsed=elapsed)),flush=True)
        if cal_loss<best_loss:
            best_loss=cal_loss;best_epoch=epoch+1;best_state={k:v.detach().cpu().clone() for k,v in net.state_dict().items()}
            torch.save(best_state,out/kind/'best_cal.pt')
        if elapsed>limits['fit_seconds_per_model']:raise RuntimeError('predeclared offline fit seconds exceeded')
        if torch.cuda.max_memory_allocated()>limits['cuda_tensor_peak_bytes']:raise RuntimeError('predeclared offline tensor CUDA allocation exceeded')
    net.load_state_dict(best_state);net.eval();torch.cuda.synchronize();elapsed=time.perf_counter()-started
    peak=torch.cuda.max_memory_allocated();del ctx,query,state,r,band,optimizer,permutation;torch.cuda.empty_cache()
    raw_cal=[forward_world(net,w,stats,current) for w in cal]
    calibration=json.loads((ROOT/'CALIBRATION_LOCK.json').read_text());grid=[]
    for temperature in calibration['probability_temperature_grid']:
        for sigma_multiplier in calibration['positive_R_sigma_multiplier_grid']:
            losses=[world_nll(raw,w,stats,temperature,sigma_multiplier) for raw,w in zip(raw_cal,cal)]
            grid.append(dict(temperature=temperature,sigma_multiplier=sigma_multiplier,cal_worldmean_nll=float(np.mean([x for x in losses if x is not None])),world_nll=losses))
    chosen=min(range(len(grid)),key=lambda j:grid[j]['cal_worldmean_nll']);setting=grid[chosen]
    weights=layers(net);arrays={}
    for j,(w,b) in enumerate(weights):arrays[f'W{j}']=w;arrays[f'b{j}']=b
    arrays.update(input_mean=stats['mean'].copy(),input_scale=stats['scale'].copy(),logr_mean=np.asarray(stats['logr_mean']),logr_std=np.asarray(stats['logr_std']))
    if current:arrays['input_mean'][:HISTORY_DIM]=0;arrays['input_scale'][:HISTORY_DIM]=1
    np.savez(out/kind/'model.npz',**arrays)
    fixture_index=next(j for j,w in enumerate(cal) if w['cases']);fixture_world=cal[fixture_index]
    state0=min(c['state'] for c in fixture_world['cases']);ii=np.flatnonzero(fixture_world['data']['state']==state0)
    c,q=normalized(fixture_world['context'],fixture_world['data']['q'],stats['mean'],stats['scale'],current)
    x=np.concatenate([c[fixture_world['data']['state'][ii]],q[ii]],axis=1).astype(np.float32)
    subset={k:v[ii] for k,v in fixture_world['data'].items() if len(v)==len(fixture_world['data']['R'])}
    remap={int(old):new for new,old in enumerate(ii)};cases=copy.deepcopy([c for c in fixture_world['cases'] if c['state']==state0])
    for c in cases:
        c['rows']=[remap[j] for j in c['rows']]
        if c['original_point_case']:c['original_row_indices']=[remap[j] for j in c['original_row_indices']]
    fixture=audit_fixture(x,weights,raw_cal[fixture_index][ii],stats['logr_mean'],stats['logr_std'],
                          setting['temperature'],setting['sigma_multiplier'],subset,cases,fixture_world['scoring'])
    dump(out/kind/'numerical_fixture.json',fixture)
    meta=dict(kind=kind,checkpoint_epoch=best_epoch,best_uncalibrated_cal_nll=best_loss,calibration_grid=grid,
              selected_calibration=setting,fit_seconds=elapsed,peak_cuda_allocated_bytes=peak,
              model_sha256=sha(out/kind/'model.npz'),numerical_export_gate_pass=True,history=history)
    dump(out/kind/'FIT_RECEIPT.json',meta)
    return net,meta

@torch.no_grad()
def evaluate(net,w,stats,current,setting):
    raw=forward_world(net,w,stats,current);output=[];mean_output=[]
    d=w['data']
    if not len(raw):return dict(index=w['index'],rows=0,science=controls(d,w['cases'],w['scoring'],np.empty((0,3))),
        mean_before_hinge=controls(d,w['cases'],w['scoring'],np.empty((0,3))),density_nll=None)
    for start in range(0,len(raw),8192):
        sl=slice(start,start+8192);a=torch.from_numpy(raw[sl]).cuda()
        scale=torch.from_numpy(d['scale'][sl]).cuda();weight=torch.from_numpy(d['weight'][sl]).cuda();best=torch.from_numpy(d['best'][sl]).cuda()
        args=(w['scoring'],stats['logr_mean'],stats['logr_std'],setting['temperature'],setting['sigma_multiplier'])
        output.append(gpu_math.gain(a,scale,weight,best,*args).cpu().numpy())
        ec=gpu_math.gain(a,scale,weight,torch.zeros_like(best),*args).cpu().numpy()
        mean_output.append(np.maximum(ec-d['best'][sl,None],0))
    g=np.concatenate(output);gm=np.concatenate(mean_output)
    assert np.isfinite(g).all() and np.isfinite(gm).all()
    return dict(index=w['index'],rows=len(raw),science=controls(d,w['cases'],w['scoring'],g),
        mean_before_hinge=controls(d,w['cases'],w['scoring'],gm),
        density_nll=world_nll(raw,w,stats,setting['temperature'],setting['sigma_multiplier']))

def bootstrap(worlds,key,seed):
    values=np.asarray([w['science'][key] for w in worlds]);rng=np.random.default_rng(seed)
    means=values[rng.integers(len(values),size=(2000,len(values)))].mean(axis=1)
    ci=np.quantile(means,[.025,.975]);return dict(mean=float(values.mean()),CI95=ci.tolist(),positive=bool(values.mean()>0 and ci[0]>0),values=values.tolist())

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=True);started=time.perf_counter();freeze=check_source()
    generation=json.loads((args.data/'GENERATION_RECEIPT.json').read_text());assert generation['status']=='PASS_ALL_136_NEW_WORLDS'
    assert generation['source_freeze_sha256']==freeze
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False;torch.set_float32_matmul_precision('highest')
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    dump(out/'PROCESS_RECEIPT.json',dict(status='RUNNING',pid=os.getpid(),argv=sys.argv,python=sys.version,
        torch=torch.__version__,numpy=np.__version__,GPU=torch.cuda.get_device_name(0),source_freeze_sha256=freeze,
        tf32=False,deterministic_algorithms=True,data_generation_sha256=sha(args.data/'GENERATION_RECEIPT.json')))
    train=load_split(args.data,'train',96);cal=load_split(args.data,'cal',16);stats=train_statistics(train)
    contract=json.loads((ROOT/'MODEL_CONTRACT.json').read_text())
    dump(out/'TRAIN_STATISTICS.json',dict(rows=stats['rows'],world_row_counts=stats['world_row_counts'],
        logr_mean=stats['logr_mean'],logr_std=stats['logr_std'],input_dim=5963,history_dim=HISTORY_DIM,
        preprocessing='float64 train-only standardization rounded tofloat32 shared byCUDA/NumPy; currenthistory zero',train_worlds=96,cal_worlds=16,val_worlds=24,test_worlds=0))
    # Raw host labels are released before fitting; only compressed GPU sufficient
    # training arrays plus train-only statistics survive. Calibration worlds stay.
    del train;models={};metadata={}
    for kind in ['full','current']:
        (out/kind).mkdir(exist_ok=True);net,meta=fit_one(kind,None,cal,stats,out,contract);models[kind]=net;metadata[kind]=meta
    selected=min(['full','current'],key=lambda k:metadata[k]['selected_calibration']['cal_worldmean_nll'])
    dump(out/'SELECTED_CAL_ONLY.json',dict(kind=selected,model_sha256=metadata[selected]['model_sha256'],
        calibration=metadata[selected]['selected_calibration'],criterion='lowest calibrated calworld NLL; full first tie',no_val_selection=True))
    val=load_split(args.data,'val',24);reports={}
    for kind in ['full','current']:
        worlds=[evaluate(models[kind],w,stats,kind=='current',metadata[kind]['selected_calibration']) for w in val]
        a=bootstrap(worlds,'delta_original',107040442);b=bootstrap(worlds,'delta_point_family',107040442)
        reports[kind]=dict(worlds=worlds,delta_full_original=a,delta_point_family=b,positive_adoption_gate=a['positive'] and b['positive'])
        dump(out/kind/'VALIDATION.json',reports[kind])
    check_source()
    result=dict(status='PASS_OFFLINE_VALIDATION' if reports[selected]['positive_adoption_gate'] else 'NEGATIVE_OFFLINE_VALIDATION',
        selected=selected,source_freeze_sha256=freeze,fit_models=metadata,validation=reports,
        complete_seconds=time.perf_counter()-started,production_extra_cost_gate_pass=False,no_deployment=True,no_test_generated=True,
        scope='current science finite-family density decision only; original controls retained; no jointfuturepath or wholecompetition claim')
    dump(out/'FINAL_RESULT.json',result);print(result['status'],selected,flush=True)
if __name__=='__main__':
    try:main()
    except Exception:
        path=Path(sys.argv[sys.argv.index('--output')+1]) if '--output' in sys.argv else HERE/'failures'
        path.mkdir(parents=True,exist_ok=True);(path/('FAILURE_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.txt')).write_text(traceback.format_exc());raise
