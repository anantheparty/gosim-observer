# 非先知跨三夜共同策略续局：独立微实验与作用域

本轮没有得到新部署策略。固定 M=3、K=3 的初始节点选择器仍选原强 B；四个独立评测世界与 B 的完整三夜总分、动作和官方输出 hash 全部相同，均分差为 0。一次选择的完整成本约 **38.094 CPU 秒**。停止该具体小族，不扩 top K、粒子、天气或请求 seed，不开 900 秒正式完整季节。

研究源和所有输出位于 `results/cold_horizon_opportunity_policy_20261004/`。未读取 L4、封存教师或凭据，未占 PRO6000/Rhodes、未提交平台、未改原强 source。

## 正式合同与本轮真正不同的机制

先独立阅读正式 `v4_scorer.py`、`v4_runner.py`、`v4_workflow.py`、`v4_fiber_map.py`，再阅读研究 portfolio 去重。科学目标结算为有效曝光中的最高贡献，raw completion max 与 science max 分账；一次曝光共享时间和 16 个 fiber。命中只在曝光起点判定，随后天球跟踪；天气积分、Moon/airmass、program band 随曝光时间演化。未来 weather/fault/request 等实际路径不能由 actor 读取。

既有 `horizon_contention` 是末夜固定 600 秒 beam、冻结 belief；`common_exposure_control` 是条件冻结天气下的共同曝光 path + target/fiber matching MILP。本轮没有重跑这两条。新的对象是 **同一个公开反馈策略 B 的路径内真实重新决策**：

`Q_B(s,a) = E_prior [ F( a; subsequently execute B on delivered public history ) ]`。

所有粒子共用同一个首动作 a。每个粒子的后续动作都由同一冻结 B 的 history→action 程序生成；只有该粒子当时已交付的公告、请求和 score feedback 可以改变后续动作。不在每个粒子里先选择最优首动作再取平均，不给 B 未来 truth。各候选终局先做官方 cap/program/best/required/Jain/REQ/report 结算，再求均值。

一般滚动版本需要复制当前公开 ledger、belief、pending、fault quota 和请求状态，并从与当前公开 history 条件一致的独立路径分布续局。**此次实现只支持零历史的公开初始节点**；未来执行 B，选择器只调用一次。它是可执行首动作控制接口，尚未实现任意中季 state 的条件粒子更新或一般滚动部署，不应称为生产 horizon controller。

## 先验世界与评测世界的分离

官方生成器生成相同公开 catalog/calendar 的三个新 prior 世界：77101/77102/77103；评测世界为不同 seed 89101/89102/89103/89104。固定 catalog seed 20261004731。目录 192 targets、240 平方度、3 夜，weather 为官方背景夜/slot 随机过程及 closures，每个世界另有一个隐藏 instrument fault 和一个隐藏 REQ。

为了让初始公开信息可精确匹配，天气方向事件、terrain、quake、rocket 和 stress 在该微域关闭；未来质量和故障仍未知。REQ 生成使用每个世界自己的独立 seed，避免相同 catalog seed 意外共享确切隐藏请求轨迹。原 req/required/faultv1/controller 全部保持：原 fault ZIP 的 38 成员逐字相同；没有移除或改写其阈值控制。

选择器的参数只有 public initial payload、当前 public snapshot。它显式调用 `worlds/prior/`，从未得到评测 root、seed、truth、offset 或未来 label。真实评测世界由外层 V4Workflow 持有，仅按正式 participant 消息给 actor。全部 7 个世界的 public initialize hash 和首个 canonical public history hash 一致。

这是同 Python 进程中的输入语义边界，**尚未进行仅挂载 sanitized files 的 actor 容器隔离门检**。不能把本轮语义审查写成正式 sandbox 通过。

## 冻结菜单与合同检查

在生成世界和排名前预声明 K=3、M=3、4 个评测世界；修正接口格式后、最终排名前再锁 source。候选为：

1. 原 B 动作：DARK、398 秒、5 assignments，pointing `(88.4787369, 235.4390649)`。
2. 已经由原 B 当次生成的候选中，按原即时 utility 排序取第一个与 B 的 assignment Jaccard < .5 的 field：DARK、398 秒、4 assignments，pointing `(89.3527744, 48.6969926)`。
3. `wait 900`，随后 B 重新规划。

