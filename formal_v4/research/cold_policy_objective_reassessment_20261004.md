# 正式终局目标与强策略的独立复核：已有正分证书被错误等待吞掉

2026-10-04。先读官方 v4 scorer/runner 和当前最佳 ZIP 的策略源码，再查 `ALGORITHM_PORTFOLIO_ZH.md` 与旧 closure 研究，最后用已发生的公开反馈量化。未读封存 L4 教师、未读 future truth、未训练、未自行启动新完整季节、未提交、未操作 Git。独有结果目录为 `formal_v4/results/cold_policy_objective_reassessment_20261004/`。

## 1. 可复核结论

**强策略把某个 field 的全零 hit 无条件当作全站关闭，即使同一个官方天气 slot 内先前已有完整正分曝光。这个错误分支在当前最强策略对应的 L1/L3 真实公开轨迹中发生，能直接取消仍可使用的观测时间。** 新候选复用已发生的正分证书，不增加用于诊断的 probe；恢复一次正常规划，并把这次动作限制在已证明开放的同槽内。

当前 L1 一次错误等待526秒，L2没有严格触发，L3三次共1627秒。旧线上δ六次共2478秒，全部在首夜。这个机制的规模是局部几十科学分的候选机会，不能解释δ的739.44科学分差，不能当作对手算法归因。

root已授权并在 **06:43:42.126633 UTC** 启动唯一一次正常 L3 完整候选对照：Rhodes PID2851723，2CPU(22–23)/2GiB/900秒、network none、actor没有 truth 挂载；新结果归 `formal_v4/results/public_open_actual_20261004/`。本报告写作时完整结算尚未交付。以下是严格来源/源码结论和公开 snapshot 比较，不是最终提分。

## 2. 正式评分决定了哪些差距有意义

官方源码位于 `formal_v4/results/cold_target_score_distribution_20261004/official/challenge/`：

- `v4_scorer.py:393–402`：单曝光 `F=min(flux*actual_duration*mean_quality/450,1)`，science=`weight*F*program_multiplier`。`mean_quality`积分天气、仪器、Moon、airmass和方向事件。
- `v4_scorer.py:443–476`：每个目标的终局 science 是有效曝光 science 的最大值；raw factor 最大值单独保存。重复曝光不累计积分。较低 F 可因更高 program multiplier 更新 science；反过来也可能更新 raw completion 而不更新 science。
- `v4_scorer.py:505–534`：required按最大有效 raw factor≥0.5，缺一个−50；Jain使用RA band完成比例，边际有正有负。曝光数量和 observed target 数量不是这些项的直接目标。
- `v4_runner.py:763–783`：program band 对每个 target 的整个实际曝光积分；一个动作只有一个声明 program，但各 target 可落入不同真实 band。玻璃/fiber几何共享同一指向和曝光时长。
- `v4_runner.py:526–554`：loss按触发 decision时的 observe 总数冻结索引窗；wait不增加该总数，observe增加。新增正常曝光也可能改变后来撤销哪些旧曝光。

生产源码已经使用 `max(w*F*m−B,0)` 的科学增量并联合选择 program/fiber winner。它的目标候选不是覆盖数。把当前策略称为“只追求多观测目标”不准确；确实存在的是未完成低 flux 重目标、未知未来质量和共享时间/field容量的压力。

现成线上δ审计中，已覆盖加权 best factor=.69054，QSO/LRG占已覆盖不饱和代数缺口66.60%。δ program纯代数缺口99.967，远小于739.444科学分差。该代数差假定全部目标都能饱和且DARK，不是可实现上界。旧 report/debias/弱菜单 rollout/current-rate λ/required硬预约/全局小菜单路线已有负结果，本轮没有重启。全季 shared pattern/time/fiber分配由独立 `season_pattern_controller` 继续，本报告不重复它的机制。

## 3. 明确错误的源码链

当前最佳基底 ZIP：

`formal_v4/results/cold_sparse_science_runtime_20261004/observer_sparse_exact_fault_20261004.zip`

SHA256=`5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`。逐成员确认它与 `fault_package/` 相同。

其代码链：

