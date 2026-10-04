"""Normal original policy entry with exact compiled arithmetic installed first."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
from sparse_exact import install
install()
import wrapper
if __name__ == '__main__': wrapper.agent.main()
