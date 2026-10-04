# 日历边界 binding：强基线实现、公开证书与停止结论

2026-10-04。仅写本文件与 `results/cold_calendar_binding_implementation_20261004/`。先独立读官方 upstream 的 runner、scorer、fiber、workflow、calendar 与 participant guide，再读旧 `cold_calendar_boundary`、未完成 `calendar_binding_policy` 和 portfolio 查重。所有计算在 Rhodes1 的独立 `/tmp/gosim-cold-calendar-binding-20261004-impl/`、CPU 26/27 完成；没有操作他人进程、GPU、线上提交、L4、sealed teacher、真实天气产品或实际 factor/quality/fiber 值。原 29-file strong control 的每个字节与原路径重新比对一致。

**结论：固定夜前实现没有取得合格候选，停止该分支；真正末夜短尾已有两个当前强包的公开可证明机会，但没有裁决其真实天气增分。** L1 当前 fault-v1 的最后 `wait` 留 47 秒，L3 留 23 秒；本轮可生成合法 60 秒申报曝光，分别分配 2/4 个目标。利用公开生成器的质量上界，可证明这些新曝光不会改变 completion 位，因此科学 best 不降、required/Jain 不变、REQ 奖励不降、future loss rank 没有后效。两点的公开均值科学预测是 +0.0817888/+0.1005716，**实际已经证明的增量下界均为 0**。

## 1. 原强策略和旧 terminal wrapper 的差别

只从 `cold_persistent_fault_control_20261004/control_package/` 复制实际 29 个文件为 `package/base/`。原参数、CPU phase、REQ DP、exact cache、反馈、calibration 和 repair 代码均未修改。`control_source_lock.json` 与最终 manifest 记录逐文件 SHA。

原 `request_terminal_adaptation_20261004/terminal_report_agent.py` 缓存已选 terminal action，插入一次报告，再原字节释放该 action；原 action 可以是 observe/wait/finish。它没有把 `remaining<60` 的等待改为 observe。本轮新增的是这个 **wait→observe** 动作。两种功能可组合，`make_boundary_policy(base)` 用于原 RequestCache 派生 controller，terminal report guard 留在最外层，让其冻结、报告、释放同一个证书通过的尾曝。实际 fault-v1 + boundary + terminal-report 的完整组合尚未运行。

产物 ZIP 使用原 control29 基底，不含当前最好 fault-v1 的 controller，**不能直接替换 root 的已冻结强包**。其中：

- 早期纯 engine-contract 子域 ZIP：`binding_safe_tail_candidate.zip`，32 files，SHA `385e86031e67f0d731570b73f42b73d8285787cf41dffca4251805d376eca122`。
- 最终公开 official-generator-family 子域 ZIP：`binding_family_tail_candidate.zip`，33 files，SHA `377a5786b6baa72d60b5d9e8b8b2c5636ad4f965045158f2a027d6d3dac68eb6`。

第二个 ZIP 包含 `binding_model.py`、`binding_agent.py` 与版本化公开 `public_weather_envelope.json`。它保留 10 秒墙钟准入、搜索后 2 秒回复余量；正常强动作完成后只在原动作是直接到 survey_end 的短尾 wait 时搜索。没有预存未来结果或回放修改动作后的旧反馈。

## 2. 官方动作域与后效模型

runner 以内部 now 为曝光起点。申报 duration 必须为整数 `[60,3600]`；先裁到 survey_end，起点位于 slot 内时再裁到当夜末端。因此夜末 1–59 秒可以申报 60 秒并合法裁短。gap 起曝不触发该夜末裁剪；每个 gap 段的 weather truth 为 None，既不提供 photons，也稀释 q_band 的全曝光均值。起曝时一次 fiber 分类，随后 sidereal tracking；提前起曝确实提供新的天球网格方向。全程最低高度仍包含 gap；REQ witness 必须整次曝光位于 issued/deadline 窗内。

公开 history 中的 observe rank 是状态的一部分，不能只优化即时 science。未来 loss 在第一次到达 trigger 的 while 头冻结 N，再删除 `[floor(aN),floor(bN))`；额外 observe 即使无 hit，也可能改变被删除的高分旧动作及其 required、REQ、Jain 状态。一个从末夜内直接裁到 E 的曝光则设置 now=E 后退出 while，不产生新的 loss 处理。当前 snapshot 以前的 loss 已结算，末段途中尚未处理的 trigger 在原 terminal wait 与新 terminal observe 两分支都不会再处理。

状态模型据此显式包含公开分数账本、已知 resync、completion 不确定性、request 时窗、observe rank、公开几何、C/E prior 和未发布夜初信息。旧 calendar-binding 实现的 `science_delta−1 >=2` 门槛没有排除 rank/loss/Jain 反例，不能直接部署。

## 3. 两类完成位不变证书

**第一类只依赖 engine 合约。** 公开六位 score r、science weight w 和最大 program multiplier M 给出旧 factor 下界

`lower=max(0,r−0.500001e−6)/(w*M)`。