1. `fault_package/research/feedback_model.py:67–75`：所有 hit score≤5.1e−7时返回 `closed_evidence=bool(len(scores))`，没有区分局部遮挡、全站关闭或先前证据。
2. `fault_package/policy.py:171`：把该值赋给 `self.last_closed`。
3. `fault_package/policy.py:342–348`：`closed or last_closed`立即清空 pending，wait到下一公开 slot边界，正常 field/planning没有执行。

### 为什么同槽先前正分是严格反证

`v4_weather_simulator.py:810–859`先更新一次该 slot 的背景关闭状态；ALL event只要与 slot任何部分相交，就把全局 `force_close`和全局倍率折入这个 slot 的 truth row。包括“实际时刻只覆盖 slot一部分”的 ALL事件，`is_observable`也不在该 row内部变化。`v4_scorer.py:195–215`在同 slot内只返回同一 `SlotTruth`；`v4_runner.py:749–776`另行交给 scorer 的只有方向事件。

因此，完整落在 `[slot_start,slot_end)` 内的一次合法曝光若有公开正分，则该 slot 的 `is_observable=True`。公开分数是本次贡献，不是最高历史分；六位舍入的严格正分仍足以证明原贡献为正。后来的另一个 field全零与“整槽全站关闭”相矛盾。

这不证明其它方向一直 clear，不证明天气好、不证明 fault不存在，也不证明将来新 slot开放。跨 slot的正分没有该证书；候选明确排除它。

### 当前最强的最小真实例

L3原强控制第一夜，公开900秒 slot=`2026-11-16T05:30:00Z–05:45:00Z`：

- observe55=`05:30:00–05:31:18`，完整同槽，3个正分 hit；
- observe56=`05:31:18–05:36:47`，完整同槽，全部 hit为0；
- 下一 decision输出 wait到`05:45:00`，取消493秒。

当时没有当前公告、没有活动REQ。原控制自身刚获得的公开正分已反证全站关闭。证书不需要 know future weather、复原 seed 或读取 host quality/factor。

## 4. 真实触发规模

`analyze_public_closure.py`仅读取 action、时间、hit ID、六位 score；读 CSV时丢弃 host factor/quality/prog_mult/最终valid列。证书使用过去已收到的测量，日后loss不撤销这项物理证据。

严格触发要求：先前正分曝光完整同槽；全零曝光也完整同槽；随后的真实动作是 wait到该槽末；无当前 ALL rain/storm；剩余至少60秒。

| 轨迹 | 全零后槽末wait次数 / 秒 | 有严格同槽开放反证的次数 / 秒 |
|---|---:|---:|
| 当前最强对应 L1 | 27 /14979 | 1 /526 |
| 当前最强对应 L2 | 30 /15630 | 0 /0 |
| 当前最强对应 L3 | 46 /22899 | 3 /1627 |
| 旧线上α | 28 /16133 | 1 /246 |
| 旧线上β | 21 /11036 | 4 /1164 |
| 旧线上γ | 19 /7963 | 0 /0 |
| 旧线上δ | 46 /24862 | 6 /2478 |

不能把第二列所有等待都称为浪费。缺少正分证书时，全零仍可来自全站关闭，保留旧分支。第三列是明确拒绝“全站已关闭”推断的真实触发，仍不是可回收终局收益。

L1/L2的稀疏故障v1完整轨迹已由 root验证与原故障v1 actions/observations/messages/score相同。L3使用原故障v1完整真实控制，total6553.045588；当前稀疏算术包的 L3完整parity尚未执行，不用 L1/L2 parity冒称已执行。

## 5. 新候选是具体控制分支

文件：`candidate_package/public_open_recovery.py`、`public_open_recovery_entry.py`。

1. 原 public ingestion/ledger/calibration正常执行。另存完整同槽正分的slot key和公开anchor。
2. 原 closure flag出现时，只有同slot正分和同slot全零同时存在才考虑恢复。
3. 活动REQ存在时不恢复；任意非terrain/earthquake当前公告时不恢复；地形条件域出现conflict时不恢复。
4. 候选沿用原 production地形后验的条件域。计算整个剩余同槽期间每个 target的精确最小 altitude，包括 lower culmination；只允许 minAlt高于所有剩余地形box高度上界的 targets。这是原 reference terrain域内的clear条件，**不是正式协议保证terrain maxAlt≤50°**。
5. 将 planner.tmax暂限到slot末，用原正常 planner、全部原band/program/fiber/required/Jain scoring选择动作；恢复 tmax。没有另写一套弱菜单。report quota/faultv1逻辑及原物理源码保持原字节。
6. 若没有合法候选，继续原槽末wait。被恢复曝光的正常反馈继续走原代码。stderr和summary记录公开证书/条件clear域/动作，便于完整对照审查。

