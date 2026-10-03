# 存活保底研究：机制成立，尚无部署证据

2026-10-04 JST。先独立阅读正式实现，再读 ALGORITHM_PORTFOLIO_ZH.md、cold_pruning_ledger_audit.py、REQUEST_LEDGER_ZH.md 和 objective_graph_DESIGN_ZH.md。独立草稿见 survival_hedging_independent_20261004.md；本报告修正草稿中未舍入端点的绝对表述。

## 问题与结论

已有较高 best 后，低科学分曝光可以有正终局价值。科学 best、raw-factor completion 和每个 REQ 时间窗是独立 witness；未来回溯撤销时，较低 science witness 可保留 science、required、Jain 或请求奖励。现有 policy 已分别保留 science/factor/lower、全历史有效标志及请求证明；本研究不把这项已有正确实现作为新增策略。

公开 L1/L2 没有 data_loss，因此无新的存活保底价值。真正新增的模型是：用随机连续行动失效窗口对历史分数层 OR、completion OR、REQ quota 与 Jain 共同结算，并在任何改变曝光次数的分支上重新算全部历史风险。该模型已实现一个微审计，但没有部署行动排序或完整季节收益证据。

## 契约与先验范围

| 依据 | 能据此采用的事实 | 限制 |
|---|---|---|
| participant guide Appendix A | 特殊 data_loss / pointing_offset 仅 Hard 卡启用；data_loss 撤销连续 observe rank，wait/report不计，时间不退款，state_resync 重算，REQ可回撤 | 不能把所有隐藏卡视为Hard |
| initialize_payload 正式代码 | 公开site、catalog、score、night calendar、slot seconds、task_card metadata、limits | 没有承诺 stress flag、x、i/j、trigger、生成器seed/配置 |
| 官方参考 generator | 每次构造最多一条data_loss；after_earthquake/fixed_slot/fixed_date三种；i/j均匀拒绝宽度>x；x验证为(0,1]；六位小数写CSV；没有正的最小宽度 | 属于生成器族先验，并非公开初始化保证；不推断所有隐藏卡都来自同族配置 |
| 本地 L1/L2 scenario/card | stress=false、实际消息无resync | 不人为加synthetic loss来宣称这两卡收益 |
| 本地 L3/L4公开card与真实resync | 明确有loss，实际N740/[88,89)/x.045、N510/[206,233)/x.06 | x/i/j/N仅在事后resync可用；在pretrigger排序中禁止读它们 |

同一参考 runner 只触发一次；其触发点在已读生成器对应地震 actual_end 或固定点。数据损失之前的地震 coarse bulletin 本身不公开确切 end/未来触发。跨触发时刻的曝光先完成才冻结N。比赛未来更多失效规则需要重新建模。

## 概率与状态表示

在理想连续均匀RNG的已接受域 D={0<=i<=j<=1,j-i<=x}，面积 Z=x-x²/2。动作 a 失效 iff floor(iN)<=a<floor(jN)，等价 i<(a+1)/N 且 j>=(a+1)/N。集合A全失效只取最早/最晚rank u,v，因此面积积分给出p(A)。按目标贡献不同值 c1>...>cm，A_k={witness:c>=c_k}，则 Ebest=sum_k(c_k-c_{k+1})[1-p(A_k)]。

实际生成器先接受连续(i,j)，再各写六位小数。令M=10^6，a_min/a_max对应概率阈值是 U=(ceil((a_min+1)M/N)-.5)/M、V同式；对原接受域积分 i<U,j>=V。实现用整数ceil消除临界浮点误差。continuous版本中末动作永不失效；CSV版本中j可round成1，末动作仍有很小失效概率。N10,x.05例为5.1281794868e-7。原草稿的间隔>=x绝对存活也只属于未舍入版本；实际采用映射后再检验p(A)=0。该“精确”仅是指定理想连续RNG、参考拒绝分布、固定N/x的解析值；有限精度PRNG与未知隐藏卡先验没有被证明相同。

固定目标的科学分期望、required存活可按层求和。Jain和REQ k-of-n是共享窗口的联合函数，必须先逐共同窗口计算完整ledger结算再取期望。不能将目标边际存活概率独立相乘，亦不能把期望band ratios代入Jain。脚本用(i,j)接受域的多边形clip精确建立舍入floor cells，包括j=1的微小角区域，调用未修改官方BestLedger/scorer核验。

