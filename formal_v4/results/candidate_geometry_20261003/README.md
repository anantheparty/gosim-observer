# 全目标加权事件扫与连续指向修复

2026-10-03。独立从官方 `v4_fiber_map.py`、`v4_scorer.py`、runner/protocol 和 L1–L4 建模后，再阅读旧空间/phase方案。实验目标是直接构造得分更高的可执行观测动作。

## 完整同源原始对照

使用冻结 `runs/cold_neural_value_20261003/production_frozen` 的 Policy 和 SpatialPlanner，完整候选枚举消除墙钟中断差异。两模式共享所有环境信念、反馈、report、请求与数据失效逻辑。新模式只替换空间后端。八次均由未修改的官方 `run_scenario` 结算完整季节，均 `survey_complete`。

| 卡 | 原 SpatialPlanner | 加权事件扫 | 总分差 | 科学分差 | required 缺失原→新 | 新模式秒数 |
|---|---:|---:|---:|---:|---:|---:|
| L1 | 6096.185388 | 6378.655366 | +282.469978 | +182.638484 | 2→2 | 317.07 |
| L2 | 6530.003371 | 6808.224288 | +278.220917 | +277.986599 | 3→3 | 382.60 |
| L3 | 5769.301279 | 5912.762510 | +143.461231 | +193.539613 | 5→6 | 330.38 |
| L4 | 5920.398486 | 6078.613462 | +158.214976 | +207.313865 | 0→1 | 323.84 |
| 均值 | 6078.972131 | 6294.563907 | **+215.591776** | +215.369640 | | |

L1 请求奖励另增100；其余三卡请求和报告结算不变。旧记录中的 L3/L4 5633/5869 不是本轮固定枚举源的基准，不能用来计算本轮升幅。完整明细为 `paired_summary.json`，每卡的 `experiment_summary.json` 保存同一组源码哈希；八组哈希逐项一致。

上述基线是原 SpatialPlanner，不能把 +215.59 宣称为对现有生产 CPUPhase 的提升。随后更强的 CPUPhase 同源四卡、保留其完整动作的 union 四卡也全部完成，构成更直接的采用比较：

| 卡 | 完整 CPUPhase control | 独立事件扫 | sweep−phase | 保留 phase 的 union | union−phase |
|---|---:|---:|---:|---:|---:|
| L1 | 6206.367823 | 6378.655366 | +172.287543 | 6260.314915 | +53.947092 |
| L2 | 6808.597984 | 6808.224288 | −0.373696 | 6808.296821 | −0.301163 |
| L3 | 5910.930583 | 5912.762510 | +1.831927 | 5917.358221 | +6.427638 |
| L4 | 6095.293215 | 6078.613462 | −16.679753 | 6094.824216 | −0.468999 |
| 均值 | 6255.297401 | 6294.563907 | **+39.266505** | 6270.198543 | **+14.901142** |

union 对 CPUPhase 的科学分差分别为 +53.888382、−.093777、+6.974121、+49.185363；L4 新增一个 required 缺失的−50几乎抵消该卡全部科学增益。union L3 保持5个 missing，比独立 sweep 的6个更好。固定状态只在收益率提高时才替换动作，但后续排程与反馈仍会变化，整季得分没有单调保证。该表也没有胜过旧 GPU 宽池或离线 truth GA 的证据；它说明新结构在同源实际 CPUPhase 上有均分增益，而不是全球算法领先声明。严格汇总在 `strong_baseline_summary.json`。

## 构造与数学范围

固定时刻、时长和 program 时，目标冻结预期增益 `u_i` 与视场中心无关。设种子切平面的 east/north 为 `(x_i,y_i)`，中心平移为 `(dx,dy)`，光纤中心为 `(c*p,r*p)`，玻璃半宽 `h=glass/2−.008`。目标的可分配中心区域是一个矩形：

`dx ∈ [x_i−c*p−h,x_i−c*p+h]`，`dy ∈ [y_i−r*p−h,y_i−r*p+h]`。

每根光纤选择其中最大正效用目标。零 gap 官方格加 .008 度 margin 后仍是互斥区域，所以不需要一般 Hungarian 匹配。每个目标向所有光纤行/列提供进入和离开边界；在每个轴的完整边界排列区间取中点，即涵盖给定切平面窗口中的所有开放排列格。

新 kernel 没有展开 `centres × targets × durations` 候选张量。它逐 X 区间初始化列归属，对 Y 的进入/退出事件增量维护每根光纤的最大值与 winner。仅当 winner 移出时扫描修复那个光纤，其他光纤的最大值保留。全部 supplied targets 参加边界和效用计算，取消旧 phase 的 24 边界目标、50 粗目标上限。每次选两个当前优质且分散种子，平移窗口为各轴 ±一个 pitch；没有改动旧固定候选列表来作为搜索全集。