没有新增 pure probe，没有扫描阈值。第一次改变也是正常科学动作，它增加observe rank。因此没有声称“无条件弱支配”。

## 6. 四个公开 snapshot已具体改变动作

通过冻结真实 actions和公开 feedback重建账本/天气拟合/校准/地形状态，最终只调用一次原正常 decide。官方长 wait_until可产生多个CSV wait row；这些没有ledger更新。本比较是公开反馈状态重建，不冒称逐 decision正常重跑了整个actor前缀。

| 状态 | 原wait秒 | 候选时长 / targets | 整余槽最低目标alt / 条件terrain上界 | point model预测science增量 |
|---|---:|---:|---:|---:|
| L3 rank56 |493|65 /14|55.9051° /50°|1.6544|
| L3 rank59 |553|400 /15|50.4384° /50°|9.4054|
| L3 rank61 |581|199 /15|53.6660° /50°|4.8958|
| L1 rank420 |526|322 /14|59.8629° /47°|4.9628|

四个control都精确输出原槽末wait；新候选没有用 host truth选clear方向。全部assigned目标在**整个剩余slot**内的minAlt已另用官方 `min_altitude_during`核验，不只检查当前指向中心或目标开始位置。shared field/fiber/program选择仍由原规划器完成。

Mac单次正常planning约84–130ms，新增全目录geometry约1–1.8ms；这是本机公开snapshot测量，不是2CPU容器完整预算证书。第一次 isolated planning为83.64ms，其余批量比较有并发测量。L3三个首动作 point预测 science之和15.9555不是可叠加的真实最终增分；候选重规划会改变后面是否重访、best和loss。

按L3通常scientific吞吐约.006–.025分/模拟秒做敏感性，1627秒对应约10–41分规模。这个范围既不是下界也不是upper bound；后来的普通动作可能本来就拿到同一批目标的更高best。完整结算才回答保留了多少增量。

## 7. 查重及其它审查结果

### 旧命题与本轮增量

`CLOSURE_PROBE_VALUE_ZH.md`已经证明全零不能推出全局关闭、同槽正分语义，并提出 ALL rain/storm wait时主动probe→adaptive-follow的三分支候选。本轮不冒称基础命题新发现。

本轮新增的是：确认当前最强实现仍违反该语义；量化其已发生的严格触发；不插入pure probe地复用已有证书；给出保留强正常planner的可执行控制分支和真实当前best动作差异。旧band可行集合投影负实验改变C/E planning env；本候选不投影C/E或训练NN。

### 请求DP与baseline奖励不一致，但缺实际触发

`request_deadline_common.py:352`先用活动REQ分摊奖励选baseline；`:379–386`即使 complete-quorum DP拒绝或不可能，也返回这个已有baseline。一个不能完成的请求仍可能通过fractional shadow reward影响动作。这是模型层不一致，但当前 L1/L2/L3 final log均`infeasible=0,rejected_by_cost=0`，旧线上γ/δ同为0；α/β没有完整final summary，不能把缺日志误称0。没有真实拒绝触发，本轮停止，不将它用于解释分差或扩一次季节。

### 新物理NN与生产数据分布的来源差异

已冻结 `data_pipeline.py:27–40`使用 L1/L2旧公开action/time模板，在新独立weather world上重新生成feedback；L1目录7800目标/32夜、L2 8600/36夜，不是2048target小pilot。`:120,129`移除全部 observation request且active_requests=[]；`:161–168`用每64次曝光的固定free-allowance report日程；`:107–108`显式指定各事件count prior。

因此其历史分布由固定动作带和固定report schedule生成，与正式 strong faultv1闭环动作、真正REQ发行和内生观测时间不同。此事实限制模型移植范围。它**不解释**有限24world validation里NN已经输给在同一新分布上评价的point control，不能据此救参或重新训练，也不否定pure physical F/b输入排除weight/best/program/pointing的数学契约。

