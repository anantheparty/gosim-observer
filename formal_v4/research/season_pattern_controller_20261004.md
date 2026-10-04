# 全实际目录共享季节图与时间路径控制器，2026-10-04

本轮没有得到可采用的新科学策略。完成了共享数据的全季有限图、实际非零 public ledger 成本测试、target-dual + interval DP、共同可行续局比较，以及接原最强 actor 的保守入口。四个真实目录状态均未通过默认采用条件；不申请 900 秒完整赛季，不制作提交 ZIP，不修改原最强源码。

## 随机 best-only 与确定代理的界限

正式 scorer 的科学账本为每目标最大 **program-multiplied score**；required/Jain 则分别看最大 raw factor，不是科学最佳贡献对应的 factor。REQ 要求曝光完整位于公布的 request 时间窗。报告可改变设备及随后反馈，data-loss window 又依赖 observe rank。因此本轮的固定贡献模型不是正式多目标或自适应天气最优性证明。

对一个已有公开最佳分 B 的目标，随机贡献 C 的正确单次科学边际是 `E[(C-B)+]`，一般不等于 `(E[C]-B)+`。例如 C 以各 1/2 概率为 0、1，B=.25：前者 .375，后者 .25。两次独立贡献的 `E[max(C1,C2)]` 为 .75，而 `max(E[C1],E[C2])` 为 .5。故即使每次边际均值准确，随机复访价值也不能由“每 target 最多一次”的确定 LP 表示。共享天气、设备、terrain 与未来 feedback 还要求共同路径分布，不能把独立 target 边际 NN 均值直接塞进该消元。

确定模型中，固定 `g_ie=(c_ie-B_i)+`，可删去重复 target 的弱 assignment 而保留其最好贡献；曝光本身与时间占用不删。因此 target-cap 有效，且 fiber assignment 模式的完整模式 LP 与固定有限 x/y 松弛同值。这项证明只覆盖当前明确固定的贡献与 valid mask。随机扩展应使用 joint scenarios 的 score-layer coverage；root 已独立写入 [STOCHASTIC_PATTERN_MODEL_ZH.md](STOCHASTIC_PATTERN_MODEL_ZH.md) §7，本轮没有用边际期望偷换此模型。

## 全目录共享表示

actor 输入只有公开 targets、calendar、既有 public hit scores/messages、公开 forecast/terrain model 与 C/E belief。研究 harness 从已经发生的原强轨迹逐条重建状态，只向 actor 推送当前时间前的 hit target IDs/scores、消息与报告结果；不用 observations 的 factor、quality、valid、truth event 时间。历史动作装入 pending 只用于解读下一条真实公开反馈。报告明确 **不声称历史 action parity 或原 actor 完整状态字节相同**。所有状态均保存当前 snapshot、公开 ledger 与 prefix SHA。

未来只取公开 calendar 中一小时 mesh，duration 为 `{900,1800,3600}`，各 program 均保留。每个空间 bin 以几何 centroid 最近的 target 为代表，不按 flux/weight/旧 rate 筛选；未来代表取两个对角 fiber phase。当前诊断图取全部可见 targets × 四 corner phases，产生真正不同于 B 的完整首动作，而不是旧 weak menu。所有候选 field 都接全部 fitting target，KDTree 只作包住 field 角点及 phase displacement 的保守邻域筛选。完整 public targets 均加载；以下图的 incidence 覆盖全部 7800 或 8600 targets，但这不证明覆盖连续 pointing/action 空间。

bank 对每 `(start,duration,target)` 存 factor、band、min-alt eligibility；对每 `(start,field)` 只存一次 target/fiber incidence。program 与 duration action descriptor 引用这两个 bank，不复制 target/score/fiber 边。band 积分排除 E/terrain，raw factor 积分含 C/E/公开 future field；mesh 跟公开 slot 与 ≤120 秒 pieces。该积分是明确的条件代理，不能称已知未来实际天气。

## 原 pattern master 的实际规模结果

单线程现有 bundled Python3.12.14、SciPy1.17.0、NumPy2.3.5/macOS arm64。读已有 UV cache，无安装。本轮不是正式 NumPy2.2.6 / 2CPU Linux 相同环境测量。L1 第18夜独立运行；L1 第8夜与 L2 第18夜独立进程并行，成本含本机并发竞争。每分支 LP 限 4 秒，按实际时间/上下界停止，没有重复旧 24 轮 gate。

