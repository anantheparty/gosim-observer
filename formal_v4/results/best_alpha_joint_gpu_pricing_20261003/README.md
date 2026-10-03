# 最新 α 基线的稳定化对偶与真实 GPU 联合定价

## 状态与结果

**完成**：最新最好 α 的独立 1376 列 master → 最优对偶面稳定化 → 数值符号 cleanup/KKT → supported 新修复划分中的缺失目标窗口 → 自有 PRO6000 GPU 定价 → 官方 CPU 精核 → 同一新 master 的 LP/MIP。

基线为 `cloud_phase_gpu_alpha_20261003`，官方 **7289.494481**。没有使用旧 α master/旧对偶。本轮保守研究净分变化 `9.09e−13`，乐观有限 LP 变化 **0**，MIP status optimal、gap **0**、未选新列，保留原 1184 个历史曝光及报告。没有新比赛回放成绩或完整全局最优证明。

## 新对偶与数值处理

使用 `best_incumbent_alpha_master_20261003/column_pool.json`，hash `21bc59a47930643499c7dec957218097187ca0db15754499af3af1d229cf5b5d`。对实际原矩阵构造完整 dual，保留 winner local links、target simplex、REQ/mandatory flag bounds 及所有时间 flow 条件，在原最优 objective 的等式约束下最小化历史已完成 mandatory 的 ν 总和：**188.54593046 → 22.49716107**。

原数值解有一个 μ 为 `+4.879794346e−10`。将这唯一的符号噪声置 0，α/β 同时按正确符号处理，完整 raw/clean arrays 保存在 `full_dual_raw_clean.npz`。没有只裁剪 compact ν 然后忽略其他 constraints。cleanup 后再次检查：

| 条件 | 数值 |
|---|---:|
| 全 stationarity 最大残差 | 4.8798e−10 |
| 对原 primal optimum 的 objective 差 | 5.4570e−10 |
| complementarity 最大残差 | 3.7007e−15 |
| 原 1376 列最大 reduced profit | 4.8798e−10 |
| 原始乘子 cleanup 总 L1 变化 | 4.8798e−10 |

clean μ≤0、α≥0、β≤0 的符号严格满足，GPU values 严格非负；这是通过 1e−7/1e−6 数值门检的浮点模型证据，不是有理数精确证明。完整符号及原始 objective/约束模型说明见上一独立 `season_dual_stabilization_20261003` 研究。

## 曝光窗口与 GPU

使用最新报告/修复切分后的 `conditional_profile_new_repair_cells.npz`，462 个 narrow supported cells；每个候选曝光所触及的新 cell 都要求 support>0、finite lower/upper、宽度≤1e−4。不能跨固定报告或 repair 不一致 gap。仅使用 fresh LP 已有起止节点的 pi，未插值未知节点。

缺失目标 `V4T001295 / V4T005424 / V4T008897` 分别有 25/29/22 个 quality-supported factor≥0.5 的节点 pair，计数尚未要求方向净空/整曝光可见性。随后筛出 5 个净空窗口，分布于 10 月 5/6 日；其 batch whole-track 几何与精确质量张量中三个缺失目标都有至少一个可达 factor≥0.5 的时段。

每个 case 32,768 个 pointing、9或12个 duration、三个 program，合计 **5,308,416 个有限列**。以 `original glass−0.06°`、原 pitch 定价，将 0.03° margin 直接纳入排名。按 science max residual、mandatory ν、REQ η 与时间弧价格联合选择每 fiber 的目标。

| 实测 | 数值 |
|---|---:|
| 实物设备 | NVIDIA RTX PRO 6000 Blackwell，非 simulator |
| GPU pricing 合计，含第一 case cache/JIT | 0.829850 s |
| device 阶段，含 NPZ load 与 CPU gate | 0.983184 s |
| module import | 0.438320 s |
| 独立 CPU/CUDA 核验有限列数 | 1,710 |
| 最大 CPU/CUDA 误差 | 2.8422e−14 |
| CPU 官方精核 | 73.280816 s |
| 官方 fiber/整曝光高度检查 | 3,673 |
| 原质量矩阵重新计算最大误差 | 2.2204e−16 |
| GPU值与精核 assignment 的价格误差 | 0 |
| 精核不同正价列 / 保留 | 233 / 120 |
| 新整季 master 全阶段 / MIP | 2.840044 / 0.107604 s |

这些计时不含 SSH 传输。仅对有限条件列定价，不代表整季 solver 的固定倍数加速。

## 整季结果与覆盖欠缺

120 个新列加入原 1376 列，每个新列均通过原 glass、严格 >0.03° margin、官方 FiberGrid、全曝光最低高度、conditional direction-clear 与 fresh repair quality checks。

乐观有限 LP 在新增前后均为 **7373.168525333393**（含 required/report 常数，省略非正 Jain）。保守 MIP 以 science max/mandatory/REQ 为目标，Jain 在取得整数排程后按实际 completion 结算；净分改善低于 CSV 舍入误差的两倍 0.009599002 时保留 incumbent。

`replacement_diagnostics.json` 进一步说明当前有限列集的欠缺：最终保留列中有 69 列可完成缺失 `V4T005424`，4 列可完成 `V4T008897`，**0 列完成 `V4T001295`**。虽然 prepared pointing/window 包含该目标的机会，当前对偶逐 fiber 最优 assignment/top列筛选没有保留下它的完成列。准备阶段覆盖并不等于最后 master 已覆盖全部机会。

单列替换诊断中最好的保守变化也为 **−202.688529**：替换三个历史曝光，科学约−2.674，丢失四个其它 mandatory（−200）。这是解释性单列诊断；整季多列 LP/MIP 已独立求解，仍没有采用新列。

后续模型工作应覆盖“为了补缺失目标而被挤掉的已完成目标”的替代观测，或在追加列后重新定价、迭代 column generation，允许原来受其它目标挤占的 assignment 改变。只围绕当前三个缺失目标枚举一批列不覆盖这些补偿链。不能从本轮无改善推出完整问题已最优。

## 条件与来源

质量是本人合法官方输出得到并在最新 run 的 clean measurements 上核验过的 same-realization conditional narrow 区间，固定最新 report/E 历史。仍假设零 pointing offset、公开 reference 方向事件范围以及 program 上下界；未证明所有未观察天气/隐藏偏移/连续指向都被覆盖。

`remote_hashes.json` 对所有五个 NPZ、metadata、device driver/kernel、GPU output 核验远端/本地字节一致；`manifest.json` 汇总源码、fresh pool/profile 和所有输出 hash。raw/clean full dual、阶段计时、coverage、GPU top、refined columns、全 master gate 与保底 schedule 均保留。

独立源码为 `formal_v4/research/best_alpha_joint_gpu_pricing.py`。没有修改原 audit/master/kernel/driver、生产 ZIP、服务、API 或功率限制，没有读隐藏 truth，没有新提交。
