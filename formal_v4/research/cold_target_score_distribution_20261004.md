# 直接 target factor × physical band 分布：阶段 1 合同与阶段 2 实现锁

2026-10-04。独立先读官方 examples 的 scorer、runner、fiber 与 workflow，后读算法组合表去重。阶段1完成数学、四个新官方生成 world、小 runner、公开特征与未拟合模型成本。Root 已明确授权阶段2 implementation 与 fresh source/机械 gate 通过后的 PRO6000 实际拟合；当前 source/机械 gate 正在最终冻结，**尚未训练、未开900秒完整季节、未线上操作、未改最强冻结包。**

结果目录：`formal_v4/results/cold_target_score_distribution_20261004/`。静态官方 source 使用已核对的公开 e01939d0，四个实际运行模块与 examples 逐字相同，见 `OFFICIAL_SOURCE_RECEIPT.json`。未读旧 cal/test 数据、旧 factor/quality/offset、L4 truth 或 sealed teacher。只读了旧 bank 支持审查文字来识别表示问题。

## 1. 预测对象与几何选择

官方 band `b` 由目标自己的站点天气 × Moon × airmass 积分决定，既不乘设备效率，也不乘方向事件。physical factor `F` 则经过设备效率、方向事件/遮挡、持续时间、flux 和 cap；`F∈[0,1]`。数据损失影响有效 best ledger，保留过去发生的物理测量。

完整一次 action 的有效 factor 是 `g'=I_hit × F`；若全程 minimum altitude 不合格，外层也不准入。pilot 的 `g` 原名实际指此 `g'`，现已在标签中分列 `physical_factor_F` 与 `effective_factor_I_hit_times_F`。563 个 miss 中 455 个在反事实 hit 条件下有正 physical factor，因此不能把 miss 当天气关闭。

**下一训练选择仅学 `(F,b)`，固定原强几何在外层处理 hit、原 pointing calibration、glass margin 与 minimum-altitude。** Future NN 输入不含真实 offset 或实际未来 hit，也不学习 hit 概率。原强公开 calibration 与准入谓词原样保留；这个选择没有使原有几何不确定性消失。后文的精确期望公式针对已准入并按 hit 条件评分的 physical contribution；只有外层 hit 已确定时才是完整 action 的精确科学期望。若需对未知 hit 建模，应直接预测 `(I_hit F,b)` 或积分 joint hit/weather，不能擅自乘一个独立 hit 概率。

pilot 的 effective `g'` 公式仍成立，因为 `w g' m_p(b)` 就是当次目标的科学 contribution。下一训练不把这套 effective 标签冒充 physical F 标签。

## 2. 同一分布内的 nonlinear 结算

令公开有效 best 为 `B_i`，program p 在 band b 下倍率为 `m_p(b)`。对目标 i、候选曝光 e：

`G_i(e,p,B_i)=E[(w_i F_i(e) m_p(b_i(e))−B_i)_+ | public_history, public_query]`。

先计算每个 target 的期望 `G_i`，再在同 fiber 的准入 target 中取最大或做原配额指派。不能用 `max(0,E[score]−B)`；不能先在每个真值 world 中选同 fiber 最佳 target 再平均。后者授予 actor 尚未公开的信息。

无需假设不同 target 独立：对已固定的合法 assignment A，`E[sum_{i∈A} gain_i]=sum_{i∈A} E[gain_i]` 来自期望线性。天气共享、方向覆盖相关或 fault 同时影响全部 target，都不改变这个 additive science 等式。Jain 是终局覆盖比例的非线性函数，REQ k-of-n 是联合完成 gate，均不能由此声称精确。本候选保持原 required/REQ/Jain 代理项、quota eligibility、fault/controller；不把 histogram threshold mass 放进 REQ 或 Jain。

当 B=0，令 `μ_b=E[F 1_band=b]`，`μ=sum_b μ_b=E[F]`，则

`G_i(p,0)=w_i sum_b m_p(b) μ_b`。

三 band 矩非负，sum≤1，表达首次 science contribution 精确。公共 mismatch=1 时也可写成 `w_i [μ+(m_p(p)−1) μ_p]`。预测单个 μ 再独立乘 band 概率会丢失相关性；合成例中正确值 .6，而独立化给 .55。

