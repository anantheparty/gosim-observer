"""Exact best entry plus the isolated conditional public-open recovery guard."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import policy
BasePolicy=policy.Policy
from sparse_exact import install as install_sparse
install_sparse()
import wrapper
from research.agent_request_distributed import TerrainBase
from public_open_recovery import install
install(BasePolicy,TerrainBase)
if __name__=='__main__':wrapper.agent.main()