| 状态 | public 已有科学分 / 正分目标 | 未完成 required bound | future starts | actions | shared incidence edges | graph arrays | build / selector 秒 | 峰 RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| L1 夜8 | 2848.635837 / 4783 | 3 | 199 | 2917131 | 9828461 | 191261759 B | 27.591 / 44.240 | 885800960 B |
| L1 夜18 | 4808.828348 / 7017 | 2 | 119 | 1815072 | 6163426 | 118111326 B | 16.650 / 33.181 | 683786240 B |
| L2 夜18 | 4031.582263 / 6659 | 7 | 151 | 2479452 | 8711074 | 163840262 B | 22.933 / 39.511 | 720109568 B |

三状态均无当前 active request。L1 夜18的完整三 program/duration edge 引用数为 53,889,168，未把它们全部实体化为 score 边或 LP 行。三个状态均产生不同首动作，但有限 master 未收敛。原 support 的 greedy rounding 比较出现 +9.6354/+21.0948/+28.6444 的“可行续局差”，均不作 winner：各分支 rounding 质量不同，且 B 的 LP 上界明显高于候选的可行下界。尤其 L1 夜18，B 可行1094.296、relaxed lower1533.686、upper1558.624；所谓候选可行1115.391并不足以证明优于 B。

这个测量说明共享表示可以容纳真实目录，但 33–44 秒每动作重建不适合季节预算；不能从 192-target 小 pilot 的 157MB、1.5 秒迁移生产结论。

## target-dual + exact time path

对固定 target-cap 只拉格朗日化 target 约束，令 `sigma_i>=0`：

```
D(sigma) = sum_i sigma_i + max_nonoverlap_path sum_e w_e(sigma)
w_e(sigma) = sum_f max_{i fitting(e,f)} (g_ie-sigma_i)+
```

每个完整曝光由 native fiber oracle 赋权；相同 start/duration 的所有 field/program 只留权值最大的 interval arc，然后 weighted-interval DP 精确解共享时间。原百万级曝光仍全量扫描；DP 只保留数百 arcs，无 exposure solver 变量或 time solver 行。interval graph 的 clique 时间容量多面体是整数的，充分优化 sigma 后得到同一有限完整 pattern **LP** 值，不是原整数问题 exact。

盒 `0<=sigma_i<=max_e g_ie` 安全：超过最大正贡献后，i 在所有曝光的 reduced contribution 已为零，降低至盒边界不增加 D。oracle path 记录选中 target 次数 n，次梯度为 `1-n`。实现用具体物理路径的 Kelley cuts：`theta >= raw_path_gain - n·sigma`，小 master 最小化 `sum sigma + theta`。master lower 是有限 dual optimum 下界，完整 oracle 的 D 是 LP 上界；每轮保留 best upper。路径按真实最高贡献账本重指派、容许复访后只结算最高分，给可执行整数下界；保留 best physical lower。有限时间未收敛，绝不把 D 或 Kelley master 值当实际得分。

## L2 夜8实际图、成本失败与修复

第四状态加载全部 8600 targets、既有公开科学分2198.719561、3389正分目标、26个 required debt bound、0 active requests。图有231 starts、430618 fields、3709602 actions、12845824 shared edges，完整三 program/duration 引用数110431545；arrays245455472 B，incidence覆盖全部 targets。初次 build33.932秒、峰RSS1010008064 B，已保存 `SHARED_PUBLIC_GRAPH.npz`，以后实验复用 SHA 相同公开 bank，不再重建图。

首版每 oracle 对370万 action 做排序，只压成652条 interval arcs却耗约1.38秒；5秒初始阶段仅4轮，3秒 common branch约3–4秒。最终 B 胜，完整 selector55.670秒（包含公开图保存等诊断开销）。原始 `time_dp/` 与 `FIRST_MEASUREMENT_target_dual_dp.py` 保留。

随后改成 native 单次扫描 `O(A)` 压缩，同一固定图/模型/时长/预算/原始 ledger，不改 duration、domain 或天气参数。cached load约.180秒，每完整 oracle约.238秒。最终包括5秒 initial、三个3秒 branch、共同路径重估，selector16.573秒，峰RSS594149376 B。这仍不是 Linux正式预算测量；新 source 下的缓存载入避开首次33.9秒构造。

这里也发现并修正了一个会制造假 winner 的比较错误。三分支有限 oracle 找到的路径质量不同：独立下界比较一度给 priced0 +98.25999。这个数保存在 `FAILED_UNSHARED_INCOMPARABLE_INCUMBENTS/` 与结果的 `unshared_incumbent_branches` 中，不能算首动作收益。最终把 initial/所有分支找出的57条时间路径作为共同 pool；每个首动作都删冲突 interval，再用其新的最高分账本重新做每 fiber 指派。这才比较相同续局搜索结果。

| L2 夜8首动作 | 当前名义科学增量 | 共同57 paths的 joint 可行下界 | 完整有限 dual 上界 |
|---|---:|---:|---:|
| B：DARK/2431秒 | 21.786628080481 | 1536.840572832222 | 5341.123120001863 |
| priced0：DARK/3600秒 | 22.792781337619 | 1515.062431570760 | 5303.899673906675 |
| priced1：DARK/3600秒 | 22.653984323062 | 1515.593944751741 | 5304.555406934930 |