采用 **单一 195 输出 joint head**（3 band × 65 factor knots），从同一个 PMF 导出 μ_b。没有独立首次 moment head。Query 不输入 best、science weight 或 declared program；所有 B 与 program 共用一次物理预测。因此 gain 关于 B 连续、非增、凸、1-Lipschitz，并且 B→0+ 与首次矩值一致。

## 3. 量化 hinge 的解析界

K=64，knots `g_j=j/K`。真实 F 位于相邻 [l,u]，使用质量 `(u−F)/(u−l)` 与 `(F−l)/(u−l)` 分配到两 knot，并保持 band 不变。这样精确保留 `E[F 1_b]`，0 与 1 端点也精确。

设 `h(F)=(aF−B)_+`，`a=w m_p(b)`。凸性使弦插值不低于 h。唯一可能有误差的 bin 是 kink `r=B/a` 所在 bin；其最大误差在 F=r：

`a (r−l)(u−r)/(u−l) ≤ a/(4K)`。

所以给定真实条件分布，投影后的 hinge **上偏且误差≤w max_b m_p(b)/(4K)**；当前倍率下每单位 weight 界为 .0046875。16 target 若 w≤1.7，纯离散化动作值误差≤.1275，两个合法动作的选择 regret 至多其误差和。这个界只约束真实分布投影误差，**不约束拟合 NN 的分布预测误差**。跨 required threshold 的 indicator 不连续，没有同样的 uniform O(1/K) 界。

Public last_result/resync 的 best 以六位小数给出。`|B_public−B_true|≤.5e−6`，上述 gain 对 B 为 1-Lipschitz，所以每 target 至多 .5e−6、16 个 target 至多 8e−6 的 best 舍入误差。Host 标签使用新 world 的真实 scorer F/b，历史输入严格用正式六位 score。Duration 是 `min(requested_end,survey_end,night_end)−start` 的实际整数秒，评分常数/权重/flux/bounds 均来自 public initialize。

`MATH_CONTRACT.json`：120,000 random target-program hinge cases；首次矩最大误差 4.44e−16；worst-case .0046875 与解析界一致；50,304 PMF/program/best 曲线点通过连续、非增、凸与 Lipschitz 检查。显式反例同时核对了 positivepart(mean)、独立 g/b 和 clairvoyant fiber max 的错误。

## 4. 四个全新 world 和官方小 runner

Pilot seeds 940901–940904，官方 catalog + weather + event + publication + stress 生成器，sha256-v1 命名分流；2048 targets、900deg²、38 夜、每 world 128 个公开几何采样查询。标签由官方 `WeatherTruth.band_quality` 和 `score_target_exposure` 生成，actual hit 仅在 host 用新 stress offset 判定。不是旧轨迹 quality/factor 拷贝。

最终 `PILOT_RESULT.json`：

| 项目 | 数量/误差 |
|---|---:|
| assigned queries / actual hits / misses | 4247 / 3684 / 563 |
| physical F=0 / physical F=1 | 812 / 685 |
| actual hit F=0 / actual hit F=1 | 704 / 582 |
| effective g'=0 | 1267（含563 miss） |
| 首次矩算子误差 | 2.22e−16 |
| 最大实际 hinge 量化上偏 | .0063567454（w不同，均满足各自界） |
| 六位公开 score 最大舍入误差 | 4.9978055e−7 |
| 官方 repair 前后重算合同 | 3 个 active fault 分支 |

每 world 另跑 12 次 observe 后主动结束的小官方 runner，共48 observe、380 actual-hit score、12公开 report result；每个公开 score 与官方 CSV 六位 score 相等。Actor 闭包只持有 whitelist initialize、公共 night calendar 和 action/history；不持有 host Scenario/events/slots truth。未来报告后的 labels 重新调用 repaired `WeatherTruth`，band 保持不变、F不下降；未复制未修分支 score。

Pilot 是 label 与接口合同，没有比较 NN accuracy/decision gain。第一次 source 虽仅访问公共字段，却闭包捕获整个 host Scenario，已保存 `failure_public_closure_v1/` 并改为公共对象。后续公共对象被 scalar score 变量覆盖而退出，失败 source/log/hash 保存在 `failure_shadow_public_v2/`。无一次失败用于选模型。