若 lower≥Jain threshold，目标已完成；再次曝光不会改变该目标的 Jain completion 位。PublicScoreLedger 在每个 last_result 收取真实公开 score，在 state_resync 后用公开 canonical best 重建。没有把估计 factor_lower 当硬证书。恰好 r=.600000、w=1、M=1.2 不足以证明 .5；r=.600001 可以。公开 resync 清空该目标时证书撤销。

**第二类明确限制为公开正式 v4 generator family。** 公开配置 clip 保证 seeing≥.50、transparency≤1、sky≤1.50、efficiency≤1；repair 后 efficiency 同样 min 到 1。公开 directional weather、earthquake、terrain、rocket 只有降质或关闭效应；lunar≤1。

不能直接用 `normalized_airmass≥1`：Kasten–Young 经验式在天顶附近有极小的下探。本轮改用解析保守界。记公开最低高度 hmin，`zmax=90−hmin`，`g0=1+.50572*96.07995^(−1.6364)`。因 `cos(z)≤1` 且经验修正项随 z 增大，

`X >= Xlo = g0 / [1+.50572*(96.07995−zmax)^(−1.6364)]`。

公开 30° / exponent .6 下，取天气 component ratio 3 后，raw quality 上界为 **3.002055939870124**，已包含浮点余量。对实际尾秒 τ，

`new_factor <= min(1, flux*τ*raw_quality_max/(q0*flux_zero_point*exposure_zero_point_seconds))`。

若此上界严格小于 min(Jain threshold, required threshold)，该目标的新曝光不能改变任何普通 completion 位，无论旧状态是否已经完成。因此可加入此前没有正分的低 flux 目标。这个证书没有推广到任意 engine 合法但超出生成器范围的天气；其假设、公开代码/config hash 均记录。REQ 成功奖励是非负的，新有效 witness 只能增加奖励。

在 terminal wait→observe 中，旧 ledger 不删除，新 best 逐目标单调，required/Jain 位保持，report 不变，request 奖励不降，且无 future rank/loss 后效。因此全项 delta≥0。未知 closure 或 offset 可令新收益为 0，不破坏该保证。它没有保证严格增分。

## 4. 当前 fault-v1 的纯公开末尾证据

`extract_public_terminal.py` 只白名单解释实际历史的 `observe_index,target_id,score` 三列；factor、quality、prog_mult、fiber 值没有解码为特征、输出或 actor input。有效性只由公开 state_resync 的 rank window 推导。公开 action/decisions 提供末动作和时间。没有载入 scenario truth；没有把反事实 hit/factor 伪装为实际反馈。

| 卡 | 原最后动作 / 起时 | 剩秒 | 新 assignment | 新 factor 公开上界 | 公开均值 science 预测 |
|---|---|---:|---|---|---:|
| L1 | wait / 2026-12-03T08:14:13Z，rank987 | 47 | fiber3→V4T004819；fiber4→V4T004144 | .359458174；.478588234 | .081788794 |
| L3 | wait / 2026-12-22T08:14:37Z，rank1050 | 23 | fiber0→V4T002772；fiber5→V4T000781；fiber6→V4T006956；fiber7→V4T006606 | .056324505；.226122934；.492933534；.100761172 | .100571553 |
| L2 | 末动作为 observe | — | 无转换 | — | — |

L1 新指向 `(68.0381059,314.6549725)`；L3 为 `(81.6566479,287.1132646)`；均申报 60 秒、DARK。官方 workflow envelope 与 normalize 验证通过；零 offset 的官方 nominal fiber 分类与全程高度验证也全部通过。真实 offset 未用于候选或评分。即使未命中，证书仍保证不扣旧分。

候选用原公共 seasonal C/E 均值，没有重建 fault-v1 的终局 latent belief。这不是声称当前 wrapper 用原 fault state 一定选择同一个指向，也不是实际增分测量。`current_terminal_summary.json` 保存全部动作、证书、nominal geometry 与公开 provenance。两点搜索和初始化总计约 1.05 秒，峰 RSS 66,764 KiB。

旧 L1/L2/L3 public-prefix 也按“首个 tail / 首个 gap”固定选择核验：L1 940 步有 8 个短尾 wait，L2 1194 步有 16 个，L3 的 65 步前缀无短尾。首尾分别是 1 秒 / 59 秒，均非 terminal，证书拒绝。其 mean proposals 为 .028616/1.111309，不能当实际 gain。没有据这些点扩大时间/lead 池。

## 5. 冻结夜前实现与正常 strong 独立世界

`normal_worlds.py` 在读取结果以前冻结 seeds **912101–912108**、第二夜 lead2700/effective900、24 个 target anchor 和严格正的预测 science delta 门槛。每个世界使用原 L1 **全部 7800 targets** 与原 strong 参数，三夜各 900 秒。背景 weather 由官方 `v4_weather_simulator.generate_weather` 独立生成；future loss 使用预声明的 .4–.6 窗 / max .2 合成压力，后四 seed 再加入夜初发布、夜末截止的固定公开几何 request。这是有限合成 horizon，加正式 generator background，**不是实际完整卡或正式随机分布的均分估计**。

