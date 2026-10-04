# 连续物理商模型：2A 真 world 支持与成本

日期：2026-10-04。stage1 的 11 项文件与 manifest 未修改。本阶段全部文件位于独立 `stage2/`。四个不同天气 seed 的官方新 world 完成；2B 的 96/16/24 独立数据与 PRO 拟合随后获得 root 授权，但本报告完成时尚未生成、拟合或生成 test。

## 1. 预测对象与解析物理

当前曝光的预测对象是 `P(b, R | public history, current publications, public target trajectory, actual duration)`。其中 `b` 是官方实际 DARK/BRIGHT/BACKUP band，`R=Q/Hbar`，`Q` 是官方未饱和质量积分除以实际曝光时间，`Hbar` 是仅由公开位置、月亮、airmass、时长和 slot 切分计算的正缩放。于是

`a=flux*d*Hbar/(f0*T0), F=min(aR,1), G_program=E[(weight*m(program,b)*min(aR,1)-B)+]`。

host 用新 world 的真实天气、方向事件、fault、report 后的效率生成 `b,R` 标签。actor 的 head 只看公开特征。未来 flux、science weight、best、声明 program、饱和 cap 不输入 head；它们在解析 G 中计算，避免网络再学这几个确定运算。时长和公开几何的形状仍输入：多 slot 加权质量与 band 阈值依赖这些形状，不能把它们全部删掉。

输入为 `ht[8,16,36] + hn[8,129] + hm[8,16] + cn[129] + cm[16] + q[50]`，合计 5963。`ht` 的新增 12 项是每个历史 hit、三个可能 band 的六位小数 score 反演商区间：下界、有限上界、上界无穷标记、可能标记。保留过去 flux/weight/program，是因为反演其 likelihood 必需。未命中不当成 R=0；hit 的零分和 missing 分开。饱和为下界约束，data resync 后公开 best 按有效历史重建。

模型为普通 `5963→128→128→39` ReLU 网络。输出 15 个 joint mixture logits（3 band × R=0 atom 与 4 个正 lognormal）、12 个 μ、12 个 σ。正 R 不作饱和截断。训练目标是联合 band/R density NLL，含 lognormal Jacobian。full history 和 current-only 同结构，以 cal 的 world 等权 NLL 选择。2A 不调用训练，也没有预测提分结果。

这是一种当前曝光条件密度近似。历史单 target 区间是特征，未声称形成多 slot 联合后验。stage1 的 33-cell 界只适用于其限制模型，本阶段真实 1–5 slot、事件边界与 fault 不能套用该界。当前 marginal head 也不能向 `STOCHASTIC_PATTERN_MODEL_ZH.md` 提供共享未来 path：未来随机复访的 Emax 需要新的共同隐状态/transition/path 模型。

## 2. 来源、冻结与失败

生成前冻结 70 项 source、public initializers、sampling、architecture、calibration、numerical 与 current science microobjective。旧 directF trial、旧 test、旧 cache/data/model/truth 均未读取或修改。既有 strong source 只复制程序与 native kernel，运行时 remote disabled。新 weather 使用允许的官方副本；weather SHA 为 `b4675ead09e8cf333c12841ac051786c523394d4fb3cfb0b52397ad75dcc753a`。静态 L1/L2 initializer 是公开输入，新 weather/event/fault 全部独立生成。

三次 source freeze：

| 版本 | freeze SHA256 | 实际用途 |
|---|---|---|
| v1 | `af9ed266d2637007db3675d76bf64adb6c77b4c031a8eb19e3fd243463161f87` | pilot0 完整算完但 receipt JSON 序列化 np.int64 失败，exit1 |
| v2 | `38d89fd2535da76ca5af0e516d6f9cc29e5719fba5952611b733c19174112b65` | 仅 JSON np.generic→item；pilot0 PASS；pilot1 空 assignment 索引失败，exit1 |
| v3 | `b9dee489acbeab31f14627bc97c10b9372494960f8310e33a6ce425f7ad0a086` | 仅 mesh indices 显式 np.int64；pilot1–3 PASS |

v1/v2 pilot0 的 NPZ、cases、public history judge、point action、point host 五项 SHA 完全相同。v2/v3 的唯一差异是 `np.asarray(idx,dtype=np.int64)`；Linux 非空 tuple of ints 原本就返回 int64 同值数组，因此 root 同意保留 pilot0 的 v2 实测，不重跑。合法空 assignment 在 v3 pilot1 继续流程中已覆盖；完成 world3 又出现一个空 assignment。

