# 稀疏公开历史下的 report 期望价值：独立新域冻结结果

本轮目录：`results/cold_report_sparse_domain_20261004/`。旧高仰角连续 sensor trial 位于 `cold_report_value_model_20261004/`，其支持域失败、原 bug/test 和冻结结果全部保留，本轮没有覆写或依赖旧 dataset。正式 source 是 e01939d0；host 只读官方 generator/scorer/fiber 模块，没有读取 L4 sealed 或本地私有 fault dates。

## 结论与交付

- 本轮 source/model/DP/package 在 test 前冻结，全部合同通过。独立 test 850000–850015 仅运行一次，之后没有改模型、阈值、actor 或采样过程。
- 16 world 上，固定公共物理动作的 DPfree 总分均值 5298.429；p>.9 free 为 5014.774；oracle 为 5467.681。DP 的 decision regret 为 169.252，p90 为 452.907。配对 DP−p90 为 +283.655，SE 104.635，11 胜 / 1 负 / 4 平。
- 这些是固定动作、best-only science 加 report 的研究分数。测试没有运行生产 strong planner 或 faultv1 闭环，不能据此宣布生产候选比已验证 faultv1 提分。
- 生产候选继承已冻结 faultv1；支持域内才增加 NN/DP 机会。正确 report 次数 >=2 是 NN/DP 支持域外，先交回 faultv1。正式协议没有公开 max2fault 保证；研究内部的 count2 健康吸收不能用于否定第三次真实 fault。
- DP ZIP：`results/cold_report_sparse_domain_20261004/candidate_package.zip`，SHA256 `069c346450412437a96b02d48abe886d4201b7a87dc583c87715b995c42a9823`。36 files，原 29-file baseline 的 27 个代码/资料成员字节不变。Actor 不含 world generator、host labels 或原轨迹私有列。
- p90 conformance ZIP 同目录 `posterior_p90_control_package.zip`。它是同后验对照，不是另一个生产最佳部署断言。

## 从协议得到的价值式

report 不推进模拟时间或 observe rank。正确奖励 100、修复当前 E fault 并恢复两次 free allowance；false 消耗一次 free，额度为零才罚 150。C/E 可混淆，quake 与可修 fault 可以同时存在，不能从低 E 硬宣称已经识别 fault。

令 `p=P(F 当前可修|公开历史)`，`Wq` 强制先 observe/wait/finish，避免零时间 report 自环：

`Rq = p[100 + W2(b_correct)] + (1-p)[-150·1(q=0) + Wmax(q-1,0)(b_false)]`，`Vq=max(Wq,Rq)`。

固定下一个物理曝光的 healthy baseline 下，`Wq=-p·ell+E[Vnext,q]`，其中 ell 是当前 fault 造成的 **下一次 best-ledger 科学机会损失**。比较的是延迟损失、额度以及公开诊断信息的未来价值；不能把所有剩余 science recovery 再加到立即 report 一侧。若下一步必然得到完美诊断，等待仍拿同一个 +100 和之后 repair recovery，立即 report 的额外价值只剩 p·ell。

正确和 false 分支各用自己的同 future kernel。修好的旧事件还可能处于 active 时间段，不能立即重抽一个新 fault。终端没有未来额度价值时，q>0 的任意 p>0 都有正免费 report 价值；q=0 的纯报告阈值为 .6。当前 timestamp 的 report 结果精确说明 F=0，但后续新 fault 的概率仍要保留。

## 新域的公共观测与几何

只使用公开 initialize 的静态 target RA/Dec、flux/weight、夜历、instrument/site/scoring，以及原 strong 的公开动作和开始/结束时钟作 **固定采样设计**。L1 984 observe，L2 1088 observe；高度约 31–89 度、时长 60–3600s、不同 field/az/program。没有复制原轨迹 score、factor、quality、prog_mult、valid、私有 offset 或 fault 标签。

缓存所有公开 assignment 的候选目标，先按 public RA/Dec 核对官方 minimum-altitude；每个独立新 world 用官方 sha256-v1 stress pointing_offset 在 survey 开始生成一次 ±.002rad 的 alt/az 偏移，再按官方 fiber 分类重算实际 hit。quake 在该官方源里改变 weather/efficiency，不改变 pointing；pointing offset 是独立 stress 项。这是本轮明确选择的生成先验，不是正式真实卡默认保证。

