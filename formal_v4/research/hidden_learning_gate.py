"""Official full-season same-source baseline and ordinary neural critic gate."""
import argparse,hashlib,json,os,shlex,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"results/hidden_learning_20261003"
UP=ROOT/"upstream/gosim-observer-examples"
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--card",choices=["L3","L4"],required=True);ap.add_argument("--mode",choices=["baseline","critic"],required=True);a=ap.parse_args()
    project=Path(json.loads((OUT/"source_manifest.json").read_text())["source_project"]);dest=OUT/"seasons"/a.mode/a.card;dest.mkdir(parents=True,exist_ok=True)
    if (project/"remote_runtime.json").exists():raise RuntimeError("matched gate must be CPU only")
    env={**os.environ,"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1","HIDDEN_LEARNING_MODE":a.mode,"HIDDEN_LEARNING_MARGIN":"0"}
    command=[sys.executable,str(UP/"runner/run_local.py"),"--card",str(UP/"local-cards"/a.card),"--agent",shlex.join([sys.executable,"-u","research/hidden_learning_agent.py"]),"--agent-cwd",str(project),"--wallclock","900","--out",str(dest),"--quiet","--inherit-env"]
    started=time.monotonic()
    with (dest/"driver.log").open("w") as h:proc=subprocess.run(command,env=env,stdout=h,stderr=subprocess.STDOUT,timeout=1020)
    report=json.loads((dest/"score_report.json").read_text()) if (dest/"score_report.json").exists() else {}
    record={"mode":a.mode,"card":a.card,"seconds":time.monotonic()-started,"exit_code":proc.returncode,"total":report.get("total"),"components":report.get("components"),"counts":report.get("counts"),"termination":report.get("termination"),"source_manifest":str(OUT/"source_manifest.json"),"deterministic_candidate_enumeration":True,"critic_margin":0}
    if a.mode=="critic":record["model_sha256"]=hashlib.sha256((project/"research/hidden_learning_model.npz").read_bytes()).hexdigest()
    (dest/"gate.json").write_text(json.dumps(record,indent=2)+"\n");print(json.dumps(record),flush=True)
if __name__=="__main__":main()
