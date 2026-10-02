# GPU 基础决策 + 本地请求 DP

独立入口 `agent_request_distributed.py`；没有部署或上传，原 `agent_model_gpu.py` 不修改。

1. 稳定 Policy 继续维护反馈、分数/因子账本、报告、修理、校准以及共享 terrain 后验。
2. `RequestRemotePlanner` 在 `_choose_baseline` 中用现有 `OptionalModelGPUTransport` / `ModelRemoteBudget` 获取 GPU Phase action+prediction。失败、额度不足或不可用时用 CPUphase。
3. common 的请求规划原样处理该 baseline，利用本地后验和已发布 forecast 建列/精确maskDP。方向后验不需要发送给GPU服务。
4. 预约跨越 baseline 时缩短tmax，并强制 CPU 裁剪，不再发一次远端请求。
5. `DisabledRemoteFacade` 阻止 Policy 自己重复远端调用；summary计数、EOF close仍代理到真实transport。
6. `PlannerBudgetFacade.record_cpu` 对 Policy 全部choose计时不采样。只有hook真正CPU baseline的时长进入CPU p90；远端setup/choose由已有ModelRemoteBudget拆分。DP/建池时长仍完整消耗官方墙钟，并且后续预算读到已减少的remaining_seconds。

`request_dp_future_field_mode` 在独立入口缺失时默认为published，显式config可以覆盖。GPU服务的固定参数仍由已记录的13项gate默认或客户端显式env控制；CPUphase24配置应从已核验的原字节配置加载。

## 公共stub门检

`request_remote_checks.py` 使用公开初始化，不连接生产网络，验证：正常baseline prediction、超时CPUfallback、预约裁剪forceCPU、只有一次远端调用、原Policy pending prediction不变、正确summary/EOF关闭、入口同时绑定policy和已缓存agent.Policy。人为50ms建池延迟的crop总耗时0.2016秒，CPU样本0.1464秒，没有把建池/DP混进CPU p90。原始结果在 `results/distributed_request_stub_20261003/checks.json`。

这些门检验证接口和预算计时，尚不是完整distributed网络得分。真实HTTP/代理延迟、可用性、预算分配仍须独立整卡验证。GPU direct的795秒也不能直接视为网络版本795秒。