## 5. 已可运行的公开输入

`public_features.py` 与 `input_probe.py` 只读 own fresh `public_initialize.json`、小 runner 的公开 snapshots 与 actor actions，不读 scorer CSV 的 factor/quality/offset。

- 每个历史 target 24 维：六位 score/weight、actual-hit 与 miss 分开、hit-with-zero、实际 duration/initialize max、flux、declared program、公开 Moon/airmass H 统计、全程/中点 alt、sin/cos az、名义 tangent geometry、age、有效 ledger 标志与 presence mask。score 饱和留下其公开值，不推回假定的唯一 F/C/E。
- Future query 51 维：最多5个公开 slot 的 H/alt/az/overlap 轨迹统计、flux、实际 duration、全程 min-alt、time/season/phase ；pureF查询不含 pointing/fiber/tangent offset。未知 future weather、真实 physical band、future hit 与 true offset 均不在输入。
- 公告129维：terrain 9 direction bits；7 current kind×9 direction bits；6 forecast kind×9 direction bits（只查已发布 forecast 的 query night）；recent formal report age/correct/false。每个过去曝光保存**当时已发布公告**，当前 query 也有自己的公告。不能用当前 forecast 替代过去未发布 forecast。
- true 与 false formal report 都提供同一时刻 healthy anchor，但不保证后续没有新 fault。Loss 删除 best 的有效性，保留旧 score 作为当时的物理测量；mask让两种含义可区分。

`INPUT_PROBE.json`：427 assigned public tokens（77 zero-score hit、47 miss）、24/51/129维全部有限、12同时间报告 anchor；全部256个八方 terrain direction 集合都能表示。这个检查证明输入可用与表示支持，不证明 NN 已学会所有集合。

## 6. 阶段 2 拟锁的数据与普通 NN

**Root 已授权 source/四世界机械 gate 通过后实际 PRO6000 拟合。** 以下 source 和 `SAMPLING_SELECT_LOCK.json` 在 fit 前锁，旧 cal/test 不参与选择。

| split | seeds | worlds |
|---|---|---:|
| train | 961000–961095 | 96 |
| calibration | 962000–962015 | 16 |
| validation | 963000–963023 | 24 |
| test（模型/校准冻结后一次） | 964000–964023 | 24 |

这些 world 的 catalog/calendar 行为设计只取 L1/L2 **公共 initializer/action geometry/实际时长**或新公共几何采样，不读原 factor/quality/valid/offset/true event。每个新 seed 重新调用官方 weather/events/earthquake/fault/publication/stress streams；模板 L1/L2 按 seed parity 均分。固定设计不等于强策略在该 world 的反事实完整 rollout。

每 world 128 个按时间顺序的 query states，分层覆盖 early/mid/late 与夜内位置；过去8曝是新 world 的正式 hit-ID/六位 score。未来每 state 两个公共 field、五个合法实际 duration（min、300、900、1800、max，经当前夜尾/season clip 与去重），每 fiber最多两个原强几何准入 target，最多32 targets/field。Future labels 对准入 target 算反事实 hit 条件下 `(F,b)`；actual hit 与实际 action contribution另存 host audit，绝不进 future NN query。

每条 past action 的 report 由公共固定行为设计选择：有免费额度时按与 truth 无关的预先 schedule 触发；结果来自新 world 的官方 `report_fault`，correct补额度，false保持/消耗，后续 score重新按该分支计算。Host loss 按新官方 plan和实际observe编号重算有效账本；actor只接公开 resync。原强 calibration/admissibility 跟随新 public hit/miss history；future source/query均不得访问隐藏 offset。

生成 prior 明示为研究分布：天气每类次数从 rain0–2、overcast0–3、haze0–2、cold_snap0–2、storm0–1，rocket0–2、quake0–3、fault0–3 独立选取；其余连续参数与 terrain1–3 保留官方 reference。次数由独立 host design RNG（world seed+20,000,000）取值，不是正式协议保证。Actor不以最多三个 fault作硬上限。实际卡可能分布不同，必须靠后续冻结的强闭环检验。