两个失败 world、source、traceback、Docker log/inspect、exit1 均完整保留。试图搬动 Docker root-owned 旧目录时的 PermissionError 没有删除原输出，重试改用新 output_v2/output_v3 挂载。一次 SCP 未完成前 hash 检查失败，等待完成后验证正确。v1 丢失的内存中分段计时未伪造重建。全部新 world 与失败输出 archive SHA：`cbfb462be64edb69f3f842b06861cd6e1b22d7d777cd288c41b7dc48566ffdc7`，10,758,958 bytes。

Rhodes 容器固定 `python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016`（实际 Python3.12.15），只读 NumPy2.2.6 runtime；每个 worker 2 CPU/2 GiB/network none，只读 source。没有挂旧 truth。保留所有 owned container，source 生成前后 hash 核验通过。

## 3. 四个真实 pilot 的证据

每个 world 在 32 个均匀季节位置作 8 次公开 sensor exposure，然后对公开 snapshot 调用一次完整 frozen point selector，并实际执行其输出。后续 host 标签用同一个新 world 判分。sensor 采样和 weather seed 独立，未来私有数据不送到 point controller。

| pilot | catalog | worker 秒 | peak RSS MiB | observe/wait | future rows/cases | scalar samples | 原 assigned pairs |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | L1 | 37.411 | 212.29 | 27/5 | 14,458/268 | 888 | 406 |
| 1 | L2 | 41.328 | 185.36 | 30/2 | 15,127/292 | 964 | 440 |
| 2 | L1 | 38.973 | 174.25 | 30/2 | 14,694/298 | 967 | 431 |
| 3 | L2 | 41.382 | 226.18 | 28/4 | 14,780/280 | 926 | 422 |

共 59,059 rows、1,138 cases、115 science states、13 原 wait、1,699 原 pairs。所有原输出的 assignments/program/实际裁时完整保留；finite pool 至多每 field 64 targets 时，原 assigned pairs 强制进入，未被 rank cap 丢掉。两 field 为原 pointing 与预声明公开偏移，至多五个实际裁时。NN 没有重算原 selector 的百万候选域，因此 finite family 不是整个 strong controller。

真实候选跨 1–5 个 weather slot，R=0 384 行、F 饱和 26,424 行、实际 offset 未命中 88 行。band 标签为 DARK45,661/BRIGHT11,639/BACKUP1,759。正 R 范围跨 world 为 0.006875–1.331911，包含大于 1 的未饱和商；不能把 R 当 F 限在[0,1]。`future_with_directional_events` 表示曝光区间有方向事件相交，因 terrain 常驻而全部有相交；它不是“每行 target 实际被事件覆盖”的计数。

独立官方 scalar 对照 3,745 次，涵盖每个原 mandatory target 与每 case 前两行附加样本。Q/R/F/band quality/band 最大误差 `8.881784197001252e-16`；F=min(aR,1) 最大误差 `3.3306690738754696e-16`。这是已证实现的真实支撑，后续不重复扩 scalar/toy 测试。

历史 public returned score 共 12,765 个；assigned 但 missing 共 2,203 个；返回 hit 的零分共 1,182 个。每个 returned score 的三 band 区间包含 host 真 R，官方 observations.csv 的六位小数分数逐项匹配。两次公开 resync 被 actor/public best 和 host mirror 同步处理。两个合法 empty assignments 已完整继续。所有六组 actor array 有限值。

initial terrain 的全部方向公开支持精确重建，四 world 分别 SE；N/NE；E/SE/W；N/W。host hidden science event 边界只改标签积分，未改 public query mesh。未来实际 pointing offset 只用于 host actualhit 标签；finite family 使用公开 offset estimate，仍有不可预测的 miss，未学 hit posterior。

四 pilot 没有实际 report state，REQ 文件为空，因而未覆盖 healthy-report execution 或 REQ controller。feature/schema 能处理这些记录不等于已证明其真实数据支持。未计算正式终局任务分数、Jain、required、未来复访 Emax、report 信息价值或 fault/dataloss 的跨动作影响。

## 4. 原输出与有限 family 的控制