没有扩大原候选 field pool，候选 1/2 同时长。**different field 提案仍来自即时排名，没有用未来稀缺窗口构造**；两条曝光都近天顶、共享部分目标。lookahead 使用新时间状态，但候选 proposal 的广度很弱。

7 项初合同全部通过：原 source 成员不变；初始公开消息相同；时长合法；候选 0 的动作、官方 CSV SHA 和组件逐项复现 B。候选 0 保留原 pending/prediction 对象，不能重建一个“近似相同”的反馈输入。

最终四对另有 20 项门检全部通过：四对完整结束、逐动作相同、官方输出 hash 相同、全部组件相同、每次使用相同冻结 prior bank。source SHA 为 `9ba99f27c9316a87db50fe47dbd4326f5bec475751b461ddb7ccb885d8602663`。

## Prior 续局的全部正负结果

| 先验 seed | B total | different field total | wait total | field−B | wait−B |
|---|---:|---:|---:|---:|---:|
| 77101 | 260.750359 | 248.399744 | 266.701218 | −12.350615 | +5.950859 |
| 77102 | 371.061615 | 370.475125 | 257.822368 | −.586490 | −113.239247 |
| 77103 | 288.463422 | 285.761793 | 288.093684 | −2.701629 | −.369738 |
| mean | 306.758465333 | 301.545554 | 270.872423333 | −5.212911333 | −35.886042 |

三个 prior 的 field 差全部为负，主要 science 差为 −12.610414/−.287209/−2.029735，其余为 Jain。wait 的 science 差为 +4.807643/−7.654237/−.422255；77102 另有 report −100、Jain −5.585010。required/REQ 差均为 0，三世界均无 invalidation。不能把“等待得到一次正 science”解释成普遍质量窗口收益；它还改变了故障证据和报告结果。

三菜单没有 exact tie；最终均选 B。后续曝光数随强制菜单变化：B 为 66/73/80，field 为 70/72/82，wait 为 77/65/81，说明这里确实执行了重新规划，没有固定 suffix tape。

## 四个独立评测世界

| seed | B = H total | science | required | Jain penalty | REQ | report | B CPU 秒 | H CPU 秒 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 89101 | 300.424230 | 200.431988 | 0 | −.007759 | 100 | 0 | 3.903499 | 41.803664 |
| 89102 | 283.228195 | 191.240331 | 0 | −8.012136 | 100 | 0 | 3.441686 | 41.479899 |
| 89103 | 257.540850 | 163.639869 | 0 | −6.099019 | 100 | 0 | 3.431885 | 41.662031 |
| 89104 | 390.717810 | 191.063334 | 0 | −.345524 | 100 | 100 | 4.670952 | 42.727689 |

H 的每个 selector 都重新运行 9 条 prior 续局，未免费复用前次选点。8/8 `survey_complete`，逐组件差全为 0，invalidated observations 均为 0。动作/observations/messages/score hashes 均相同；运行成本的差本身不能称得分收益。

## 完整成本与预算含义

四个在线 chooser CPU 秒为 37.786937/38.049647/38.213362/38.059042，mean **38.027247**。该计时包括 current menu 生成、initial state deepcopy、9 个 B 初始化、所有未来 replan、官方模拟与结算、输出文件 I/O，只有已缓存 prior 文件生成没有放进原 chooser timer。

另实际重生成相同 3 个 prior 世界，包含 catalog/geometry/calendar/weather/fault/request 和 I/O，warm import 后为 .066551 CPU/.067220 wall 秒。每次调用应加此成本，得到 **38.093798 CPU 秒/selector**。初始零 ledger/belief 的完整初始化已计入；尚没有中季大 ledger clone 成本测量。

整个 8-run pilot 用时 183.121305 CPU 秒；其他合同、probe、失败和生成工作单独保留，不混入收益。Mac Python3.10.12/NumPy2.0.2，线程环境为 1；pilot RSS 最大值 100909056 bytes（约96.235 MiB），一次 owned process 样本 CPU99.6%、RSS97328KiB。它不是受限 Linux 2CPU/2GiB 实测。三夜 120 秒 workflow 均完整，只说明这个小域未超时。