公平比较保留 B。初始 best upper5339.742212、best feasible1530.245873、Kelley lower2814.714087，dual gap2525.028125。Kelley在很少 cuts时价格剧烈切换，native时间降低没有解决收敛。没有据此增加数据、天气幅度、budget或 test救参；此预算下没有可推荐的实际 winner。

## 可执行 actor 入口与采用条件

`results/season_pattern_controller_20261004/season_entry.py` 接原最强 SHA `5b00e6...` 的38成员原字节副本，入口继承原 PersistentPolicy，并只替换 planner.choose；原 guard 决定 report、false-result cached action release、正确修复后的反馈重规划。所有 ledger、factor proofs、REQ deadline、fault/notice/closed等待仍由原 actor处理。任何 active REQ、原 request-DP active 或 B 中未完成 required assignment 都直接保留 B。候选还不得降低原 short-step robust uniform completion 的任一 RA-band 数量。

季节 graph 首次 eligible public state构造一次；不逐动作复制全图。future物理 bank固定于这一公开状态，随后每两个夜仅对实际非零 ledger重规划。当前首动作的条件物理 field/belief另由当下公布信息更新。该 freeze 是明确近似，未模型未来报告修复、后续公告/terrain posterior和天气 feedback。

非均匀 sigma只供原强全候选搜索产生一个新 science proposal，**不据 sigma/rate本身采用**。最终用同 graph重新解 B/候选的 future time paths，合并全 paths，共同重新结算 max ledger。默认采用 gate 为 `candidate_joint_feasible_lower > B_joint_full_finite_upper + 1e-7`；未达到时保留原 B/prediction。这个 gate即使通过也只是固定有限确定模型证书，还必须正常2CPU/2GiB/900整季对照后才谈正式收益。

源码限制额外季节规划计量220秒、首次 graph55秒、每个oracle2秒、每两夜一次、reserve90秒，超时/内存/异常回原B。这里预算检查是软中断，单 native scan/graph chunk会有小超出；不是完整季节900秒保证。初始57MB保存目录也不代表运行RSS。Mac大目录真实测量与额外cap支持进一步工程验证，但缺Linux native build与正常完整gate，不申请整季。

曾写过的直接 price-overlay scorer 存在 `DEFERRED_price_overlay_controller.py`/`season_controller.py`，不由最终入口导入；它没有从共同 continuation作采用判断，本轮不采用。

## 合同、接口与剩余门

`CONTRACTS.json` 的12新 synthetic模型通过：native shared fiber oracle与独立Python值一致，compressed interval DP与全部interval子集枚举一致，任意非负sigma的完整DP upper包住独立完整pattern LP，Kelley lower位于LP下方，physical max-ledger lower位于LP下方；含空未来域。只验证新 oracle/DP/bounds，没有重复旧192-target pilot或官方72算子测试。

actual adapter audit：L2夜8因原B含unfinished required，.093秒保持原B、额外规划0；L2夜18加载由较早夜8公开状态冻结的bank，实际public ledger不变，真实进入价格规划，约2.2秒后仍B。request/required guards和原fault类继承通过，不声称官方runner整季或历史全状态 parity。源码提供 `build_native.py`，当前只已编译/检验macOS `.dylib`；Linux `.so`、SciPy生产依赖、真实2CPU/2GiB protocol与900完整赛季尚未验证。

最终L2夜18 adapter具体记录13轮、204个正价格、upper2911.919553/feasible905.070677，原strong搜索未产生不同action，原B为DARK/151秒。`SERIALIZED_CONTROLS_AUDIT.json` 另直接读最终saved graph和controls、不重跑solver，三条共同续局204/201/203个曝光的fiber/eligible/nonoverlap/最高账本全部通过，贡献误差0。audit初版反复解压NPZ浪费时间，终止该自有进程exit143后改为一次cache读入；原空日志保留，不是数学gate失败。入口在SciPy或native库不可加载时明确回原exact-fault actor，这个fallback也不算新策略部署。

下一有意义的研究应解决实际目录 target-dual 的有限预算收敛、共同路径 incumbent强度与 future物理freeze偏差；或者接正确 jointpath score-layer模型。继续增加旧固定轮数、从不同质量的分支下界选winner、或把边际NN均值放入target<=1，都没有依据。本轮建议保持当前最强正式actor。

全部原始正负结果、公开输入/账本、共同path pool/具体controls、失败比较、编译source、Mac成本和source SHA manifest只在本目录；没有futuretruth、GPU/外部服务、git、900整季或线上提交。