可以在固定已知请求与既定动作序列上按science层/completion阈值/REQ窗口保存极早与极晚witness，内部witness不会改变任何单连续窗口的全失效谓词。动作本身及rank不能删除；未来原始factor的推断区间、已公开请求证明需独立维护。若失效支持不是单连续窗口，极值压缩不成立。现有cold_pruning_ledger_audit仅在truth固定i/j、有限N族上比较survival签名；本模型覆盖未知随机i/j的分布，并显式包含全ledger的N变化。

## 真实公开历史小审计

源为READY native受限完整回放的actions/decisions/messages及score feedback。observations.csv先投影为(target,rank,score)，忽略factor/quality/prog_mult/fiber等离线列；最后observe若没有下一decision_request不计公开反馈。请求只在issued<=action start且完整曝光落窗时考虑。Hard prefix按实际resync时刻事后截出，只用于描述性机制审计，不能作为部署trigger先验。

| 卡 | 公开prefix observe数 | 较低science hit | 新全季factor安全证书 | 新REQ窗口首条安全达标witness |
|---|---:|---:|---:|---:|
| L1 | 981 | 163 | 0 | 5 |
| L2 | 1107 | 233 | 0 | 5 |
| L3（loss前） | 739 | 99 | 0 | 0 |
| L4（loss前） | 509 | 14 | 0 | 0 |

例如L1 rank926目标V4T003566的新science .318470<旧 .534552，raw-factor公开下界.589758仍为REQ2新窗口首个达标witness；季节已有.989910下界。这说明只用science best删重复会破坏请求，但这一机会已有请求策略覆盖。

对Hard公开score历史另施明确synthetic条件 x=.05,N=2*prefix（两卡一致，不读实际未来x/trigger），9/3条较低science witness有正保底删除边际。L3最大.020787，L4最大.013365，普通science量级很小；逐条删除边际不能直接相加作为行动价值。没有由此筛出一个合法的当前field/fiber替代及真实续局排序反转。

raw-factor真实列另外隔离为 offline_factor_teacher 审计，只核验已发生hit的独立factor改善，绝不进入public_history/动作打分。L1/L2/L3/L4较低science但提升真实rawfactor的hit为31/23/4/1；其中跨过.5阈值为0/3/0/0。故L2确实存在science maxima与completion maxima来自不同记录的真实反例，公开安全证书却未同步增强；这已有独立factor账本处理，未形成新的survival策略。数值见public_audit.json。

## 微验证与成本

五种窗口集合各100000个已接受共同场景与解析值一致到抽样误差，最大误差.001691。30个确切窗口cells全概率质量1.0000000000000002；官方shared science=1.9777777777777785，解析=1.9777777777777779；官方联合REQ期望88.888889，错误独立近似86.419753。所有science/required/REQ/Jain均调用完整官方ledger语义。

固定N10/x.2时，在rank4高science1后追加rank8低science.8，条件science边际+.088889；这只是固定N反例。新增空observe把另一ledger N2改N3则−.111111；首rankledger同样N2→N3则+.059259。新增计数的外部性有正有负，不能只算新的witness边际。真实续局还可在resync后重新观测补回，纯冻结ledger保底期望会高估这种可恢复损失。

最终微审计不到1秒本机CPU，Hard score-layer部分每卡约.01秒；无GPU、训练、SSH或完整季节重排。本轮没有CPU瓶颈，不能为占GPU而训练。重复审计、初版synthetic相关性示例的修订、命令路径错误及全部数值保存在结果目录manifest/failures。

## 预声明停止与下一阶段门槛

停止本轮完整replanning：L1/L2无loss；Hard事前x/trigger先验尚未由initialize识别；只有条件历史删除价值，没有当前合法动作排序差异，也没有未来恢复/时间机会成本。不得把这次micro胜零best增量简化基线称为强策略收益。

后续仅在有明确Hard卡契约/允许离线教师先验且public candidate真正变序后继续。保持完整field/16fibers/时间/持续曝光耦合，分别采样未来触发N、舍入窗口及公开反馈下的质量；未来分支必须在相同已到达消息上选择动作，resync到达后才能recourse。预先锁定参数与触发选择规则、共前缀、普通强native control、真实teacher replan、2CPU/2GiB/900秒及source SHA；先L3仅一个预选分叉，非正或不完整则停止，不用L4救参。随后至少隔卡完整门检才可能谈部署。
