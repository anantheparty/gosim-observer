# 线上 RequestCache α–δ 科学分轨迹审计

完成日期：2026-10-04，Asia/Tokyo。独立先读正式官方 scorer/runner，再读取本队完整线上公开轨迹、计算下述分解，最后查阅 `ALGORITHM_PORTFOLIO_ZH.md` 去重。未使用本地 L1–L4 替代线上四卡，未读取 sealed L4 教师标签或未来 truth，未执行 SSH、GPU、新赛季或提交。只写本报告和 `results/cold_science_trace_audit_20261004/`。

**最强可证结论是低 flux 重目标的质量与时长分配存在明确的终局缺口；δ 的 739.44 科学分差的具体因果主因仍未知。** δ 已完成38夜，覆盖8917个目标，但已覆盖目标的加权 best factor 仅0.69054。25个四卡 required 缺失全部是QSO；14个已命中目标在各自历史最好实际 quality 下，按3600秒条件计算也不足factor0.5，另11个没有有效命中。下一步应研究未来优质时间窗及机会成本，不能只把当前曝光拉长或累计重复曝光。

## 真实来源与核验

四卡完整线上目录均为 `formal_v4/results/cloud_request_cache_{alpha,beta,gamma,delta}_20261003/`。每卡具有 `actions.jsonl`、`decisions.csv`、`observations.csv`、`messages.jsonl`、`score_report.json`、`workflow_result.json`、`agent.log` 和 `archive_manifest.json`。当前28个下载输出文件的SHA256全部与各自archive manifest一致。重算终局science与官方report差值为α−0.000009、β−0.000004、γ−0.000021、δ−0.000009，属于六位CSV舍入；observed数量、失效记录和submitted observe时长/assignment数量均一致。

本批来源是 `cloud_request_cache_batch_20261003/summary.json`，官方source fingerprint：

`7bdc340f6247fc0ce961d68c395eded9d88908db34713493120c231d3ef4b81a`

上传ZIP为 `/Users/kamico/Downloads/observer_request_exact_cache.zip`，当前SHA256：

`e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`

70947字节、29文件，当前全部build-manifest成员SHA一致。具体route/上传来源证据在 `results/request_exact_cache_candidate_20261003/{README.md,upload_status.json,package_gates.json,exact_cache_provenance.json}`。上传包保留原Request算法和policy_config字节，只加严格等价缓存并禁用可选remote；四卡都走Request路线。这里直接核验ZIP，未假设当前工作树中所有同名源码就是已上传release。包及输入输出SHA均另存本次 `package_provenance.json` 和 `provenance.json`。

公开catalog分别来自 `practice_cards/<card>/<card>/public/targets.csv`；公开日历和评分配置在相同card目录。没有线上文件缺失。没有对手动作、逐目标ledger或质量记录；下述对手比较只使用任务给定aggregate。α/β的完整agent.log存在，但没有finish最终规划摘要，因此不能分离其CPU基线/REQ构建耗时。

## 正式计分与时序

官方实现：`upstream/gosim-observer-examples/runner/challenge/v4_scorer.py`，以及 `v4_runner.py`。

单曝光 `g=min(flux·duration·quality/450,1)`，science为 `weight·g·program_multiplier`，终局对每个target取有效曝光science最大值。`best`的factor与独立`max_factors`不能混用；required及Jain由最大有效factor判断。program正确声明的乘子为DARK1.20、BRIGHT1.12、BACKUP1.06，错档为1.00。quality是曝光内天气/效率/月光/气团/方向事件积分，延长曝光会改变其平均值。

required阈值0.5、每缺一个−50。REQ必须使用**完全包含在发行时间与deadline之间**的有效曝光，并取单次factor最大值；不是累计积分。数据丢失在公开state_resync时回溯废除observe-index窗口，deadline已结算的请求仍会修订奖励。`targets_observed`统计有有效ledger entry的target，即使score为0，不能直接当作factor≥0.5的完成数。

## 四卡实分、加权覆盖与质量

`W_cov`为至少一个有效entry的target权重和；`B=Σcovered weight·g_best`，其中`g_best`来自最高science曝光。表中的quality比率不是对手归因。