正式 `v4_runner.py:820–829` 的 last_result 返回实际 hit target IDs 和六位 score，未返回 factor/quality/prog_mult/valid。history 的接纳只依据这张公开列表：>=3 个已公开 hit IDs，保留零分和饱和，distinct starting slot；未命中的 assignment 不凭 host truth 偷补。H、alt 和方向来自这些已公开 ID 的 public RA/Dec、时钟与 commanded field，actor 不输入隐藏 offset/actual center。零 score 仍可由 closure/weather/directional/geometry nuisance 等解释。

每个目标的 Moon/airmass 使用官方 <=120s mesh 与 slot 边界积分，同 field 的几何共同关系保留。history8 保留方向和 terrain 公告；terrain 首次公告记忆跨 history。8 个公开 score-likelihood token 为 17×9 的 C/E 联合网格加公开统计，另含方向公告、几何、age、nightage、当前公告/forecast、report feedback 等；共 1568 dims。每个 world 独立 dropout 0/.15/.35，形成稀疏历史；这仍不是一个 counterfactual strong rollout。

## 独立世界与拟合

| 域 | seeds | world 数 | records |
|---|---|---:|---:|
| pilot | 810000–810003 | 4 | 独立合同域 |
| train | 820000–820063 | 64 | 64625 |
| cal | 830000–830007 | 8 | 8075 |
| val | 840000–840007 | 8 | 8082 |
| test | 850000–850015 | 16 | 只做一次闭环评估 |

`SAMPLING_LOCK.json` 在训练前锁定 seed、生成/观测过程和 gates。fault count 的 0/1/2 先验为 .25/.50/.25，quake count uniform0..2，每个 weather kind count uniform0..3；其余官方 terrain/rocket/jitter/correlation 参数保留。forecast、bulletin、weather、fault 和 directional effects 都来自同一个独立 world。探索 report 发生概率 .012；任何正确 report 后的每一条后续 score 都按该 world 的 repaired set 重算，不能延用未修分支。

train/cal/val 生成共 36.15s，NPZ 81,298,560 bytes。普通 MLP 1568→128→128→1 在 PRO6000 CUDA 上实际拟合，16 epochs 由 cal NLL 选 epoch3，再一次 affine logit calibration；用时 16.63s，最大 CUDA 1.024GB。冻结权重 SHA256 `aa6ee228fe4e529aab93787901081f569b596a725671c92e1690c14a9702d35e`。cal NLL .120817/Brier .035619，val NLL .060208/Brier .015898，均优于 constant prior；这些 posterior 是统计混合，不是 C/E 的可识别性证明。cal 的最高概率 bins 很小且过度自信，不能把 p>.9 当数学保障。

原始训练日志 epoch14/15 的 cal NLL Infinity 是 float32 的 `1-1e-8` clipping 舍入到 1 所致；logits/概率仍有限，所选 epoch3 与导出 float64 最终 cal/val NLL 有限。原日志保留，没有据此重训或改 selection。GPU float32 与 NumPy 导出 max logit 差 3.51e-6。

## 小 DP 与修复记录

1024 个有限 decision epochs；state 是 posterior15 bins × quake-age3 × public correct_count3，q=0/1/2。phase8 由公开 observing-time progress 定义。训练每条历史同时提供同 future 的 wait / true repair / false-report 下一次公开 score 历史；分别拟合 Kwait/Ktrue/Kfalse，shrink32。loss 用当前 best ledger 下 repaired−unrepaired 的下一曝差，不按目标独立 weather 最大值拼接。

第一次本轮 DP 已保持 correct_count 的 wait/false 不变、true+1，并禁掉 count2 虚构 +100；进一步语义核对发现 count2 pooled loss 仍能生成约 −50 的虚构 future science loss。`report_dp_stage1_nonabsorbing.npz`、`report_core_stage1_nonabsorbing.py`、stage1 val 和合同记录保留。`DP_CONTRACT_AMENDMENT.json` 记录机械修正：研究 max2fault prior 的 count2 loss/V=0，kernel 投影到 p0 保留 quake；NN 权重与 calibration 不变。修复后 val 分数与 stage1 完全相同，没有选新阈值。最终 DP SHA256 `4acb1ddffe391c0e0e16dbda24207c3b9e22a60961701ba6f2b05130d0ea7d25`。

