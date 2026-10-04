# 完整曝光模式列生成，2026-10-04

本轮只研究已存在两个 public-only、零历史/零通知 pilot 的确定 science-only 模型。沿用 `cold_public_opportunity_cost_20261004` 的全部 32 夜日历、192 targets、四个夜内起点、24 个无收益筛选 anchor、三 program、duration `{120,600,1800,3600}` 和公开 seasonal C/E。不读取 truth，不生成新世界，不复做已经通过的 scorer/几何精度测试，不运行 900 整季，不部署。

## 模型与瓶颈

旧紧凑 LP 的 target-best 消元只适用于固定系数 `g_ie=max(c_ie-b_i,0)`、可删除重复 assignment 的 science-only 目标。REQ、required、Jain、rank、loss、自适应反馈和随机 `E[max]` 均不在等价证明内。本轮复用该数学范围，不能把季节 nominal value 称为真实未知天气最优或正式得分。

旧实现仍把每条 target edge 作为 x 变量，每个曝光 fiber 作为一行；W90501/02 common graph 分别有 53,735/77,297 行和 95,991/131,307 变量。CSR 只有 3.27/4.52 MB，求解器与重复求解累计 RSS 却达 605/562 MB，超过预先的 512 MiB。本轮不重跑那个全量 LP，不改变图规模或内存门。

对曝光 e，令 Q_e 为完整合法 assignment 模式：每个 fiber 选择零个或一个 fitting target。每 target 在同一曝光只能归属唯一 fiber。空 assignment 允许。模式 q 的 target 指示向量为 m_iq，收益为 `v_eq=sum_i g_ie m_iq`，时间占用为原曝光 interval。

```
max sum_eq v_eq z_eq
sum_eq m_iq z_eq <= 1       each target
sum_eq a_je z_eq <= 1       each time atom
z_eq >= 0
```

这是原有限 compact LP 的 Dantzig–Wolfe 重写。正时长曝光的 `y_e<=1` 被至少一条时间容量隐含。模式可行解设 `y_e=sum_q z_eq`、`x_ie=sum_q m_iq z_eq` 即满足原模型。反向，y>0 时每 fiber 的 `x/y` 加上空选择概率构成 simplex；各 fiber 分布的乘积给出完整 assignment 模式的凸组合，恢复 x/y。y=0 时 x=0。故**完整模式全集**与原有限 LP 同值，target 竞争、共享曝光 fiber 容量和 interval 冲突均保留。未完整枚举时，必须以全图 pricing 达到容差来证明 working set 同值至该容差。

sigma_i、lambda_j 为非负 target/time 价。定价 oracle 对每个 fiber 取最大正 `g_ie-sigma_i`，因此全 exposure 最大 reduced cost 是

`P_e=sum_f max_{i in(e,f)}(g_ie-sigma_i)_+ - sum_{j covered by e} lambda_j`。

扫描完整原图即可完成分离；不缩未来 calendar，不取旧即时 top-K。只把违反约束的当前完整模式送入小 master，避免所有 fiber 行和 x 变量。主 LP 内存 `O(N+T+K*(16+L))`，每轮完整 pricing `O(E+A+T)`（time 价以 prefix sum 积分），K 为已加入的模式数，L 是曝光覆盖 atom 数。图和 geometry 仍是 `O(E+A+cache)`；不声称通用 LP 有线性时间保证。

即使 pricing 未收敛也可给出严格有限图上界：把曝光按其起点 atom 分组，对每组计算 `delta=max(0,max P_e)`，在该起点 atom 的 lambda 加 delta。每个曝光覆盖自己的起点 atom，所有新对偶约束因此成立；修正后的 `sum sigma+sum lambda` 是完整有限 LP 上界。保存 residual、修正量和下上界；未收敛不称原 LP 最优。该上界只用于模型证书，不能把上界排名当作正式收益。

## 预声明实验

代码实现前固定：24 次 master solve/branch，working set 总计最多 8192 模式；每轮每个 start atom 至多加入两个新的最高 residual 模式；全图 pricing tolerance `1e-7`。seed 为每 target 最高 nominal edge 对应曝光的 score-max 模式，再加每 start/duration 的最高 score-max 模式，使用确定 tie。共同 recourse 分支复用已有模式，但每分支重新算 g、禁用冲突曝光并重新执行完整 pricing。所有分支共用新首动作结束时刻的 start union。

比较预先包含 B、新定价两首动作、零时长 `y_current=0` 和同 B 时长空曝光。必须至少完成 B/新首动作/空y/空占时；若任何成本门停止，原样保存失败，不给完整 winner。另提供一个物理可执行的确定未来 greedy schedule 为每分支下界：严格不重叠、每 fiber 一个 target、账本取最高贡献；其模型值不能冒称真实天气收益。