| 卡 | total | science | observed / catalog | W_cov / W_all | B / W_cov | science / W_cov | science / B | required missing | REQ | 终止 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| α | 7248.868252 | 7149.117840 | 9538 / 10000 | 8559.15 / 9100 = 94.06% | .70764 | .83526 | 1.18035 | 4 | 2/2 | wallclock |
| β | 6517.864140 | 6768.101649 | 9187 / 9600 | 8247.75 / 8736 = 94.41% | .70441 | .82060 | 1.16494 | 11 | 2/2 | wallclock |
| γ | 6750.550861 | 6650.828563 | 9421 / 9900 | 8451.90 / 9009 = 93.82% | .68636 | .78690 | 1.14649 | 4 | 2/2 | complete |
| δ | 6423.086757 | 6523.825782 | 8917 / 9400 | 7993.45 / 8554 = 93.45% | .69054 | .81615 | 1.18189 | 6 | 1/2 | complete |

以 `1.2·Σcatalog weight` 为**纯代数天花板**，缺口准确分为未覆盖 `1.2(W_all−W_cov)`、已覆盖不饱和 `1.2(W_cov−B)`、program `1.2B−science`。这个天花板假设所有target都饱和且DARK，未考虑时间/几何/天气资源，不能当作可实现收益或原题最优上界。

| 卡 | 未覆盖缺口 | 已覆盖不饱和缺口 | program缺口 |
|---|---:|---:|---:|
| α | 649.020 | 3002.833 | 119.030 |
| β | 585.900 | 2925.534 | 203.665 |
| γ | 668.520 | 3181.009 | 310.443 |
| δ | 672.660 | 2968.347 | 99.967 |

按任务提供的最新δaggregate，榜首science7263.27、required−150、report100、Jain−1.30、REQ200、observed8515、total7411.98；本队science6523.825782、required−300、report100、Jain−.739024、REQ100、observed8917。science差739.444218，加上required150、REQ100，Jain反向抵消约.561，总差约988.89，受页面两位小数舍入。每个counted target的science比值本队.73163、榜首.85300，仅说明更高observed数量没有保证更高science。对手的覆盖权重、flux、program、曝光及历史重复均未知，不能把差值归因于对手“更长曝光”或“更优QSO选择”。

## δ 的低 flux 质量与时长缺口

| class | catalog权重 | 加权覆盖 | covered best加权factor | science / covered权重 | max-factor≥0.5 / covered | factor=1数 | best-duration中位秒 | 已覆盖不饱和代数缺口 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BGS | 1015.20 | 96.94% | .85220 | 1.00186 | 1997 / 2187 | 1073 | 642 | 174.544 |
| ELG | 3196.00 | 97.84% | .78890 | .93466 | 2630 / 3127 | 1204 | 1078 | 792.129 |
| LRG | 1880.00 | 90.96% | .63945 | .75711 | 1177 / 1710 | 309 | 1298 | 739.849 |
| QSO | 2237.20 | 87.08% | .47090 | .55545 | 512 / 1146 | 105 | 1503 | 1236.943 |
| Star | 225.60 | 99.34% | .90748 | 1.06372 | 726 / 747 | 456 | 225 | 24.882 |

QSO占catalog权重26.15%，是最大单类不饱和缺口；QSO+LRG贡献已覆盖不饱和缺口66.60%，其未覆盖缺口再加550.80。634个已覆盖QSO仍不到factor0.5；678个QSO只有效命中一次。QSO catalog flux中位.17816，ELG .55530；实际best-duration中位仅从1078增长到1503秒，QSO best quality均值.64925，ELG .67049。这里存在明确的flux与时长分配压力，不能用覆盖数替代加权factor。

但不能把这直接叫“曝光太短”或断言所有QSO都应饱和。δ有效曝光≥1200秒已占60.21%时间，其中≥2400秒占25.85%时间、只贡献13.997%最终science增量。长曝光位于不同季节、天气和ledger成熟阶段，不能用这项相关性证明换成短曝光会增分。整个QSO类+0.1加权factor在DARK条件下对应233.784分，只是敏感性，未证明有可行时间窗能实现。