即使只按基准 prior 的 66 个曝光，每曝光调用也需约 **2514.191 CPU 秒**，已经超过整个正式 900 秒上限；真实本地 L1/L2 是7800/8600 targets，正式大目录约2.5万，不能从192-target成本宣称可部署。低频公共战略节点、缓存或离线学习可能降低成本，但需要新的独立合同和验证，本轮没有实现或启动。

## 公开几何稀缺性审查与解析反例

`public_scarcity_audit.py` 只读取 L1/L2 的 public targets/calendar 和公开 site/instrument/score config；未使用 Scenario truth loader。按900秒起点网格，分别检查完整900/3600秒曝光在当前及随后两夜是否始终高于最低高度。选择初始、第8、第18和末三夜；661个 scalar 对照与官方 minimum-altitude 最大误差1.019e−7度，数值检查不是区间证明。

**pilot 的192个目标在三夜均有900秒和3600秒几何服务机会，纯“只有今夜可见”目标为零。** L1/L2 四个公开窗口也全部如此：每个目标均在三夜有至少一个合法长曝光起点。最长曝光的三夜可选起点数仍不同：pilot最少33、median71；L1窗口最少25/27/36/29，L2最少27/33/37/21。该结果是离散几何 supply，既没有质量保证，也没有共同 field/fiber/time 容量或当前 best ledger，不能把这些目标数当成可全部同时服务的容量。

因此，单看“可见几夜”的预约很难在这批公开目录产生排序变化。真正可能稀缺的是高 H（Moon/airmass）且未知 weather 良好时段里的 **共同 field/fiber 可服务价值容量**。将每个目标的未来最佳时刻独立领取，会重复领取同一时段/field/fiber；只计算当前被指派目标的未来损失，也遗漏了未指派目标的替换链。这些结构仍需要公共 residual-best score layers 与未来兼容图，不等同于放大即时 topK。

两个解析 toy 使用官方 BestLedger 的 best-only 结算，限定抽象有限完整曝光列，没有宣称已嵌入实际16-fiber几何：

- 当前只能选一个 field；A贡献5且只有当前可服务，B贡献6且当前/下槽都可服务。greedy B→B 得6，A→B 得11。它证明稀缺窗口信息可以反转即时 rate；本 pilot 没有把这类动作放进菜单。
- 两条等概率 future path：下一槽 X只有A，Y只有B。共同首动作 A 的期望为8，B为8.5；错误地每 path先挑首动作再平均给11。这个2.5差就是提前读未来的虚假价值。当前 implementation 的共享首动作方法避开此错误。

下一条提案若继续，应先从公开 calendar、天文积分与共同 fiber 兼容图推导未来 residual value demand 和 supply pressure，再提出当前低 rate 但释放未来竞争容量的动作；不能据本轮四个评测 world 的真收益选新菜单。已有共同曝光 MILP 的设计仍需去重，不能借“Hall pressure/图容量”名字重跑它。本轮只给出了上述审查与反例，没有启动新的策略 rollout。

## 失败保留与结论边界

初版请求设置用了非官方 `minimum_completed`，生成失败；修为等价 `minimum_completion_fraction=2/3`。官方总分键误记为 `total_score`，在 baseline measure 后、排名前修为 `total`。初始 public budget int/float hash 不同造成无动作失败，修正数值类型。发现候选0重建 pending 风险后主动中止未完 chooser，保留全部 partial 输出，改为逐字保留原对象并完成 B parity。公开稀缺审查曾错误假设当地38夜，L1实际32/L2实际36，空网格失败已保留，修为读取各卡最后三夜。没有用失败或 eval 标签更换统计参数。

该具体 selector 是 **无收益且费用过高的初始小域策略**。它验证了非先知共同首动作、反馈依赖续局、正式结算及基准可复现；没有充分测试稀缺质量窗口/大目录纤维竞争，也没有否定跨时间方法族。无需正式 full run，不生成候选 ZIP，不作生产采用。