## 8. 全季裁决必须包含后效性

L3原真实control公开resync发生于2026-12-03T04:10:34Z，N759，fraction[.119871,.121387]产生索引窗[90,92)。候选新增observe可改变 N/索引/触发decision时刻，即使额外曝光全为正分也可能撤销别的旧witness；Jain也不单调。该未来事实只用于事后审查，候选不会读它。

root的一次正常 L3对照应核对：冻结ZIP/source、正常预算/完整survey、首次分歧确由公开证书触发、所有recovery的actual feedback、report/REQ/required/Jain/loss完整结算、真实final总分。比新增曝光即时science或选择好的posthoc field不够。若完整对照为负，保留错误推断诊断，停止本候选，不扫描参数。

## 9. 冻结交付

候选 ZIP：`formal_v4/results/cold_policy_objective_reassessment_20261004/observer_public_open_recovery_fault_candidate_20261004.zip`

SHA256=`bab39ca84027531ecd0fd9c60fe4eabe219e1914d2739325ee7a9bd3af730fcb`，92195 bytes。

项目 metadata明确 `run=["python3","-u","public_open_recovery_entry.py"]`，因此正式runner能选择新entry。原38个成员中36个逐字相同，仅 `observer.project.json`和`build_manifest.json` metadata更新；新增两个hook文件。原 actor物理/REQ/report/faultv1/native源未改。完整40成员hash在 `SOURCE_FREEZE.json`。

原L3控制：`formal_v4/results/strategy_reassessment_actual_20261004/seasons/fault/L3/`，total6553.045588，完整raw/source门检来自 `ROOT_FAULT_FOUR_CARD_RESULT.json`。候选当时没有完整季节结果；root启动的正常唯一对照与结算独立归档，不把本报告的公开snapshot值写成真实收益。

主要证据：`PUBLIC_CLOSURE_TRIGGER_ANALYSIS.json`、四份 `*_PUBLIC_SNAPSHOT_COMPARISON.json`、四份严格 public prefix、`PUBLIC_SNAPSHOT_ACTION_GATES.json`、`SOURCE_FREEZE.json`、`AUDIT.json`、`MANIFEST.json`。

## 10. 追加：正常完整L3为负，停止该候选

**2026-10-04 07:06:36.185168 UTC，root已核验完整L3：候选6501.055556，对原故障v1控制6553.045588，Δ=−51.990032。不采用，不扩大其它卡，不调整阈值，不再重跑。** 本节是最新实际结论；前文“结果待交付”保留为试验前证据的时间记录。

权威结果：`formal_v4/results/public_open_actual_20261004/ROOT_ACTUAL_RESULT.json`。正常2CPU/2GiB/900秒协议，survey_complete，accounted433.177秒；root已核验全部冻结source及原始输出SHA。

| 终局分项 | candidate−control |
|---|---:|
| science |−52.215562|
| Jain |+.225530|
| REQ |0|
| report |0|
| required |0|
| 总分 |−51.990032|

前60条实际actor action逐字相同，首次分歧确为首个 `public_open_recovery`：候选在`2026-11-16T05:36:47Z`输出65秒/14目标曝光，控制wait到05:45。完整候选共4条真实hook events；对应曝光均有效，actual hit数14/13/15/15，原始本次score和分别1.818239/1.919323/9.495538/1.957279。这些即时正分没有保证终局best-only科学分增加。

候选 targets_observed=8377，控制8329；候选观察数量更高，科学分仍更低。所证明的同槽全站开放语义及局部错误推断仍成立，但该控制分支改变后续规划、复访、best账本和observe rank，**语义正确不保证这个启发式移植提高最终得分**。本轮只报告完整对照的负结果，不把−52.215562归因于某一个未经独立识别的后续机制。

本次沿用已存原故障v1 L3控制，没有额外重跑完整native控制；60条相同前缀不能冒称整季native parity已另测。原最佳ZIP保持不变。冻结候选source、原 `AUDIT.json`、原 `MANIFEST.json`保留不动；后续证据及本报告新SHA单独记录于 `ACTUAL_FOLLOWUP.json`。
