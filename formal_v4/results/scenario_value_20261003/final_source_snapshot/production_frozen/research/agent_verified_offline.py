"""Keep each frozen policy in its own process and disable remote initialization."""
import os
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')


class DisabledRemote:
    enabled=False
    calls=0
    seconds=0.
    rpc_calls=0
    rpc_seconds=0.
    def __init__(self,initial,config):
        if config.get('enabled') is not False or config.get('enable_search') is not False:
            raise ValueError('offline portfolio requires explicit disabled runtime')
    def check(self):return {'remote_check':'disabled','transport':'offline-verified-portfolio','seconds':0.}
    def choose(self,*args,**kwargs):raise RuntimeError('remote disabled')
    def close(self):pass


def main():
    branch=sys.argv[1]
    if branch=='request':
        from research import agent_request_distributed
    elif branch=='phase':
        from research import agent_model_gpu
    else:raise ValueError('unknown offline portfolio branch')
    # Imports above install the frozen policy. Replace only its optional transport
    # factory before initialize; stable Policy and planner source remain exact.
    import remote_planner
    remote_planner.RemotePlanner=DisabledRemote
    import agent
    agent.main()


if __name__=='__main__':main()
