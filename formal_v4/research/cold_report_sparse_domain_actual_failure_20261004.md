# Sparse report 实际失败：公开因果诊断与下一算法合同

本轮只读冻结 source/NN/DP/test/package，诊断文件在 `results/cold_report_sparse_domain_20261004/actual_failure_diagnosis_20261004/`。没有读取私有 fault onset/date、L4 sealed/teacher；没有重新读取旧 test 作选择，没有修改原候选、阈值或生成 prior，也没有启动新 full 或新训练。原生产实现拒绝部署。

## 实际结果与额度链

根任务已完成正常 2CPU/2GB/900s 实际强闭环：新 report 对 faultv1 的 L1/L2/L3 差为 **+88.780156 / 0 / −411.623630**，均值 **−107.614491**。L4 不开启救参。

| 卡 | 已发生的公开 report | 结果 | 作用 |
|---|---|---|---|
| L1 | rank857，p=.443669，delta=.949157，q2 | correct | 真实提前修复；science +88.710132、Jain +.070025，其余同 v1 |
| L2 | terminal rank1087，p=.005961，delta=.508274，q2 | false | 终端免费信息尝试，结算各项同 v1 |
| L3 | rank767，p=.826689，delta=3.915853，q2 | false | q2→q1，已经使 v1 reserve1 门禁不允许额外 report |
| L3 | rank769，p=.658897，delta=2.105466，q1 | false | q1→q0，NN free-only 和原 strong free-report 都不能再诊断 |

上述 rank 是结果审计位置，不是未来触发规则。时间戳只在原公开证据中留存，本报告没有把实际日期转为算法条件。

L3 NN 查询713次、合计 .144s；不是 NN 耗尽900秒预算。只投影已发生的公共动作/反馈得到以下更强的因果证据：

1. 新 L3 去掉两次 report 后，**全部1169个 science/wait动作与原 control 逐字典相同**。
2. 原 faultv1 到其第一次正确 report 之前的1119个动作，也与 control 相同。
3. 在新 L3 已发生的公开历史上重建原 v1 evidence，第一处 `qualified=True` 但 free quota 不合格的位置正是 **rank961**。对应原 v1 在相同公开动作前缀/时钟的 report 有已发生的公开 correct ack。没有用私有 onset 推断此事。
4. 原 v1 要求 `free > free_quota_reserve=1`。所以第一条 NN false 已经剥夺了后续 v1 机会；不能把失败只归因于第二条 report 太快。

机制链是：NN 错误触发 → 改变真实共享额度 → 禁止原强诊断 controller → 没有 repair → 科学动作完整回到 no-repair control。先调用 `super().propose(v1)` 只能保护**当前**已满足的 v1 决策，保护不了其未来额度。

## 明确错误一：Bellman 允许 actor 禁止的 q0 动作

冻结 `report_core.build_dp` 对 q0 仍计算 paid-report R 并令 `V0=max(W0,R0)`；但生产 `SparseReportGuard.propose` 在 `free<=0` 时直接返回普通 science action，固定 evaluation 的 `dp_free` 也禁止 q0 report。未来动作集合不一致，先前 exhaustive tree 核对的是一般 paid-report 模型，没有核对 **部署 free-only** 的动作集合。这是模型实现错误。

同一冻结表在公开 rank961 的 q0/p≈.880857 状态仍给 `report_minus_wait=+112.083`。真正 actor 因 q0 根本不查询/执行它，不能获得 Bellman 预期的付费自救。

一个两步微例即可显示影子价失真：下一步有确定 fault，正确 report +100，并恢复400 science。若 paid report 可用，q0 的确定正确 report也不罚150，因此 q1−q0 的价值为0；若 actor 固定 free-only，q0不能report，最后一次 free 的价值为500。不能把 paid-policy 的额度价用于 free-only actor。

### 独立诊断修复合同

只在诊断目录生成 `diagnostic_free_only_dp.npz`，保持 NN、calibration、生成 prior、K/L 和原 package不变：