研究分支在 gap 提前到 a−2700；pre proposal 与同 effective900 的 inside search 比较，同时保留一个独立 deep-copy 原 strong 的未来首次动作作为 forecast 比较。copy 中不加入未发布消息。两分支之后各自收 runner 的真实公开反馈，继续原 strong 正常重新规划，完整结算 science、required、REQ、Jain、reports、loss；没有使用旧未来 tape。

八组 pre−reference forecast science delta 依次为 **−2.027071、−2.274091、−1.774728、−1.575533、−1.758898、−2.257590、−2.325217、−2.275219**。全部未达门槛。相应 observe counts 为 **23/23/19/20/21/23/16/17**，两分支完全一致；所有 observe/report 动作、公开 score feedback 与全部终局分项差都是 0。实际完整核验 16 条有限 world，154.47 秒；taskset 2 CPU、地址空间上限 2 GiB、每 actor 900 秒，driver 也有 900 秒停止限制；峰 RSS 107,960 KiB。

这个结果不提供任何获准的 pre-night 策略，也不否定更广的方向绑定域。gate 只比较 science，一旦产生候选，还需要考虑 inside 多动作机会成本、未发布 REQ/公告和 rank 风险。本轮没有成功采用点，因此不扩大 lead/duration/anchor、调阈值、救参或再跑同池。

## 6. 正负短官方实验与失败

最终 33 次短 loop 保留完整 decisions、observations、messages、score_report、snapshots/certificates。只替换 Scenario loader 为 validate 通过的内存 fixture，其余官方逻辑未修改。

| 实验 | 全项 delta | 说明 |
|---|---:|---|
| 旧方向 pair 复核 | +.750480 | 旧合成证据复核，不宣称新实际卡收益 |
| 夜初未知 REQ | −100.140000 | pre witness 在 issued 前，漏 100 奖励 |
| DARK q_band padding | −.200000 | 同 photons、program 匹配变差 |
| 已完成目标 terminal tail | +.554013 | engine-contract completion 不变 |
| 新 low-flux terminal tail | +.021893 | official-family 上界下不跨 completion |
| naive Jain tail | −18.800000 | science +1.2、Jain −20 |
| certificate 拒绝该 Jain 动作 | 0 | 完整对照保持原 wait |
| 额外非terminal空 observe | −201.200000 | N改变，loss删高分旧动作并改变Jain |
| 原 strong 正常反馈的三目标 tail integration | +.018244 | 首动作完全相同，末 wait 改合法 observe；adopted=1 |

另八个独立 background seed 的两目标同中心 pair pre delta 是 +201.557477 至 +202.12，其中大部为单 RA band 的 Jain 从全空到非空改善。其 inside 同中心可能完全漏 hit，**不是强 inside 排程基线**，仅用于确认 geometry/完整结算路径；没有拿这些数字批准 pre deployment。

第一轮 normal world 因原 PlannerBudgetFacade 的 `__getattr__` 导致 deepcopy 在构造未初始化 wrapper 时递归。`FAILED_NORMAL_DEEPCOPY/` 保存完整源、log、已完成 control 与失败分支痕迹。只修 copy memo 的 facade 预注册；八 seeds、gate、strong 参数均不变。`NORMAL_REPAIRED_SOURCE/` 保存实际成功批次的完整源。最初二目标 terminal integration 两分支均无正预测候选，保存于 `INTEGRATED_INITIAL_NO_CANDIDATE/`；随后用同 cell 两个不同 faint target 的三目标 fixture 验证真实 adoption 路径，不将先前 0 差改写成成功。早期 X≥1 草案已撤销，`FAMILY_ENVELOPE_REJECTED_X_GE1.json` 记录理由与解析修正。

## 7. 具体下一步

停止本轮固定 pre-night 实现。保留两个 tail 机会，优先把 `make_boundary_policy(current_fault_base)` 放在 **原 fault-v1 controller 上**，原 terminal-report guard 留最外层；保留现在公开 family 上界与 reserve，不改 strong chooser/参数。先用当前 L1/L3 的真实公开终局 actor 状态做一次协议组合核验，检查 report cache 原字节释放、rank/E、公开 factor 证书和墙钟。若公开源和 controller 状态可恢复，则只在该 terminal 分支调用官方 scorer 裁决真实新增动作，禁止向 actor 传隐藏天气；不需要复算原完整 control/global bound。候选真实 gain 可能为 0，预算收益规模也很小，应优先保留 root 当前已验证的大收益强包。

复现：在 Rhodes1 目录运行 `audit.py`、`NORMAL_REPAIRED_SOURCE/normal_worlds.py`、`public_prefix_probe.py`、`current_terminal_probe.py`。原接口/score 函数未改；官方核心 hash 与 upstream 五文件逐项一致。`MANIFEST.json`、`FINAL_FAMILY_SOURCE_LOCK.json`、`PRECOMPUTE_SOURCE_LOCK.json`、`REPAIR_SOURCE_LOCK.json` 保存 source、公开输入、全部输出及失败 hash。沒有线上提交，也没有修改任何原冻结 source 或 root package。
