# 独立 Phase RPC 入口

`formal_v4/gpu_phase_rpc_server.py` 复用现有受限 RPC 服务，只在新进程内把初始化类绑定到 `PhaseServicePlanner`（继承已门检的 `PhaseGPUSpatialPlanner`）。默认端口 19929，不改既有服务源码或 19924 进程。尚未部署。

部署前需要把 `gpu_rpc_server.py`、新入口以及 `research/{gpu_phase_candidates,gpu_spatial_candidates,spatial_candidates}.py` 放到一个独立目录，保留 `research` 包；如需服务端采用地形模型，应由客户端传入数值 `target_quality_scale`，服务端不直接读取私有天气。

在 Windows PowerShell 中启动（传入当前同接口范围、同有效期的受限 GPU bearer 文件即可；不要显示令牌）：

```powershell
Set-Location C:\Users\hedge\gosim-observer-formal-v4-phase
& C:\Users\hedge\gosim-gpu-venv-20260926\Scripts\python.exe -u .\gpu_phase_rpc_server.py --host 127.0.0.1 --port 19929 --token-file <现有受限令牌文件的绝对路径>
```

`/initialize` 的 backend 应为 `PhaseServicePlanner`。协议与原服务相同。服务在缺少 GPU 配置项时填入已归档四卡门检的固定默认：1024 anchors、最多 32768 候选、top64、fixed workload、256 精解、32 refinement、3秒紧急保护，以及 Phase16种子/24边界/64精解/3秒保护/phase模式。显式客户端配置项优先，`gpu_refine_budget_seconds=.3` 也记录，但 fixed 模式主要由工作量控制。

这 13 项完整定义在入口 `PHASE_GATE_DEFAULTS`，`/health` 返回默认字典和其 SHA256；每次 choose stats 返回相同 SHA256 与本次补齐的 key 列表。CPU fallback 参数不由服务修改。正式流量切换由根任务处理。

## 新进程微基准

2026-10-03，PRO 6000 上读取公开 L1 初始化，使用已冻结的 e7ab Policy / be40 GPU / 832e Phase 模块，1024 anchors、最多 32768 baseline 候选、256 精解候选、32 refinement、16 phase seeds、24 边界目标、64 phase 精解：

- import 0.465 秒；初始化 0.081 秒。
- 第一次 choose 0.608 秒；初始化加第一次 choose 0.689 秒。
- 从脚本开始到第一次动作 1.154 秒。
- 后两次 choose 0.483 / 0.485 秒；每次 40000 phase 候选，64 精解，无紧急截断。

这是独立新进程，第一组复用了先前完整回放产生的磁盘 JIT 缓存。第二组指定一个新建空 `NUMBA_CACHE_DIR`，import 0.483 秒、初始化 0.082 秒、首次 choose 1.035 秒；初始化加 choose 1.117 秒，从脚本开始到首次动作 1.600 秒，之后 .505/.490 秒。两组都不含 HTTP/TLS、服务队列、网路延迟，第二组也未清 GPU 驱动缓存。服务上线前应先预热一次公开初始化/choose，再开始正式容器调用。全季四卡 Phase 结果已另存，平均比分照 baseline 高 132.98 分。

原始测量：`formal_v4/results/gpu_phase_cold_probe_20261003/{result,empty_cache_result}.json`。