本轮固定使用 free-only DP，未比较 paid-vs-free 选参。科学、required completion、REQ、Jain、data-loss invalidation 的完整未来机会没有纳入该小状态，best ledger 和固定采样路径只是近似。因此不是全题 bound。

## 官方合同与 actor

- 新 world assigned→actual start hit/min-alt 56,608 cases 全等；其中 9368 名义 hit 因新 offset 丢失，5 个名义 miss 获得 hit。
- 官方 target score 2846 cases 六位误差 0；244 report/wait sharedfuture 分支，含 44 true repair continuation 和 66 directional degraded 分支。
- 126 个可穷举两 epoch Bellman tree，误差 2.84e-14；3240 K rows 归一误差 2.22e-16，public count 违例质量 0；quota route/健康吸收/终端奖励核对通过。
- 1957 个 host 与 actor 公开 feature 比较 max差 1.19e-7；公开 H 与官方差 3.33e-16。actor 几何 memo 与原 `_geometric_H` 逐值 bit-equal；233 条全零曝光保留。此 memo 复用已有 full-public geometry，未改变原 strong 搜索。
- 公共 adapter 初版少 hit 时漏更新 quake 公告年龄的失败保留在 `public_adapter_checks*.log`。修复公开公告处理后通过；不改 train world/model。
- false report 原 physical action/pending/C/E/belief clock/ledger 原样释放，true 正常 ingest repair 和 replan；time/rank不变；quota1可用、quota0不追加 paid report。L1/L2 真实公开前三输入的 original/disabled/DP/p90 response 全等。
- `count2_fallback_checks.json` 明确核对生产 correct_count>=2 不调用 NN/DP，但原 faultv1 仍可提出第三次 report。此微域不修改已冻结包或模型。
- 未模拟 data loss。actor 遇到公开 state_resync 清 sparse history，重建支持前用原 faultv1；没有把旧 valid/private labels 当恢复依据。

## Validation、test 与公共支持审计

| 固定动作域均值 | none | p90free | DPfree | oracle |
|---|---:|---:|---:|---:|
| val8 | 5230.337 | 5387.918 | 5536.063 | 5555.963 |
| test16 | 4635.046 | 5014.774 | 5298.429 | 5467.681 |

val DP regret19.900；test DP regret169.252，correct1.0/false1.0/paid0 每 world。test 逐 world 结果以及唯一读测试记录在 `test_evaluation.json` / `SOURCE_LOCK.json`；所有冻结 hashes 在测试后保持相同。

只投影已有公开原 strong history 的支持审计：L1/L2/L3 支持查询数 924/1033/931（旧 trial 为0/0/41），相应 sparse sensor records618/724/631。新 source 可以进入其预声明域，也会给出正 report-wait；这不是新 report 的 counterfactual 结果、不是原 wallclock 恢复或 actualfull 分数。未读取 L4。这些公开 audit 日期/概率没有用于修改候选。

## 下一步

根任务 review 后，使用锁定 ZIP 做真实 strong 闭环，和已完成的 faultv1/可用 exact acceleration 比较；L4 留作之后的冻结 holdout。评估新 DP 对已有强策略的增益和 actor wallclock，不能以本轮 none/p90 sensor 增益替代生产比较。若真实结果失败，应保留本轮完整失败路径，不修改旧 test 或用实际 fault 日期救参数。

实际入口是 ZIP 根目录 `report_entry.py`，project run 为 `python3 -u report_entry.py`。ZIP 无外层目录，保留 baseline 的 `agent.py` / `policy.py` / `research/`，新增 `report_entry.py`、`report_policy.py`、`report_support.py`、`report_core.py`、`sensor_core.py`、`report_model.npz` 和 `report_dp.npz`。仅依赖 `numpy==2.2.6`；官方容器 `python:3.12-slim` 安装至 `.deps`，actor 无 torch/GPU/外部服务依赖。

安全组合 sparse exact 的接口：在另一个组合目录保留本轮 36 files 原字节，追加已冻结 sparse arithmetic 的模块和平台库，新入口先 `sparse_exact.install()` 再 `import report_entry`，最后 `report_entry.agent.main()`。不能导入旧 fault `wrapper.py` 替代 report_entry，否则会丢失本轮 guard 或重复 wrapper。当前 fault-fast 输入 ZIP SHA256 为 `5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`；组合由根任务/原加速 agent 另锁，不改本轮 ZIP 或 test。可复用 `check_public_interface.py` 与 `check_count2_fallback.py` 验证组合微合同。