排列点可能被许多未选中的微弱目标切成细格。恢复该点的获胜目标及光纤，把这些 placement 矩形求交，并取交集的中心，以提高所构造指派的玻璃余量。随后做最多三次球面 gnomonic 残差修正，连续移动同一个指向。最终每个候选都交给原 `_evaluate`，重新做完整球面玻璃分类、最多72个目标曝光断点、3种 program 和单请求 quota 精解。只有精解 rate 严格超过原动作才替换；预计执行的 command 舍入及估计 pointing offset 参加复核。

kernel 的完备性仅限于给定供给目标、切平面窗口和每个 supplied utility vector。在线 useful predicate、两个种子、粗时长、球面修正和未来价值均是启发式。粗效用使用请求的分摊影子价；最终精解才恢复原单请求 quota。球面修正可能移出初始平面窗口，仍使用该种子的保守局部供给池，动作合法性由球面精解保证；不存在全球面或整季最优性声明。

## 实际工作量和依赖

四卡各987/1100/982/943次空间决策，精解 rate 提高879/992/882/836次。累计完整排列格为1.576/1.939/1.601/1.651亿，kernel 及候选修正累计108.29/128.92/108.87/112.45秒，最终额外精解约7–9秒。墙钟时间是在同一台 Mac 上最多8个 CPU 实验进程并行时测得。

本研究原型使用 Python、NumPy、Numba；没有 CUDA、模型 API 或远程调用。未来 truth 文件由官方 evaluator 读取作结算，participant 后端只接收公开初始化、当前 snapshot、已有反馈与 Policy 的环境估计。`run_scenario` 原生回放没有 transport 的强制900秒计时；已测总耗时低于383秒，但正式 2核/2GB/900秒容器 gate 尚未完成。部署需将 kernel 编译成可在标准 Linux 容器执行的版本，不能假设容器有 Numba。

## 核验和可复现文件

`candidate_geometry_verify.py` 使用 seed4771，独立向量化逐格全穷举核验24组输入，覆盖2–4边网格、gap0/.03、各轴0.5–1.55pitch窗口。累计23194格，最大效用误差1.7764e−15。`kernel_cases/00.npz` 至 `23.npz` 保存完整输入、Numba的两个不同空间最大候选输出、访问格数和独立 brute 最优值；可直接用于 C++ 后端逐项核验。

原八次回放的精确源码在 `source_snapshot/`；`frozen_python_manifest.json` 提供冻结 Policy 及其全部研究 Python 依赖的 SHA256。后续仅增加 `_base_choose` hook，kernel 没有改变；union 源码单独保存在 `union_source_snapshot/`。union provider 执行独立 CPUPhase instance 一次，复制它的 frame、所有原始候选、最终接受的 phase 动作、收益率及反馈 prediction，然后执行相同事件扫；不重复执行原 SpatialPlanner 基线。

复现原始模式（工作目录为仓库根，使用冻结框架源）：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 formal_v4/research/candidate_geometry_experiment.py --card L1 --mode baseline
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 formal_v4/research/candidate_geometry_experiment.py --card L1 --mode sweep
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 formal_v4/research/candidate_geometry_verify.py
```

更强 control 和 union 的入口分别为 `candidate_geometry_phase_compare.py --card L1` 与 `candidate_geometry_union_compare.py --card L1`。原始后端源码哈希见各 summary；后续 hook 版默认仍走原 SpatialPlanner，只有 union provider 走 CPUPhase。

## 可供普通 NN 提案训练的数据

`labels/L1` 和 `labels/L2` 为训练卡、`labels/L3` 为验证卡、`labels/L4` 为留出测试卡。每12次曝光记录一次当前在线状态的两个 seed，共672个 group，约6.4MB NPZ，最大266个局部目标。它是空间即时效用的教师标签，不能当成终局 continuation value 或泛化提分证据。

每个 group NPZ 保存：`seed[2]`（预计实际 alt/az）；`pool[N]`（公开目录索引）；`x[N],y[N]`（east/north，度）；`values[Q,N]`（效用每秒）；`durations[D]`；`bx/by/bv[Q,2]`（各 utility 的两个离散空间最大值）；`interior_x/interior_y[Q,2]`（获胜指派可行盒中心）；`radius`（度）。`Q=3D`，duration-major 后 program 顺序 DARK/BRIGHT/BACKUP。对应 JSON 保存该时点原动作、所选球面指向、实际精解 rate 及工作量。JSON 在该状态的两份 NPZ 写完后产生。

## 剩余决策瓶颈

L3 新增遗漏 `V4T007053`（RA133.528、flux.255375）：原策略最后两夜用2387秒达到factor.537205，新策略早一周只用1225秒达到.242566，后续未补足。L4 新增遗漏 `V4T002279`（RA125.799、flux.081536）：原策略最后一夜用2955秒和quality1.03573达到.554549，新策略完全未观。两项均为高RA末季长曝光安排损失；不是几何miss或data-loss撤销。目标和原始有效因子明细在 `required_swaps.json`。

下一步价值在于对这些单次长曝光窗口预留时间，以及使用 C++ 或普通 NN 将新增连续动作结构部署到正式资源约束下。当前未修改生产源、未修改 Git index、未提交网站或填写备注。
