# v4 PRO 6000 批量指向搜索后端

2026-10-03。后端为 `gpu_spatial_candidates.py` 的 `GPUSpatialPlanner`（兼容别名 `GpuSpatialPlanner`），使用已有 Windows Python 的 NumPy、Numba-CUDA，无大模型或额外深度学习依赖。部署目录为 `C:/Users/hedge/gosim-observer-formal-v4/research`，GPU功率上限600 W。未改变既有远端任务。

## 两级数学搜索

1. CPU复用公共几何、时间窗、科学/required/request状态和质量信念，生成广泛的目录锚点。每个锚点分别对齐不同光纤中心，因此同时扩大区域覆盖和网格相位覆盖。
2. GPU对所有候选指向×可见目标进行批量 gnomonic 几何。落入场内的目标再比较一组曝光时长、三个program和各自增量价值。按光纤 `atomic.max` 得到该格最大值，再对所有格求和、除以曝光时长。
3. 把粗筛最好的几十个候选与CPU基准候选交给现有 `_evaluate`，使用目标饱和/门槛时长、请求quota精解和两个尺度的空间平移检查，输出真实v4动作。

批量几何、科学/门槛价值和光纤聚合均使用 float64。粗筛的公共时长网格和请求影子价格属于近似；最终动作的断点扫描及quota逻辑沿用CPU版本。GPU不会读取隐藏真值。

宽搜索中粗网格的并列候选可能改变后续精调起点。为避免扩大搜索丢失原有动作，>320 anchors时保护320-anchor基准候选族，独立精解和精调，再与宽搜索比较当前预测价值。该保护针对同一状态下的动作价值；不能证明更宽搜索的整季实际成绩一定不下降。若refine预算不足，保护优先执行，但无法保证未完成的全部候选已覆盖。

## 远端实测

L1公开初始化：7800目标，其中首轮4442个有价值且可见；19种粗曝光长度，16光纤。每档热态重复两次，数据保存在 `gpu_benchmark_result_l1.json` 和 `gpu_wide_benchmark_result_l1.json`。

| 候选指向数 | GPU粗筛 | CPU精解与精调 | 总决策时间 |
|---:|---:|---:|---:|
| 5120 | 18.8–20.3 ms | 143–148 ms | 174–176 ms |
| 16384（含基准保护） | 约57 ms | 176–184 ms | 248–257 ms |
| 65536（含基准保护） | 约209–210 ms | 约198 ms | 448–449 ms |

首轮JIT编译约0.6–1.3秒额外成本；服务启动后应在平台调用前预热。热态每轮可在1秒内扫描数万候选，远端通信时间另计。

40个相同候选、相同冻结质量、相同粗时长网格，对照独立 NumPy 计算，最大目标值绝对差为 `2.220446049250313e-16`。GPU返回动作经过官方 `normalize_action` 和全部16个 `FiberGrid.classify_target` 检验。

5120/16384/65536三档加入基准保护后，首轮精解收益率均为0.9506273991805804，均选择112秒、DARK和16根光纤。此处没有声称更大宽度已经提高整季分数；需要完整同实例回放衡量。

## 服务建议参数

默认后端320 anchors、最多8192候选；服务可设置 `gpu_anchor_count=1024`、`gpu_max_candidates=32768`、`gpu_refine_count=64`、`gpu_refine_budget_seconds=0.4`，单轮约0.25秒。若实测剩余墙钟充裕，可用4096 anchors、`gpu_max_candidates=131072`，本例约0.45秒。

初始化和 `choose(snapshot,best_scores,best_factors,env_estimate,active_requests)` 接口与CPU版本相同，输出动作字段和 `last_prediction` 也相同。HTTP入口需持久保留每卡的planner实例，预热CUDA，维持best-score/raw-factor反馈状态；同一planner调用应串行。

## 固定工作量与复现性

最初后端根据 `gpu_refine_budget_seconds` 的墙钟耗时停止CPU精解。即便数据与源码相同，机器负载也可能改变精解候选数和最终路径。2026-10-03的两套完整GPU direct回放均冻结了这一旧行为；它们衡量各自运行负载下的900秒可行结果，不能作为严格逐决策确定性的消融比较。

现增加可选 `gpu_fixed_workload=True`。该模式按确定的coarse值与候选索引排序，最多精解 `gpu_exact_candidate_count=256` 个去重中心，再执行 `gpu_refinement_steps=32` 次空间探测。缓存命中不重复计算；候选不足时完成全部候选。`gpu_emergency_seconds=3.0` 只作精解阶段紧急保护，触发状态记录在stats；固定模式不再使用常规 `.3 s` 截断。默认未开启该模式，因此旧服务行为不变。新模式尚未部署到运行中的服务或完整回放套件。

独立PRO6000微基准：16384候选，225个精解中心，32次空间探测，248次实际 `_evaluate`。冷热重复和人为给每次精解增加2 ms延迟后，四轮动作SHA256与工作计数完全一致；最终源码热态248–250 ms，人为减速859 ms，紧急保护均未触发。首轮含JIT788 ms。结果见 `gpu_fixed_workload_benchmark_result_l1.json`，其中保存完整源码hash。这一测试证明本状态的墙钟扰动未改变动作，不声称完整赛季已经完成逐决策复现。
