"""Normal debias RequestCache entry; exact sparse fibre reductions installed first."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
from sparse_exact import install
install()
import debias_entry
if __name__ == '__main__': debias_entry.agent.main()