网络：每 target token `24→32→32 ReLU`，按 presence mask 在同曝光内 mean/max pool成64维；与当时129公告、16 action/time/report metadata拼成209维。过去8曝209×8，再加当前129公告和16metadata，共1817维，`1817→64→32 ReLU` 得共享 context。Context32+query51，`83→32 ReLU→195 logits`，一次 joint softmax。μ_b和全部程序/历史best的期望 gain均从同一个PMF导出。无 C/E潜变量、whole-eventset prototypes、固定天气路径bank或带future truth的目标ID embedding。

训练 soft-label CE：真实 band 固定，F质量仅落相邻两 knots，最优预测就是该投影条件分布。Query不输入 B、weight 或 declared program。12 epochs、AdamW lr=.001、weight_decay=.0001、grad norm5、float32、GPU seed949200；按world均衡抽state，每state先平均有效queries后等state平均，batch8 states及其全部queries。PRO6000上普通Torch实际拟合；输出 NumPy权重与公共 fixture，Torch/NumPy gate另算，不以random-weight成本称已训练。

控制：current-public-only 模型保留完整当前129公告与16metadata，`145→64→32`context，同一个83→32→195head；只不接过去8次score/history。另保留冻结原强public point scorer作为同candidate对照。两个NN版本可在validation晋级，history是否新增value单独检验。均值正部只作明确错误的数学消融，不部署。两个NN均用同新的train/cal/val world，不能使用旧数据或旧Gaussian。

每 epoch按 calibration equal-world/equal-state soft-label CE 从预锁T∈{.8,1,1.2,1.5,2}选择一个joint temperature。Validation在两版本12epoch共24checkpoint中按全部24world的平均真实 science gain / actualseconds 选一个固定版本，tie先早epoch再current-only。所有模型/原point对照使用相同两field×五duration×三program、原`.008`glass margin、start min+.04与up-limit减1秒、公开calibration correction，以及同一original public closure/last_closed wait gate。只比较science，不加required/REQ/Jain/scarcity bonus；未来实际hit与truth仅host评价。

每个模型先期望，再同fiber max/assignment，再选field/duration/program一个可执行动作。真实host science按`I_hit F`与true prior best结算后除实际秒。每world等权，报告selected-vs-original-point、full-vs-current、selected-minus-best两control的paired差与world-bootstrap区间。Finite clairvoyant oracle只作同family后验regret，不能称可执行oracle或完整题上界。

启动一次test的gate：**selected固定版本相对原strongpoint validation平均Δ>0且paired95%world-bootstrap下界>0**；不因full-history未胜current-only就丢弃current-only的可能提升。History增量另报告。Gate通过后冻结source/model/temperature/checkpoint，仅生成/读取新的24test world一次；test只评价selected版本，不切另一模型，不救旧world/test/L4。未过validation门则test保持未生成。

PureF不依fieldpointing：51query只依目标、公开时间/实际duration、Moon/airmass轨迹；历史nominal tangent offsets独立算，保留miss几何信号。Public query/geometry缓存按initializerhash+target/time/actualduration；NN PMF缓存还必须model/temperature/context hash，同UTC report、resync、message改变也失效。不能在NN gain外再次乘terrain-clear或方向天气概率。REQ/Jain threshold不使用195soft knot tail，hinge误差界不覆盖completion indicator。

## 7. 成本和 source 的实际完整程度

`COST_PILOT.json` 是 Mac arm64、NumPy2.0.2、单线程、random weight float32 **未拟合** benchmark，单joint head（first moment也从此导出）。65536 rows共享stem .02407秒，joint head+μ_b .06447秒，总约.08853秒；histogram临时51.1MB，float64 reference差<1e−9。不是正式2CPU/2GiB gate，也不包含公共geometry/encoder/fiber reduction。

最多6,553,600 future target labels，query float32数组上界1,468,006,400B，shared24维history约251,658,240B，须按world分片/流式训练。Pilot官方scalar约90.25µs/target；线性外推 labels约591.46秒，**不含world生成、几何cache、context/features/写盘**。最终pilot `build_seconds≈1e−5` 是已存在world的查找，不能当新world生成成本；最初真正生成四world各.239–.256秒的证据保留在 v1 receipt。完整成本仍需实际新数据阶段计时，遇数量/速度偏离不能冒报已完成。