- q0：`V0=W0`，report illegal，delta设为不可执行。
- q1/q2：保留同一个 wait/correct/false kernel；true→q2，false→q−1；当前 p0 的已知健康等待和研究 count2 健康吸收保留。
- 全部414,720个 state×horizon×quota 验证动作可执行性与 Bellman重算，误差0；126个两 epoch 小树穷举误差7.1e-15。
- 原 DP SHA `4acb1ddffe391c0e0e16dbda24207c3b9e22a60961701ba6f2b05130d0ea7d25`；诊断 constrained DP SHA `77860d6a33b03cca2f6b5d714ad46f86cfddbe64a2e2f8c20d8da12573de4a69`。

只用已声明 cal/val 做诊断，未读取 test：

| 旧固定历史上的平均额度影子价 | 原 paid continuation | 严格 free continuation |
|---|---:|---:|
| cal q1−q0 | 24.635 | 195.921 |
| val q1−q0 | 24.819 | 206.721 |
| cal q2−q1 | 7.477 | 26.010 |
| val q2−q1 | 7.413 | 27.140 |

同样固定设计上的 cal/val score 分别从5382.178/5536.063变为5374.220/5502.429，即 −7.957/−33.634。修正语义不自动使策略更好；这里没有据得分选择部署版本，也没有解除拒绝。

## 明确错误二：wait 的基准是固定动作 NN DP，不是原 v1 controller

训练 `trajectory` 采用固定公开 science动作，随机 .012 report；配对 `xwait/xreport` 只跟随下一次固定曝光，没有生产 v1 evidence/controller、quota reserve、原 strong repair witness、修复后的全局 replan。DP state只有 p-bin、quake-age-bin、correct-count；缺少 v1 最近8slots的证明进度和未来何时会报修。

所以旧 `R-W` 是这个固定设计、coarse NN-report 模型的 advantage。实际 wrapper 的等待动作却意味着**继续运行 strong+v1**。两者不是同一个 `W`。单纯保留 prior/source 和扩大 geometry support 不能修复这一点。

v1 的 q2→q1 是一个 controller 门禁跳变：额外诊断由允许变成禁止；其影子价不能从“q1还能由未来 NN诊断、甚至q0还能付费自救”的 value table 借用。当前 v1 `qualified=False` 也不说明未来机会没有价值。

## 独立概率证据：false 后的健康起点没有充分保留

正式 false report 在该 timestamp 给出 F=0。下一次 F=1 只能来自新的 fault onset。后续 posterior 可以变大，但应通过 **健康起点后的 hazard 与新 score innovations** 更新，不能让 report之前的 low-E history直接重新成为同一个可修 fault 的证据。

公开第二次 L3 尝试距离第一次有2个 observing slots，8个 likelihood tokens里6个仍是第一次 report前的原 token。冻结 NN只在同 timestamp强制p0；之后又是独立 MLP映射，没有持续 Bayes state来承接“这些旧异常已经被false归入weather/quake nuisance”的联合条件。

将第二次 feature 的 last-report scalars清为未报告，仅作只读 ablation，p从.658897变为.604034。这个结果不能单独证明违反Bayes（到达时间先验及新观测也可能改变posterior），但表明此网络的 negative-feedback scalars并未提供可靠的持续排除机制。

按已声明训练 count0/1/2权重 .25/.50/.25、官方 nominal+jitter−200..200先验，使用 **公开 L3 的1091 slots** 和当前false时的“零次correct且F0”条件，2slots中新首次fault的先验为 .007229。要升到p=.658897，需要新证据 LR约265。此数只解释原生成先验下的 innovation价；不是正式世界上界，不能把统计先验当协议限制，也没有读取实际 onset。

### 原 cal 已有局部过度自信

重看 frozen train/cal（不看 test、不改模型）的预先公开条件组：last report false 且quake公告年龄1–4nights。

- cal723条、6world：实际active率 .041494，平均预测 .117765。
- 其中 p>=.65 的33条来自3world，**仅1条active**，而预测至少应有 .65 的活动概率。记录有跨曝相关，不能当33个独立试验计算显著性；它仍是具体的局部校准失败。
- 更接近第二次实际尝试的“false后≤17.3h、quake前4night、phase3、correct_count0”组：train96条仅7world、active0；cal21条仅1world。网络没有在该联合域完成可信的校准。

大于900条 geometry/history 可查询记录只是接口支持量，不是更多独立world，也不能证明 production observation process同分布。训练物理方向/slot积分正确，仍会有如下统计差别：固定 L1/L2 动作没有随新weather和repair replan；随机 report采样与生产按 posterior/guard选择的report不同；forecast仅部分压缩；quake magnitude/nuisance未显式持续表示；source的绝对slot jitter与public survey长度在feature中不能完整还原；resync只清hist，训练没有data-loss过程。