δ有效1077次曝光、962971秒，曝光时长分位P10/P50/P90为107.5/634/2053.5秒，最大3600秒。只有3147/8917个target曾有效饱和，QSO只有105/1146；因此program切换能修复的量级远小于factor/目标选择的量级。677个最终positive best为错档，base364.082342，若允许每个target独立换到最大奖励，最多补72.816468；全体program天花板缺口也只有99.967248。实际曝光只能声明一个program，错档target的实际band不公开，不能把这个乐观数字当成可执行修复。

## Required：25个缺失全部QSO，14个需要更好quality

四卡required总数分别500/480/495/564，缺失4/11/4/6，共25个，全为QSO。已有效hit的14个，无一在其**已记录历史最大quality**下按3600秒得到factor≥0.5；另11个没有有效hit。它们的required失败不属于“program bonus没有领到”，因为判定使用独立factor。

δ四个已hit失败target：

| target | flux | 实际max factor | 实际最高quality | factor0.5所需q（3600秒） | 同历史最高q×3600的条件factor |
|---|---:|---:|---:|---:|---:|
| V4T000504 | .07056227 | .310676 | .735096 | .885742 | .414960 |
| V4T001951 | .07304876 | .051745 | .751794 | .855593 | .439341 |
| V4T002467 | .06405488 | .133657 | .658464 | .975726 | .337423 |
| V4T004230 | .04753409 | .012291 | .808033 | 1.314846 | .307273 |

δ V4T005259、V4T007159没有有效hit。V4T000504已有一次3600秒曝光，其quality.550358、factor.310676。四个目标都未达到所需quality，因此不能声称“把旧曝光拉满3600就救回”。上述乘法仅保持已实现平均quality的条件诊断；延长时间会改变积分quality、altitude和program，不能生成新的真实得分。也不能据此推断这些目标原题不可行：更好天气/效率、月光与气团窗口未被本队选择的反馈仍不可见。

required进度CSV表明α最后5夜从5缺失降为4；β最后5夜一直11；δ最后5夜从8降为6；γ最后5夜一直4。缺失不会在终止时才突然出现；未来质量机会与稀缺长曝光承诺需要进入较早的决策。既有portfolio的required预约路线已在L1/L2等完整对照失败，因此本审计没有提出重新采用同一硬预约。

## 历史 max 与回溯 loss

本次按最终有效ledger逐时间重算真实science增量 `max(score−historical_best,0)`，保留原始score，未把重复raw分数当净收益。δ有14876条有效hit，5959条重复；重复raw score4006.541610，只形成2452.103918净science增量（61.20%）。但重复仍贡献总science37.59%，不能一律禁重复。884条hit不改善science，raw31.760094；48次整个有效曝光science增量为0，合计30052秒。后者可能仍形成REQ/required信息或公开诊断，不能自动称全部可回收时间。

δ loss在2026-11-08T05:16:53Z公开，observe N603，废除[150,169)的19次曝光/280条hit。运行中的science从3926.388145降到3820.661247，撤回105.726898。后续重观测使最终与“保留这批失效entry”的纯ledger差只剩6.856578。γ对应触发撤回61.484164，最终剩5.112715。这个条件ledger比较固定实际动作，未计算避免loss或补偿它的重新规划因果收益。

δ REQ1于Oct26 00:15发行，Oct27 08:30 deadline首次公开结果为6/6，+100。上述Nov8 loss废除了V4T005585的唯一合格action159（factor.781887）和V4T007669的唯一合格action166（factor.545239），结果修订为4/6、−100。两target后来普通factor分别.628186/.777238，但均不在旧请求窗口，不能恢复REQ奖励。REQ2在Nov30 deadline为6/6，+100。这里REQ失败的具体时序已证明，但它是奖励100的撤回，不是science100的直接损失。这项机制已在portfolio `request_quota_failure_20261003`研究，本轮不重复交换搜索。

## α/β deadline 与资源证据

四卡公开日历均38夜。α/β都已进入第38夜，**没有整夜尚未开始**。β一夜无observe，但这不是deadline未执行夜。