机械测试只验证本轮新算法：小有限图完整 pattern LP、原 x/y LP、列生成以及每轮修正上界之间的关系，包含同 target 跨曝光竞争、fiber 冲突、duration interval 冲突、空选择与 blocked first interval。已完成的 32 图旧合同与 72 official operator 精度测试不重复。

两 pilot 各自 fresh process，单线程 HiGHS/BLAS。沿用完整选择门：10 wall seconds 和 512 MiB RSS（含原 B/public 初始化、完整 geometry、图、initial CG、pricing 与所有 common recourse；imports 累计峰值计入 RSS，启动时间另记）。无 scipy 环境时仅复用现有安装，不安装。输入与旧 source/manifest SHA 验证，所有新源码、记录和失败只写 `results/compact_opportunity_algorithm_20261004/` 与本文件。

## 实际结果

新算法机械合同的 24 个分支通过：独立完整 pattern 枚举 LP、原 x/y 小 LP 与全 pricing 收敛后的模式 master 同值；任意非负价格的完整模式枚举 residual 与 fiber oracle 一致；每轮修正对偶上界包含完整 LP 最优；序列化整数续局的 fiber/interval/target-best 账本可行。另刻意只运行一轮，得到 restricted lower `7.482579357921`、修正 upper `12.151316517374`，包住独立全模式值 `9.588462698239`，并正确标为未收敛。没有重复旧官方算子精度测试。

本机默认 Python、pyenv 3.10 与 bundled Python 的默认路径均无 SciPy；用已存在的 UV SciPy 缓存通过 PYTHONPATH 读入，无安装。实际环境为 Python 3.12.14、SciPy 1.17.0、NumPy 2.3.5、macOS arm64，HiGHS/BLAS 单线程。这与旧 trace 的 Python 3.10、正式 NumPy 2.2.6 环境不同；以下为算法/内存机械 pilot，不是严格同环境 speedup 或正式 2CPU Linux 实测。

| 项目 | W90501 | W90502 |
|---|---:|---:|
| initial 完整曝光 / edges | 19,020 / 75,927 | 23,511 / 106,332 |
| 初始 master 行（旧 LP 行） | 836（53,180） | 836（76,502） |
| seed 模式数 | 573 | 582 |
| initial master solves | 22/24，收敛 | 24/24，未收敛停止 |
| 最后 initial master 变量 / nonzeros | 3,995 / 26,294 | 5,456 / 41,948 |
| 全图最后 pricing residual | 5.77e-15 | .008725662961 |
| initial restricted lower | 123.359339443894 | 137.071464868048 |
| initial repaired full upper | 123.359339443894 | 137.401015492098 |
| 与旧已保存 initial LP 值之差 | 1.28e-13 | 未称同值；旧值 137.077729907416 在上下界内 |
| 完整 common recourse 分支数 | 5/5 | 0/5，initial gate 止 |
| 原首次测量选择 wall / peak RSS | 1.538570 秒 / 157,138,944 bytes | 1.201026 秒 / 157,712,384 bytes |
| 证书日志重放 wall / peak RSS | 1.571070 秒 / 154,730,496 bytes | 1.227555 秒 / 159,875,072 bytes |
| 日志重放 import / 进程全部 wall | .350877 / 1.926421 秒 | .343002 / 1.575448 秒 |

W90501 common master 仅 839 行，整个选择最大 working set 为 4,276 个模式、27,906 个 matrix nonzeros。目标竞争和时间冲突的行保持完整，52,896 个 action/fiber 行不再进入求解器。全部当前合法 proposals 仍来自所有可见 target × 四 phase × 原固定合法 duration/program 的定价，未缩成旧 B 菜单。

W90501 完整共同未来域的结果如下。LP 列表示有限确定 science-only 模型的最优松弛；整数列为公开 nominal graph 上可执行、经过独立序列化审查的具体未来 schedule，均只给名义收益。

| 固定首动作 | 当前名义科学增量 | 未来 LP | joint LP | joint 可行整数控制 | CG 轮数 |
|---|---:|---:|---:|---:|---:|
| B | 1.855762374494 | 122.810333252221 | 124.666095626715 | 121.066095626715 | 6 |
| priced0 | 15.184485940836 | 114.891276327095 | 130.075762267931 | 130.075762267931 | 2 |
| priced1 | 18.272663985252 | 111.778243221346 | 130.050907206598 | 128.850907206598 | 2 |
| y_current=0 | 0 | 123.899339443894 | 123.899339443894 | 120.419339443894 | 2 |
| 同 B duration 空占时 | 0 | 123.678188905722 | 123.678188905722 | 121.938188905722 | 2 |