## 下一算法：对当前基准的增量价值，而非重调原阈值

值得做一个独立研究，但不能复用这个 posterior当已校准概率、不能只改free quota阈值，也不能把上述实际日期或rank变成触发条件。默认继续已验证 faultv1，根任务决定是否启动新研究。

### 1. 表示健康约束后的联合 belief

建议 belief维护 fault active/repair状态及future arrival mass、背景C/efficiency、quake shock magnitude/age和方向weather nuisance。false时条件化到F0，同时保留旧低分对quake/background的解释；true时移除该fault multiplier而保留quake；之后先按公开 **observing clock和calendar/config** 做hazard prediction，再仅用新的正式score做likelihood update。普通NN可拟合public score likelihood/Bayes factor或belief更新近似，不宜再直接以滚动8history输出无约束绝对p。

每次未知第三fault仍作为正式支持域外或新域的概率混合，不能用训练max2断言不存在。quake/fault共存、directional loss、全zero、饱和和false后的健康锚点必须成为world-level calibration组，而非事后在卡日期上调值。

### 2. 正确 controller-conditioned advantage

令 B是已经冻结的 strong+v1，z是其 **公开 controller state**（最近8slots证据/时间、night/sector覆盖、negative level/cooldown、repair witness、ledger、public quota、必要时runtime支持），b是新联合belief。

一次插入后承诺继续B的最小可复核目标：

`A_B(b,z,q) = p[100 + E V_B(b_correct,z_correct,2)] + (1-p)[-c_q + E V_B(b_false,z_false,q-1)] - V_B(b,z,q)`。

future必须共享同world/weather；correct分支先repair再replan；false分支保留明确的健康条件并执行真实quota变化。`V_B` 必须运行B实际允许的动作，q0不存在假想paid自救。若B现在已经report，直接执行B；其余state比较这个增量。

当B迟早会正确报告同一个当前fault时，早报的+100基本相消，主要收益是B诊断延迟前的科学机会回收。false损失则至少包含 `lambda_B(b_false,z,q)=V_B(q)-V_B(q-1)`。近似 threshold应来自 `p·delay_recovery > (1-p)·lambda_B`（再加入合法信息/重置额度项），不是固定p>.9。

lambda_B(q2)需要反映v1 reserve门禁，不能只看当前qualified bool。小DP若保留，可加controller诊断lead-time/证据进度，而不是把这些状态继续pool到同一个p/quake bin。完整z很大时，普通NN critic可以在独立world中拟合B continuation或成对advantage，并用world级误差审计其条件支持。

### 3. 下一数据合同与成本

下一trial需新独立seed/config/policy lock，包含B产生的公开history与B选择的report，特别覆盖false锚点后的quake、q2/q1门禁和真正的方向/field replan。训练label可用host sameworld分支，但actor只看public；不得使用这三卡私有fault日期或L4。

可以先做小型独立world上的controller-only固定物理动作 pilot核对quota/value门禁，再做少量真正B replan分支估计CPU成本；两者要分开声明。真实B continuation比本轮固定动作36秒生成昂贵，不能无估算直接开64×900s。root批准新域后，再用PRO6000实际普通NN拟合；本轮没有开始这些工作。

多次插入若需要policy iteration，应让future controller就是将部署的同一个free-only混合policy；一次插入后只跟B的critic不能宣称多次复用自动安全。source gates除quota/count/repair外，还应逐state核对未来动作集合可执行，并测试完整false→next-observe→未来controller链，而非只核对一次false释放的当前action不变。

## 可复核工件

诊断目录包含 `public_causal_diagnosis.json`（公共轨迹/v1门禁和动作parity）、`actual_public_features.npz`（少量公开feature）、`training_conditional_support.json`、`free_only_contract_checks.json`、`diagnostic_free_only_dp.npz`、`cal_val_free_diagnostic.json` 与对应只读scripts/logs。`DIAGNOSIS_RECEIPT.json` 核对原SOURCE_LOCK全部hash不变。

本轮结论是完整失败诊断与数学合同，不是新的生产候选。q0修复、统计校准、基准controller价值三项必须分开解决；孤立第一项不能解除部署拒绝。