| 卡 | 公开night总秒 | actual end UTC | 计划结束UTC | 未执行night秒 | night时间进度 | 模拟wall进度 | accounted / agent秒 | 在途响应忽略 |
|---|---:|---|---|---:|---:|---:|---:|---|
| α | 1126800 | Nov11 03:05:57 | Nov11 08:15 | 18543 | 98.3544% | 99.4253% | 900 / 883.717 | true |
| β | 1078200 | Nov25 03:04:27 | Nov25 08:15 | 18633 | 98.2718% | 99.4223% | 899.991 / 883.168 | true |
| γ | 1110600 | Nov16 08:15 | 同左 | 0 | 100% | 100% | 883.744 / 867.097 | false |
| δ | 1061100 | Dec1 08:15 | 同左 | 0 | 100% | 100% | 587.273 / 574.022 | false |

截止丢失最后约5.15小时的机会仍是实质问题；缺失这段时间的实际潜在science未知，不能把两个截断卡的质量不足全归于策略，也不能称它们失去了后半季。α/β完整日志没有最终planner摘要；ZIP禁remote factory且初始公开日志为disabled/0秒，γ/δ最终摘要remote_calls/seconds均0。γ规划827.921秒，其中CPU baseline600.860421、REQ列构建225.638718、DP1.373381；δ548.894秒，分别458.527225/89.341792/.984597。CPU基线和REQ构建是观察到的成本，DP本身很小；α/β没有独立拆分数据。

本地同ZIP首决策JSONL gate及δ完整公开REQ2 gate存在，后者原版13.501秒、缓存8.633秒、453列/DP/6个动作逐项相同。没有找到同源ZIP、同线上α/β初始化及900秒预算的本地完整单卡复现输出；`gpu_https_budget_L1_20261003`是另一数据/源快照，不能替代。未为补齐这项证据启动新赛季。

旧官方Request α到Oct31 07:55:29，science5942.269118；本次缓存α继续相同提交前缀到Nov11，science+1206.848722。β旧到Nov22 06:24:17，继续推进science+179.623937。该差包含额外进度、缓存、禁旧health和机器分配混杂，不能当缓存独立因果收益。δ旧Request475.229秒、本次587.273秒、VerifiedPortfolio725.685秒，actions/decisions/messages/observations/report逐字节相同；平台耗时波动确有证据，不能单靠单次秒数证明算法改进。

## 可行动结论与限制

优先改动的研究对象应是**低flux重目标与未来优质时间窗的联合机会成本**：science ledger仍有约2968的已覆盖不饱和代数缺口，QSO/LRG占其中约66.60%；required缺失目标又全部位于更低flux QSO尾部。应以真实闭环重新规划验证是否能将优质长曝光资源从低增量候选移给这些目标，并同时结算science、required、REQ、Jain和loss。不是推荐所有target饱和、盲目加长、禁重复，或再次采用已经失败的硬预约/旧scenario bank。

另两项明确工作边界：α/β首先应保留完整900秒执行机会；δ已完整，program独立修复的乐观量级不到100，最终不可恢复science loss约6.86，都不能单独解释739.44。对手动作未知，本队缺少对“未选择的时间窗/指派”的真实反馈，本审计没有完成策略因果反事实。因此最大**观测到的终局缺口**与最大的**已证明可执行收益**必须区分；后者本轮没有新得分实验。

## 复算与结果

在仓库根目录执行：

```sh
python3 formal_v4/results/cold_science_trace_audit_20261004/analyze.py
python3 formal_v4/results/cold_science_trace_audit_20261004/supplement.py
```

主结果为 `summary.json`、`four_card_summary.csv`、`deadline_budget.json`、`duration_quality_hurdle.json`、`class_trace_stats.csv`、`prior_official_comparison.json`。每卡另存逐target、class、flux、duration、program、required、requests、progress、action/hit marginal CSV。`provenance.json`和`package_provenance.json`提供全部来源SHA，`audit.json`核验计分重算、source/package和边界；`source_manifest.json`记录本次新脚本及报告SHA。