Mac BLAS曾对有限random-weight输入发 floating flag warning，输出有限；source/warning票据保存在 `warning_blas_flags_v1/`，当前benchmark改explicit einsum并与float64 reference核验。

**已完整可执行**：官方四world生成/labels、effective与physical语义分列、joint hinge/moments、public feature adapter、48曝小runner、公开输入probe、未拟合CPU成本。

**尚未完成**：上述96/16/24/24规模的数据builder与public-only采样/原强calibration adapter、完整hierarchical trainer/evaluator/NumPy export、生产原强science scorer安装。当前没有完整生产runtime候选或提交ZIP，不能宣称可部署。Root先review方案；若批准下一阶段，先完成这些source与4新world端到端public/label gate及source-lock，再真实PRO6000 fit。生产science替换需先核实调用规模和正式2CPU/2GiB预算，再由root决定完整闭环，不能把.088秒row benchmark外推成整季通过。

保持最强 `observer_sparse_exact_fault_20261004.zip` SHA `5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29` 不变。本阶段没有上线增益、模型accuracy或完整分数结论。

## 8. 阶段2实际 source 与机械票据

`physical_operator.py` 将官方≤120s每slot网格向量化；future同target/time/actualduration跨field物理标签与query去重，hidden event boundary只在host label细分，绝不进入NN输入。`data_pipeline.py` 只从旧public设计whitelist action/start/end/实际时长，重生成每world weather/event/publication/stress/score。过去测量在当时repair状态只计算一次，valid mask在query cutoff按已公布resync更新。Host effective/truebest/publicbest/weight/point双精度，训练F及输入float32。

新fresh机械seeds940911–940914，与train/cal/val/test完全分开。每world128states；完整public calendar逐slot核对；每世界约1k真实新past观察，分别对照未缓存原policy的C/E、ledger/factors/lower/calibration、clock与terrain状态。此前捕获的nightend、exclusive-enddate、pending-prior/startaz、host-rate-precision等失败source/log/world均保存在独立failure目录；没有用于模型选择。

`torch_helper/` 子agent已完成两架构、单joint195、state-balanced CE、NumPy导出/推理和公开CPUfixture；无优化器fit。CPU logits/PMF/stats maxerr1.788e-7，state-balanced loss误差0，gradient误差5.82e-11。`finite_evaluator.py` 与 `fit_driver.py` 已可执行finiteaction/cal/val/checkpoint选择，但尚未实际fit。仍没有替换原season science evaluator的生产runtime或新提交ZIP。

PRO6000 fresh环境read已验：Torch2.7.1+cu128、NumPy2.2.6、CUDA可用，GPU97887MiB/~10203MiB占用、108.68W/600W、5%使用；复用既有venv，不安装、不改功耗、不终止其他任务。大数据CPU生成与实际GPU拟合分别保存成本与日志。

## 9. 冻结 v2 与实际 CPU 生成

最终95项source冻结SHA `127444cd52a2800db383b7905e62b38baa6622caf4dc933d0cbcd1e1f3cdf2cb`，四fresh机械gate以及v2执行动作receipt amendment均通过root独立核验。V2仅新增host实际hit/publiccommandedpointing/start收据，四world18核心数组与v1逐元素一致，512动作通过officialnormalize。V1冻结tar全部95原hash可回溯；早期失败source/log未覆盖。

Rhodes1既有Python3.12.15镜像、NumPy2.2.6中12独立worker，实际136world数据生成完成：train96/cal16/val24、test0。墙钟308.058秒，worker累计3436.054秒，其中freshweather14.472秒、futurelabels186.259秒；3,943,796有效future行，136NPZ共355,392,736字节，全部SHA通过。过去新观测包含727miss、125,934 hit却scorezero与98loss-resync，公开有效性按query时刻更新。每split细项写CPU_DATA_COST_COVERAGE_SUMMARY.json。

