"""Independent frozen-request entry with exact caches and disabled transport."""
import os

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')

# The frozen entry installs its original terrain/request policy classes. Replace
# both factories before the first initialize message can create any policy.
from research import agent_request_distributed as frozen_entry
from research.request_exact_cache import ExactRequestCacheMixin
from research.request_remote_planner import RequestRemotePlanner
import agent
import policy
import remote_planner


class DisabledRemote:
    enabled = False
    calls = 0
    seconds = 0.
    rpc_calls = 0
    rpc_seconds = 0.

    def __init__(self, initial, config):
        if config.get('enabled') is not False or config.get('enable_search') is not False:
            raise ValueError('exact-cache candidate requires disabled runtime')

    def check(self):
        return {'remote_check': 'disabled', 'transport': 'offline-request-exact-cache', 'seconds': 0.}

    def choose(self, *args, **kwargs):
        raise RuntimeError('remote disabled')

    def close(self):
        pass


class ExactCachedRequestRemotePlanner(ExactRequestCacheMixin, RequestRemotePlanner):
    pass


class ExactCachedRequestPolicy(frozen_entry.DistributedRequestPolicy):
    def __init__(self, initial):
        super().__init__(initial)
        if type(self.planner) is not ExactCachedRequestRemotePlanner:
            raise TypeError('exact-cache planner was not installed before initialization')
        if self.remote is not None:
            raise ValueError('offline exact-cache policy cannot retain a remote transport')

    def summary(self):
        return {**super().summary(), 'request_exact_cache': dict(self.planner.exact_cache_stats),
                'request_exact_cache_class': type(self.planner).__name__}


remote_planner.RemotePlanner = DisabledRemote
policy.SpatialPlanner = ExactCachedRequestRemotePlanner
policy.Policy = ExactCachedRequestPolicy
agent.Policy = ExactCachedRequestPolicy

if __name__ == '__main__':
    agent.main()