可提交给后续公开状态控制器研究的具体 `priced0` 为 `DARK/3600s`，pointing `(81.6160178,302.9074999)`，10 assignments，完整 JSON 在 `pilot/W90501/PROPOSED_FIRST_ACTION.json`。它的 per-fiber assignments 与旧失败轮的同 pointing proposal 部分不同，因为等值对偶的 target 价可以不同；完整 action 的 nominal score 和共同续局值保持相同。这里未执行正式 observe 动作。

`priced0` 的 50 个未来曝光整数 schedule 与其 LP 上界在浮点容差内一致，并超过 B 分支的完整有限 LP 上界至少 `5.409666641216`。它也超过其余所有候选分支上界至少 `.024855061332`，因此在这五个固定首动作、这个固定未来列域中有整数可行性与最优上界的选择证书。没有从两个上界排序推断真实 controller gain；没有把固定 seasonal C/E、clear mask 和有限 anchor/start/duration 代理迁移为未知天气季节的最优性。

W90502 的失败条件现在是 working set 24 轮未收敛，已经避开原 512 MiB 内存失败；两次完全相同算法均保存该停止。未增加轮数、模式上限、batch、night samples、duration 或内存门，未生成 proposal/winner/common-recourse。这个 negative 结果说明移除 fiber 行解决了模型结构内存，有限轮数内收敛并无普遍保证。

为让根代理直接验数值证书，补了一次**仅证书日志**重放：保存 initial/common 完整 public graph，以及每轮 sigma、lambda、start-atom repair。首次源码、日志、结果和 controls 保存在 `FIRST_MEASUREMENT/`，算法/域/预算不变；不再做第三轮重放。`PERSISTED_DUAL_CERTIFICATE_AUDIT.json` 直接评价这些图和价格、无 solver 重跑：60 轮全部通过，最大证书数值误差 `1.14e-13`，修正后最大 residual `1.14e-13`。W90501 五个序列化 master support 的 target/time 最大负载分别 ≤`1+7e-16` / `1+3e-16`，所有整数 controls 的单 fiber 容量、interval 不重叠、起点 blocked 条件和 max 账本均通过。

首次新合同失败是先调用默认多线程 HiGHS、后调用 threads=1 导致新版 HiGHS 全局 scheduler 返回 Not Set；把合同的所有 LP 调用统一为既已声明的单线程修复。第二次合同遇到 blocked 后空未来域，补零值/零价/空 support 的正确边界处理。失败源码/日志以及修复 source locks 都保留，未调整小图随机 seed 或预算。

## 扩到公开大目录的剩余瓶颈

模式 master 避开了 `N+16*A+T` 行和 `E+A` 个 solver 变量，但完整公共 geometry cache、曝光列和边图仍保存。当前复制式 columns 对同 field/duration 的三个 programs 重复 target/fiber 数组，所有曝光系数仍逐 edge 存储。较大目录、更多 anchor、更多夜内起点或时长会增加 E；本方法不会消掉这个输入扫描成本。下一步可把 `(start,duration)` 几何和 `(start,center)` fiber incidence 分离、program 系数引用共享 cache，同时维持全图 oracle；这只是结构建议，本轮没有改变输入图或再次测试。

每轮全 pricing 的时间为 O(E+A+T)，时间价通过端点 prefix sum 计算，避免 O(A*T) 的展开矩阵。master 复杂度仍随 K 与 LP 退化结构增长；target-best 竞争可使很多字段具有相同 reduced value，W90502 已出现 24 轮 residual 非零。不存在以本 pilot 保证全年正式规模收敛的结论。未来 terrain/forecast 接口、非零已有账本、REQ/required/Jain 等多目标和未知天气联合分布还需另行建模；本轮没有把新 NN 均值接入本消元。

可执行入口是 `results/compact_opportunity_algorithm_20261004/run.py --world W90501|W90502`，依赖原 public pilot 的冻结源与输入（SHA 已验证并另保存到自有 `frozen_prior/`）。主要证据为 `PATTERN_CONTRACTS.json`、`pilot/*/RESULT.json`、`pilot/*/PRICING_TRACE.json`、`pilot/W90501/CONTROL_*.json`、`pilot/W90501/MASTER_SUPPORT_*.json`、`PROPOSED_FIRST_ACTION.json`、两个 certificate audits、source locks 和 `MANIFEST.json`。没有 ZIP、训练、正式隐藏 truth、GPU/容器操作、900 整季、部署或线上提交。