`pilot_analysis.py` 是事后只读分析 source，执行前独立冻结；它没有修改 70 项试验 source、拟合模型或调参。使用预声明存储的 point C/E 当前分布，在相同 finite family 按 public `max(w*m*Fpoint-B,0)` 先每 fiber max 再按 duration rate 选 case/program；完整原 action 是 option0，并按原程序、所有 pairs 与实际裁时评价。selection 不用 host R、band、actualhit 或 truebest；host 仅判断所选当前动作的实际增量。

| pilot | 完整 original 当前 science/sec | finite point rescore science/sec | 差值 |
|---:|---:|---:|---:|
| 0 | 0.02404781 | 0.02475095 | +0.00070315 |
| 1 | 0.01782297 | 0.01889163 | +0.00106866 |
| 2 | 0.01591865 | 0.01657105 | +0.00065240 |
| 3 | 0.02034263 | 0.02141180 | +0.00106917 |

world 等权差值 +0.00087334；finite point 改了 73/115 个 science state。该分析只说明 finite-family 当前 science 目标本身与完整 controller 的输出有差异。它没有证明 NN 密度更好，也不是正式赛提分结论。2B 必须同时比较完整 original 与这个 same-family point control，不能把 search/objective 变化算作密度模型收益。

## 5. 数值门与实际成本

新 trial 提前声明 float32 规模误差界：每层以 `|W|err + gamma(n+2)(|W|(|a|+err)+|b|)` 推进，ReLU 是1-Lipschitz，TF32关闭。打印所有 logit 差异并与该规模界比较，不沿用旧 trial 无尺度固定 logit 门。概率实际门为 maxabs3e−6/perrow L1 3e−5。

对 component logR=μ+σZ，封顶 positive-part score 对 logR 的 Lipschitz 常数不超过 M=w*m。故同 Z 耦合给出 `|ΔG|≤M(|Δμ|+sqrt(2/pi)|Δσ|)`，joint mixture 加 `Mmax*TV(π,π')`。G 必须同时在该 bound（含预声明8e−8*Mmax kernel allowance）和1e−4*Mmax实际 cap 内。action margin 大于相关 option 误差和时须同 action；小 margin 则报告 tie 与误差界。该门尚未用拟合后的 CUDA/NumPy 模型实测，未宣称 export PASS，旧失败试验门未改。

| 每 world 秒 | pilot0 | pilot1 | pilot2 | pilot3 |
|---|---:|---:|---:|---:|
| 完整 point selector 调用 | 7.259 | 8.143 | 8.342 | 7.760 |
| 公开 history 特征 | 2.776 | 2.751 | 2.736 | 2.829 |
| future query/H/case/host labels 合计 | 5.069 | 6.040 | 5.483 | 5.713 |
| official scalar（上一行的子项） | 0.173 | 0.186 | 0.186 | 0.163 |
| past host labels | 1.724 | 1.454 | 1.260 | 1.907 |
| NPZ/JSON write | 0.148 | 0.156 | 0.153 | 0.153 |

full runner 包含上述嵌套 actor/host 操作与官方执行；这些数字不能简单相加。query/H/case/host labels 未单独仪表化分离，不能把混合 host 计时当 actor-only 成本。

预声明 pilot 门 120s/1GiB process RSS 四项通过。生产 NN 额外成本门仍是 median20ms/p9550ms/64MiB，未放宽。当前公开 history 特征平均85.49–88.40ms/state，已经超过其目标；还没有算 naive 每 query 重复5963首层、CDF及完整 head。因此没有生产成本 PASS，不能部署。后续若保存前者数学函数，可独立冻结 immutable-history H/cache 与 shared context first-layer 运算，再测总 actor 额外成本；它不是这四 pilot 的改动或已成功结果。

## 6. 已授权的下一步与停止点

root 在四 pilot 完成后授权 2B：新 train96/cal16/val24 world，固定普通 full/current NN、12 epochs、AdamW、cal checkpoint/25格 temperature×sigma calibration、val 两个 point 控制。生成/fit driver、输入规范化、GPU分片和资源必须再先冻结、备份后才生成；四 pilot 只作支持审计，不作为 train/cal teacher。cal/val 用 PRO GPU batch forward 与相同解析 float64 CDF G，CPU仅作必要导出 fixture/数值验证。

未启动新 test；旧 test 仍未生成。仅正验证门通过后才可讨论新 test，生产成本失败保持失败。拟合后交 root 审查，不自启正式900季节或线上。2B 即使得到正当前 science gain，也只证明当前曝光/finite family 的条件期望价值，不能升级成完整多 slot 后验、共享未来 path、正式终局最高分或旧 directF 负结果的失败原因。
