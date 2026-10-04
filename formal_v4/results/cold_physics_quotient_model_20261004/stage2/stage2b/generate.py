"""Rhodes own-container 2B generation. Source must be frozen before launch."""
import concurrent.futures as futures
from datetime import datetime,timezone
import hashlib,json,os,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n')
def main():
    lock=json.loads((HERE/'SOURCE_FREEZE.json').read_text())
    assert lock['parent_source_freeze_sha256']==sha(ROOT/'SOURCE_FREEZE.json')
    for name,value in lock['files'].items():assert sha(HERE/name)==value
    resources=json.loads((HERE/'EXECUTION_LOCK.json').read_text())
    source=ROOT;out=Path(os.environ['QUOTIENT_GENERATION_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    logs=out/'logs';logs.mkdir(exist_ok=True)
    for folder in ['worlds','datasets','failures']:(out/folder).mkdir(exist_ok=True)
    tasks=[(role,i) for role,n in [('train',96),('cal',16),('val',24)] for i in range(n)]
    started=time.perf_counter();receipts=[];aborted=False;next_task=0
    image=resources['rhodes_image'];owned_prefix=resources['container_prefix']
    def run(task):
        role,i=task;name=f'{owned_prefix}-{role}-{i}';t=time.perf_counter()
        args=['docker','run','--name',name,'--cpus','2','--memory','2g','--network','none',
            '-v',str(source)+':/work:ro','-v',str(out)+':/output',
            '-v',resources['numpy_dependency_path']+':/deps:ro',
            '-e','PYTHONPATH=/deps','-e','OPENBLAS_NUM_THREADS=1','-e','OMP_NUM_THREADS=1',
            '-e','QUOTIENT_OUTPUT=/output','-e','QUOTIENT_SPLIT='+role,
            '-w','/work',image,'python','stage2b/dataset_driver.py','--index',str(i)]
        with (logs/f'{role}_{i}.log').open('wb') as log:result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT)
        inspect=subprocess.check_output(['docker','inspect',name]);(logs/f'{role}_{i}_container.json').write_bytes(inspect)
        receipt_path=out/'datasets'/role/f'{i}_receipt.json'
        receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        passed=result.returncode==0 and receipt is not None and receipt['budget_pass']
        answer=dict(split=role,index=i,container=name,exit_code=result.returncode,wall_seconds=time.perf_counter()-t,
            passed=passed,worker_receipt=receipt)
        return answer
    with futures.ThreadPoolExecutor(max_workers=resources['max_workers']) as pool:
        pending={}
        def launch():
            nonlocal next_task
            while not aborted and len(pending)<resources['max_workers'] and next_task<len(tasks):
                task=tasks[next_task];next_task+=1;pending[pool.submit(run,task)]=task
        launch()
        while pending:
            done,_=futures.wait(pending,return_when=futures.FIRST_COMPLETED)
            for future in done:
                task=pending.pop(future)
                try:r=future.result()
                except Exception as error:r=dict(split=task[0],index=task[1],passed=False,orchestrator_error=repr(error))
                receipts.append(r);aborted=aborted or not r['passed']
                dump(out/'GENERATION_PROGRESS.json',dict(status='FAIL_STOP_NEW_LAUNCHES' if aborted else 'RUNNING',
                    finished=len(receipts),started=next_task,total=len(tasks),receipts=receipts))
                print(json.dumps({k:r[k] for k in ['split','index','passed']},allow_nan=False),flush=True)
            launch()
    status='PASS_ALL_136_NEW_WORLDS' if not aborted and len(receipts)==len(tasks) else 'FAIL_INCOMPLETE_PRESERVED'
    for name,value in lock['files'].items():assert sha(HERE/name)==value
    dump(out/'GENERATION_RECEIPT.json',dict(status=status,elapsed_seconds=time.perf_counter()-started,
        finished=len(receipts),total=len(tasks),source_freeze_sha256=sha(HERE/'SOURCE_FREEZE.json'),
        source_readonly=True,network_none=True,no_old_truth_or_data=True,no_test_generation=True,receipts=receipts))
    print(status,flush=True)
    if status!='PASS_ALL_136_NEW_WORLDS':raise RuntimeError(status)
if __name__=='__main__':main()