原detached容器用--rm，启动时未注册dockerwait，因此原始Docker退出码缺失，不能据容器消失宣称exit0。GENERATION_COMPLETION_RECEIPT.json保留此缺口；完成证据是coordinator最终manifest/stdout、136worldreceipt及全部NPZhash。自己的数据容器初始8GiB接近限制后改16GiB，资源更新有独立票据，外部服务未更改。该成本是离线数据生成，不是正式participant2CPU2GiB900s表现。

WindowsPRO6000接收同一冻结source和四个lossless数据shard，hash验证通过后才启动实际12epoch×两架构。外部launch_gpu_receipt.py仅记录真实WindowsPID、原始进程退出码及nvidia-smi功率/显存，不改变冻结模型source。此处尚未给训练accuracy、validation或season分数结论。

## 10. 实际 PRO6000 拟合与最终拒绝

2026-10-04 05:42:43.858 UTC 开始，PRO6000 普通Torch2.7.1cu128实际完成两架构各12epochs，共24 checkpoints、36,864次optimizer update。Fullhistory epochs训练+校准+有限validation共332.057秒，current-only共287.102秒；外部观测启动至退出644.356秒，退出采样间隔20秒。33个nvidia样本设备total memory peak11,963MiB、power peak144.49W，功率limit始终600W。WDDM每进程显存N/A，total含其它进程且采样未保证瞬时峰，不能称本训练的精确allocated peak。

| 预锁 architecture 最佳 | epoch/T | finite mean science/actualsecond | 相对原point Δ | paired95%world-bootstrap |
|---|---|---:|---:|---|
| 原冻结强point control | — | 0.010464122405 | — | — |
| 完整history | 12/1.0 | 0.009868326363 | -0.000595796041 | [-0.000654620666,-0.000541168344] |
| 当前全部public-only | 8/1.0 | 0.009241981821 | -0.001222140584 | [-0.001326879615,-0.001120297375] |

Full−current mean+0.000626344543、CI[+0.000561516119,+0.000693409863]，仅是两预声明架构的有限动作模型对照，不能单独归因于history、不能转述成season收益。整体最好模型仍比原强point低约5.69%，两模型相对point的区间均严格负，所以性能门拒绝；新24test world保持未生成。原最强ZIP5b00e6a…完全不变，无生产adopt、900秒full或REQ/Jain得分结论。

**最终driver原始exit1，而不是成功结束。** 24模型文件和逐epochval/action收据已写完，复制描述性的最高val weights后，NumPy-vs-CUDA public logit门 `<3e-5` 失败，因此SELECTION_RESULT和SELECTED_MODEL_LOCK均未写。原始rawstdout、exit1、全95source指纹、完整publiccache frozen snapshot、所有24PT/NPZ/eval/config/trainlogs/遥测均归档。未修改source、放宽门或重fit。

只读具体诊断：8publicstates、2060validqueries，原float32 NumPy/CUDA maxlogit差3.0517578125e-5，最大logit绝对值149.32；CPU/CUDA差1.90735e-5，float64 accumulation NumPy/CUDA差2.28882e-5。PMF max差7.74860e-7、均值6.44345e-7、expectedsciencegain7.53687e-7，抽查动作assignment完全相同。这与累加roundoff一致，但严格冻结门仍记失败，不作全输入部署正确性证明；因性能已有拒绝原因，本轮不修部署parity。

136原NPZ+各world JSON全部本地SHA匹配，87拟合源产物全部SHA匹配。4个lossless数据tar和拟合gzip tar为重复运输资料，移至owned/tmp；DATA_TRANSPORT_RESTORE_MAPPING/GPU_FIT_TRANSPORT_RECEIPT记录SHA与恢复路径，Git备份保留原始小文件本体。远端artifact manifest一处literal trailing newline错误也保留原文本与hash，并仅规范JSON语法，产物hash未改。

本轮完整可执行的数据/operator/publicfeature/训练/NumPyexport/有限动作source已实现，但最终selection driver失败且模型性能门拒绝；**生产runtime集成与正式2CPU2GiB gate尚未做**。下一物理结构路线（已知flux×duration×H缩放可能应显式使用）只是root另记的研究假设，本轮结果不证明它是失败原因，也不救本轮参数。
