# 算法路线、独立探索与采用标准

更新：2026-10-04 07:15 JST。本文件区分已完成实验与正在计算的路线。目标是提高完整赛季的实际得分；参赛程序允许传统算法与普通神经网络。

## 当前证据

- 最新完整官方批次 Request Cache 四卡均分 **6735.09250250**。历史不同批次的单卡最高值算术平均 **6836.95278225**，尚未作为新包完整实测。
- 20:51 JST 榜单截图记录的榜首四卡均分约 **7580.7075**。相差约 **845.615**；约 **670.692** 来自科学分，required 缺失约150，请求约25。该榜单值按页面两位小数计算，随之后提交可能变化。
- 旧 alpha 有限列 LP 值 **7373.168525333**，低于榜首该卡可行分 **7937.94**。它约束了候选池和质量模型，不能充当原问题上界。
- 公开本地 L1–L4 的生产 CPU 基线为 6096.185388、6534.787015、5633.730701、5869.556485；与平台 alpha–delta 是不同数据。旧 GPU L1 的一个源快照实测6348.155319，源快照必须一起记录。

## 路线与需要改变的决策

| 路线 | 模型或搜索对象 | 有价值的实验 | 不能据此得出的结论 |
|---|---|---|---|
| 多起点贪心、beam、LNS | 真实时间上的曝光区间、pointing、program、时长、assignment；终局 best-only ledger | 保留高分初解，短曝光与原始连续起止；单晚高吞吐修复，低频非连续多晚交换；相同墙钟预算消融 | 同粗候选池赢贪心，不等于赢现有生产程序 |
| 遗传、群体、随机搜索 | 整季可行排程群体；按夜/区域交叉后修复时间和观测编号约束 | 精英保留、排程差异度、多个初解来源；用真实结算选择个体，记录每个算子的净贡献 | 种群大小、代数或者搜索次数本身不能说明进步 |
| 图论、网络流、匹配松弛 | 时间容量、纤维容量与目标终局 max reward；移除部分物理耦合构造乐观资源图 | 对明确的全集/松弛证明可嵌入，再计算能包住已知可行解的上界或影子价格；每个时刻固定 field 的指派仍可精确求解 | 固定旧列的流/LP 解不能约束尚未生成的连续物理动作 |
| 剪枝、分支定界 | 部分排程及剩余时间/可见性资源 | 以可验证的乐观续局值剪枝；只在覆盖完整分支或有支配证明时删分支 | 没搜到补偿列，不等于这种补偿物理上不存在；Jain 项也不保证覆盖数单调 |
| 随机过程、期望模型 | 根据已公开反馈更新天气/仪器状态，按情景模拟续局 | 学习真实科学增量的分布、未来可见窗口及时间影子价；公开 L1–L4 隔卡验证 | 即时 program 分类准确或某个反馈可辨识，不等于整季高分 |
| 普通 NN / RL | 终局 continuation value、机会成本、候选提案或时间资源价 | 多策略分叉 rollout 的实际终局差作为标签；保留几何/指派精算，NumPy 部署；隔卡完整重放 | 小训练损失、快 GPU kernel、赢简化弱基线，都不能证明生产提升 |

## 已完成的新探索

1. **GPU 局部候选 NN**：实际在 PRO6000 上训练27→64→1模型。L4 top16局部 regret为10.53%，旧 coarse为0.35%；不采用。它预测冻结即时效用，尚不具有整季价值。详见 `results/nn_proposal_20261003/README.md`。
2. **独立全季 LNS**：初版粗池相对同池贪心提高约403.770、363.041，但低于生产；同100秒单晚修复比多晚高约87.730。随后解除最短900秒限制，保留全部原始短曝光，以真实强排程开始，每卡600秒搜索。官方本地完整重放L1 **6348.155319→6409.988920（+61.833601）**，L2 **6949.795139→7008.567151（+58.772012）**；每卡救回一个required，科学分分别+11.931757、+8.717827。这是本地truth、固定报告时点、有限新列的先知改善，不是云平台提分。详见 `results/cold_global_search_20261003/`。
3. **独立概率/资源图模型**：联合期望 program 模型四卡条件实验没有稳定收益。完整target-slot图包含任意连续曝光的资源嵌入，没有沿用旧曝光列。后续全球64800 cells空间支持函数已实现，六种目标价格未收紧旧界；连续3600秒单次积分上限将L1/L2乐观上界收紧至 **8671.259552/9502.027614**。最佳对偶仍为零，没有生产可用时间价格；数值容错证书不是区间算术形式证明，界仍宽。推导见 `SPATIAL_SUPPORT_BOUND_ZH.md`，实验见 `results/cold_probabilistic_model_20261003/`。
4. **独立 NN 未来价值**：初版简化控制器失败；同源强策略L3对照5701.591442→5544.336893（−157.254549），拒绝采用。之后实际生成六条强轨迹的550741目标状态和2883全局终分标签，训练联合预测required survival与signed science增量的模型。两条真实相同前缀反事实续局：L1等时wait替换observe100/700，完整终分分别+4.784766/+43.246978，主要来自后续science。它们是行为策略的因果教师标签，不是NN得分或泛化证明。详见 `results/cold_neural_value_20261003/`。
5. **delta 固定 rank 交换**：自己官方账本证明 REQ1曾达到6/6，后来数据失效撤销两条 witness，最终4/6。完整动作只换两个曝光，固定时间、时长、wait和report；条件模型净增45.216477。未知质量/方向条件仍须官方重放，尚未提交。详见 `results/request_quota_failure_20261003/README.md`。
6. **独立遗传/群体实验已完成**：绝对时间基因、夜块交叉、区间修复、种群距离和精英保留；四卡各600秒GA与600秒单轨对照，共八次官方完整回放。L1/L2 GA赢，最佳 **6418.234926/7016.964672**，比新强LNS初解再提高8.246006/8.397521。L3/L4单轨赢，最佳 **5796.894090/5937.710055**，比对应强初解提高163.163389/68.153570。已完整处理回溯loss；本地truth、有限池、固定报告条件没有改变。GPU终局fitness并非本轮主瓶颈，实测区间修复更贵。详见 `results/cold_evolutionary_season_20261003/`。
7. **独立可证剪枝已完成**：每卡规定原始族31^5=28629151序列，program向量支配先减少99.4%–99.9%，保留族再B&B剪70.65%–99.74%，与524806叶全穷举一致；另119164原始三阶段序列核验支配前后最优相同。Jain区间上界有推导，53016内部上界零违例。L1界开销使B&B慢于穷举，其余更快。另在214/174种未来loss-trigger N下验证ledger存活签名压缩，不改变动作计数。这证明有限族/状态压缩正确，尚不是完整题目全局最优或生产提分。详见 `results/cold_pruning_proofs_20261003/`。
8. **新的全目标几何构造**：固定时刻和曝光收益下，每个玻璃格选择其中收益最大的目标。对全部有用目标的玻璃边界做二维加权事件扫，再将获胜指派的共同可行盒居中、连续修正球面指向，最后用原精算器选择曝光时长和程序。16次同源完整回放已完成。相对真实强CPUPhase，独立sweep四卡均分 **6255.297401→6294.563907（+39.266505）**；保留完整Phase初解的union为 **6270.198543（+14.901142）**。对基础Spatial的+215.591776不能称为强策略提升。两种新构造在L4都多缺一个required，体现末季时间分配仍是瓶颈。24组逐格穷举全通过；672个隔卡几何教师group已保存。详见 `results/candidate_geometry_20261003/`。
9. **PRO6000终局动作critic已完成并拒绝**：5,568个完整曝光反事实，标签替换当前动作并删去重叠曝光，完整结算终局科学、required、REQ、Jain及loss。35→64→1普通MLP实际CUDA训练6000步约4.12秒，L3完整协议分 **5769.301279→5441.010433（−328.290846）**。未用L4救模型。相同教师另做GPU boosted-tree的预声明depth2/4/6控制，选中模型L3排序regret6.238878，仍差于实际public utility选择的4.853964，直接拒绝，不加额外整季测试。教师正向分支很少，汇总特征不能可靠表达未来目标竞争；增加步数不是解决方法。下一次学习应使用真正重新规划的分叉续局及目标层竞争结构。详见 `results/hidden_learning_20261003/`、`results/gpu_action_critic_20261003/`。
10. **双层天气滤波已完成并拒绝**：官方V4生成器夜层AR保留跨夜记忆、槽层每夜重置；独立Kalman实验在L3预测RMSE降低约19%，L4不稳定。时间deadline截断曾使L4单次对照+532，重复后符号翻转。固定24锚点工作量消除混杂：L3 **−28.938401**、L4 **−73.902698**，未采用。官方生成器及slot内常量、forecast事件夜支持规律已记录；不能用旧v3随机miss/false-positive假设代替V4。详见 `results/generator_forecast_20261003/`。

## 最新门检与仍在计算的实验

- **可部署几何后端已READY**：C++/ctypes保持研究kernel语义，已在Mac与受2CPU/2GiB限制的Linux容器上核对715组、53,840,920个排列格，中心/值/访问数逐位一致。Linux仅依赖libc/libm，最高GLIBC符号2.3.4；不在评测时编译或加载Numba。独立submission ZIP已生成。四卡受限协议均完整结束、无traceback，L1–L4实分 **6362.021539/6823.661561/6004.504542/5974.281941**，均分 **6291.11739575**，每卡433–522秒。同环境同预算固定强CPUPhase四卡对照均分 **6241.898614**，逐卡增益 **+72.028922/+31.442316/+89.675321/+3.728568**，平均 **+49.21878175**；八个完整协议季节均通过。历史Mac分数不一致已定位：同一字面float64优先级向量的六个相等元素，在Mac NumPy2.0.2与Linux2.2.6的默认argsort下发生不同顺序，改变最后两个anchor；前缀状态、反馈与输入完全相同，Mac Numba/native也完全相同，排除kernel替换。证明和字面向量保存在 `results/geometry_native_20261003/trace/L4/`；[NumPy文档](https://numpy.org/doc/2.2/reference/generated/numpy.argsort.html)说明默认排序不保证同值相对次序。候选源和ZIP整个门检过程保持不变。尚未云平台评分，浏览器接口连接超时；不把本地四卡增益称为正式alpha–delta增益。
- **免费误报额度的诊断策略已拒绝**：report不耗模拟时间、不改变observe编号，正确修复补回误报额度。直接花光两次免费额度在L1造成−219.67，证明额度有未来机会成本。保留一次给原有witness分支的策略在固定24锚点CPUPhase bypass的L1/L2/L3/L4分别 **+36.063219/+9.314604/+8.964608/+6.435674**。启用完整Phase的同源同工作量门检反而下降：L3 **5910.930583→5909.315457（−1.615126）**，L4 **6095.293215→5912.328130（−182.965085）**，平均 **−92.2901055**；L4多缺两个required。新增report全为false、无直接扣分，策略仍因belief reset及排程轨迹交互显著退步。停止采用及native组合；这说明零直接代价和弱基线收益都不能替代强策略完整验证。实际官方合成quake+fault场景证明诊断能修复的机制实验保留，但不是隐藏卡收益证明。
- **required全局时间预约已拒绝**：新无context代理独立从阈值任务与天文时间窗推导，将长曝光目标和非重叠一小时时间块构成最小费用匹配，再用公开反馈滚动重排。75个随机匹配与独立SciPy最优值一致。L1初版 **+6.598214**，但存在预约起点过期/越过自身块尾的执行偏差；修正并锁定公开resync处理后，八条同源完整回放全部结束：最终L1–L4差值 **−0.568916/−206.077356/−173.295510/−371.664486**，均分 **6255.29740125→6067.39583425（−187.901567）**。最终过期起点为零、resync均处理；失败主要来自条件可行预约反复截短科学曝光，L3损失一个REQ、L4多缺三个required。匹配求解精确不等于减少后的排程模型正确表达机会成本；不救参、不部署、不做额外资源门检。源码、所有实验与核验保留于 `results/required_allocation_20261003/`。
- **独立随机情景/决策价值模型已拒绝**：新无context代理先独立阅读官方评分/生成器，再查重，构造路径内完整曝光积分→program band→饱和→历史best正部/required阈值→最后取期望；增加模型内75%/90%完成分位对应的曝光时长（不是已校准真实概率）。固定16路径、8字段。初版L1 **+161.416771**，均值积分消融 **+166.698785**；补高度过滤后 **+229.682088**。独立审查发现有限路径bank随候选最大时长重排，短曝光分布不具前缀一致性，故这些初版收益未采用。机械固定(path,slot,latent)后，3456官方积分/结算对照与共同前缀门检通过，28485次最终指派高度检查零违例；最终同源完整L1 **+25.788278**、L2验证 **−59.321419**，平均 **−16.766571**，required/REQ不变。实际参数未改、不用L3/L4救参、不追加ablation；停止此版。所有初版、修正、对照、审查与源码在 `results/scenario_value_20261003/`，不能将初版高分替代最终验证结果。
- **新的全局物理动作搜索第一版已拒绝**：`cold_global_field_search` 使用fork_turns="none"，先独立从官方评分/纤维几何推导球面pointing盒、目标/光纤兼容图及16行Hungarian匹配局部界，再查重既有路线。搜索整个安全约束域，固定展开预算后返回候选；不是全局最优证书。1500随机盒/60000点的10561次缩边玻璃命中全部被包含；2500点、125个focus试验未发现冻结效用匹配界违例，但这些随机状态全部使用3600秒上限，遗漏了夜尾边界。首帧局部收益不代表完整分数。预声明256展开/16候选的同源L1受限协议已结束：强CPUPhase **6289.992617 / survey_complete / 528.36秒**；新增搜索 **5771.562541 / global_wallclock_expired / 900秒**，后者只有截断季节账本，不能采用。native固定时长列表还漏掉当晚剩余时长裁剪，会污染夜尾排名；实际发出的动作仍由原Python精算，因此没有因此发送超夜尾曝光。另独立确认72断点限制造成部分候选损失，不能把其他差异都归因于此。下一版先修正时长全集并补短夜尾门检，再考虑native直接输出经验证动作、用可执行率更新incumbent，以及按球面field半径预筛根盒目标以减少昂贵区间运算；保持全域模型，不用缩节点替代结构改进。源锁、完整控制及截断搜索原始账本、错误定位均保留于 `results/global_field_20261004/`。
- **无上下文目标/图结构审查已完成**：`cold_objective_graph` 独立阅读正式实现后，将science max、required及普通完成视为固定终局存活曝光集合上的coverage项，请求k-of-n奖励视为跨曝光互补gate；Jain存在负边际，完整序列还必须处理observe rank及回溯失效。给出了有限列的时间DAG、score-layer/raw-witness OR与请求quota模型，普通图NN仍为设计。后续天顶与program信息动作的实测见下一项。
- **天顶与program信息动作的独立审查已完成**：L1/L2各8个真实前缀状态的天顶az事件扫描，4/16比固定A=0更好，0/16胜过强CPUPhase；保留合法自由度，但不做独立切换的完整季节测试。前缀微验证使用离线真实factor和共同天气先验，不能称为部署策略实测。program同时影响从公开score得到的无条件raw-factor下界：L2有16个required首次真实达到阈值时仍无完成证书，之后18条hit到首次证书期间仅增加3.521683科学分，不能将这些hit等同于浪费曝光时长。独立代理从离线真实science成本为零的机会中预声明选最早L2 rank6：固定前缀、pointing、627秒及15 assignments，仅BRIGHT→BACKUP，然后两条分支都真正重新规划到终局。11项门检全部通过，control逐动作重现原轨迹 **6792.219245**；BACKUP **6765.980248（−26.238997）**，science−26.251138、Jain+0.012141、required/REQ/report不变。证书确实增强，但C/E后验也改变，observe1096→1103；没有得到终局收益。停止该program切换路线，不用其他卡救选点。真实replan分叉、零当前science代价与负终局标签均归档，结构化图NN仅保留为尚未实现设计，没有宣称训练成功。详见 `research/objective_graph_DESIGN_ZH.md`、`results/objective_graph_20261004/MANIFEST.json`。
- **全域物理搜索第二版已完成并拒绝**：机械修正所有时长边界并纳入阈值/失效两侧，native直接输出duration/program/assignment；将7位命令重分类后才更新可执行incumbent剪枝。根盒目标使用排序高度区间与保守球冠dot前筛，再做昂贵投影区间与匹配，保持同256展开预算。独立逐整数检查覆盖短夜尾、负Jain阈值前秒、focus up切换、完整指派及官方几何。L1两条受限协议均survey_complete：control **6289.992617 / 530.093秒**，search **6246.329317 / 588.452秒**，差 **−43.663300**；science−43.459938、Jain−0.203362，required/REQ相同。READY native **6362.021539**仍更高，且REQ 2/2。997次搜索、255次采用新动作，native总成本56.319秒，根pool安全剔除87.79%；相较第一版前915次搜索已耗402.607秒，结构优化解决超时。首个同历史分叉合法且真实science增量+0.063036，全季仍下降，说明局部更强不等于终局更好。按预声明停止L2，完整源码、同源账本、强基线、逐秒证明与拒绝报告冻结于 `results/global_field_20261004/v2_archive_manifest.json`。
- **无上下文逆问题阶段一已完成，阶段二继续核验**：`cold_band_identification`独立推导同槽C（q-band质量）与E（效率）的分段可行集合、饱和/舍入处理及不可识别反例。36组合成场景和411条参考曝光未排除真值；L2两次自然跨program历史缩小了未来档位集合，未新增效率诊断证据，也未做整季策略测试。纯60秒判档probe在固定线性目标、无自身终局贡献、信息仅限当前900秒槽的条件下，最佳仍亏损1/600；这个结论不涵盖有效科学曝光或持续故障。后续发现65°筛选缺乏正式terrain范围保证，阶段一使用truth槽时间也须改为公开推导；这些限制单独记录，不改写旧结果。阶段二正在验证单采样短曝光或严格匹配标签的公开筛选，只有实际改变状态/动作才启动赛季。详见 `results/band_identification_20261004/MANIFEST.json` 与 `PUBLIC_DEPLOYMENT_LIMITS_ZH.md`。
- **无上下文跨时段纤维竞争微实验已完成**：`cold_horizon_contention`先读正式实现再查重。公共时间DAG上的Beam Search每节点重生field、三program和全目标fiber指派；从L1/L2各8个末夜公开状态筛选27个同fiber替代，预声明的即时/续局排序反转和未来路径变化均为零。独立状态、实际指向偏移、observe rank及无REQ/loss门检补齐后，结果逐项与首版一致；两次强制旧tape的官方整季重放精确重现 **6362.021539/6823.661561**。42个beam、243次native choose、6871个保留assignment选项；两卡全部微审计76.10秒。没有合格点，故未启动真实replanning教师、GPU训练或Rhodes大任务。这只否定固定600秒弧、冻结belief的27个末夜替代，不能否定全季竞争或宽beam。源码、失败与全部结果见 `results/horizon_contention_20261004/MANIFEST.json`。
- **质量联合约束的受限赛季对照已完成并拒绝**：阶段二仅接受由initialize夜历/slot_seconds定位、发起时bulletin一致、无非terrain公告、<=120秒单采样正分的自然曝光；report/跨槽/新slot清空。强native L2的98条合格曝光均包含真C/E，一次自然多program联合产生一个新增冲突。保持原pointfit/ledger/report和20文件READY源码字节一致，仅将当前planning env投影到联合可行集合；observe489从原230秒/14targets动作改成174秒/11targets。Rhodes1两组2CPU/2GiB/900秒协议均完整完成：control逐动作重现READY **6823.661561**，constraint **6776.887746（−46.773815）**；science−46.994499，Jain改善+0.220684，required/REQ/report相同。两组accounted分别522.308/520.967秒，七项门检通过；没有participant truth挂载、源锁变化或traceback。更紧的正确状态集合仍未带来终局收益，停止这个最小投影规则，不救参。完整来源与对照见 `results/band_identification_20261004/stage2/`，计算已释放。
- **无上下文失效风险微审计已完成，暂无部署动作**：`cold_survival_hedging`建模低science备份witness的分数层OR、completion OR、REQ quota与共享随机失效窗口，追加observe须重新算所有历史rank风险。参考generator连续区间先验及六位端点舍入有解析积分，严格区分公开契约和隐藏x/trigger；30个窗口cells调用官方完整ledger全项结算，科学期望与分数层解析一致，REQ真实联合期望88.888889而错误独立近似86.419753。空observe改变N可产生−0.111111或+0.059259外部性，不能只计新hit。实际L1/L2无loss；163/233条低science hit中各5条提供新REQ窗口证书，这已经由原策略覆盖。Hard公开历史在明确synthetic x/N先验下仅9/3条备份有小额保底边际，未形成当前合法field排序差异。不到1秒CPU，无新策略赛季/GPU/SSH任务；停止此轮部署尝试。详见 `research/survival_hedging_REPORT_ZH.md` 与 `results/survival_hedging_20261004/MANIFEST.json`。

## 独立探索机制

### 2026-10-04 新一轮独立路线

- **连续时长与完整field组合微域已完成**：无context代理先读正式实现再查重，在L1/L2首个同槽已收到反馈且余至少600秒的公开状态（均rank1）搜索两个完整field、program与整数曝光时长。原生下一动作字面一致，候选冻结后才调用官方裁决。相对限制为两场的greedy有正差，但原强base在同样782/797秒内分别安排五场和三场；最佳双场对该控制实际为 **−53.351853/−122.192665**。已启动的三场L2微跑也为 **−1.459190**，停止固定动作数扩参。L1 777600双场叶9.23秒，L2 347328叶3.87秒。没有整季replan或GPU任务；这些仅为负的短域标签，不能当终局teacher。完整推导、动作、强控制与源码见 `results/compound_time_graph_20261004/`。
- **真正续局的policy-iteration教师已通过门检，批量已启动**：无context代理独立建立公开历史上的半马尔可夫模型，候选只取当前公开状态，改变field、duration或program后由冻结native正常重新规划到季末。revision5因官方stderr截短而丢失capture，失败保留；revision7改为起初空的独立公开输出挂载。四卡自然控制完整重现READY全部动作、总分与分项，早rank64和晚rank858加速控制也逐动作相同。L1/rank64五条完整续局中field **+21.474136**、short **+41.425680**、long **−101.779266**、program **−125.395166**，全部保留；后续动作真正重新规划，非固定未来tape。首批按公开夜历16中分位/卡预声明64状态组、最多320季与256相关基线差标签，只有32训练状态；L1/L2拟合、L3验证、L4测试。独立审计和root核对源锁、完整状态、原始capture字节、全部候选、终局前冻结、失败归档和严格过去前缀后，Rhodes1 driver **973012** 于 **2026-10-03 19:38:56 UTC** 实际启动8 workers，物理核0–15，每季2CPU/2GiB无网络容器。首8组均冻结5个不同候选；尚未完成bulk或训练NN。预算预计 **2.08小时**、保守 **3.45小时**，6小时停止新作业；每组只有一个真实未来世界，不是精确条件期望。完整证据见 `results/policy_iteration_20261004/PILOT_AND_GROUNDWORK_REPORT.md`、`ROOT_PILOT_AND_BULK_INVENTORY.json`、`bulk_job.json` 和独立 `results/teacher_bulk_audit_20261004/report.md`。
- **无context闭环遗传策略独立建模和合成门检已完成**：新代理研究公开历史上的任务承诺、放弃与恢复语法，由共用物理解码器生成合法动作，区别于旧truth动作带GA。四个公开布尔谓词、三种算子、深度≤2的6123棵树可按精确抽象行为压至1287类（少78.98%）；0.401秒合成官方账本门检通过。初稿的动作包摘要支配不足以保留终值，已明确撤销。最多12条真实分叉准入后才做等预算GA/单轨；后续最多71季，约8.54–10.30串行小时，暂未启动。无实际季节提分证据。详见 `research/evolutionary_policy_REPORT_ZH.md` 与 `results/evolutionary_policy_20261004/`。
- **独立PRO6000结构化NN已实现并通过导出检查，尚未训练**：Windows独立环境PyTorch2.7.1+cu128/NumPy2.2.6实际识别sm120与96GiB，原RPC/Numba环境未改。6598参数DeepSets用逐目标公开账本/未来几何和动作指派池化，匹配6507参数flat、ridge及native控制。真实CUDA与纯NumPy导出最大误差8.58e-6，目标置换误差7.45e-8，梯度有限；只核验随机权重，没有读取真实教师标签或训练。独立审计补齐重复动作/标签、相互矛盾baseline和control-only状态的准入处理，13项合成检查通过。bulk只有32训练状态，首先检验小模型与标签质量；未校准导出 `deployment_calibrated=false`，选择仍返回native控制。来源见 `results/structured_nn_runtime_20261004/`、`results/structured_student_20261004/`。
- **NN检查点的决策目标已修正，实际标签尚未读取**：root用实际metrics函数构造 `[0,−100,+1]` 合成终局差。较低MAE模型（1.0）却选收益0的control；另一模型MAE1.666667却选收益+1候选。改为固定L3候选上的 `teacher_regret_mean` 优先、MAE仅同分比较，数学上等价提高所选候选的平均已实现收益。新trainer SHA `933e40c2…249585`；15个既有非train函数AST与四CUDA模块保持不变。单世界/相关状态的教师排序不是整季部署收益，完整回放仍必须做。此次预声明修改未读取实际bulk标签、未训练、未改teacher锁源或数据划分。来源见 `research/decision_objective_probe.py` 与 `results/decision_objective_20261004/`。
- **无context因果信息价值微实验已完成**：独立代理先读官方题目再查重，以同slot≤120秒单积分片的正分anchor与零分hit对照，结合共同仪器/天气标量、公开program乘子范围、饱和及六位舍入严格下界推导固定terrain blocked证书。强native旧历史得到L3六个、L4七个新证书，13/13离线truth核对正确，5168正分约束零反例；L1/L2没有新blocked证书。原被动terrain忽略zero，原生产策略已有1200秒临时blocked回避，两者均与本机制区别清楚。官方评分器两个声明先验世界的合成场景中，同一个60秒有效科学probe仅按公开反馈改变840秒续局，期望终分 **+6.107668**；相对两种限定900秒单commit较好者净增 **+6.004849**。这是存在性机制，未改真实卡策略、未完整replan、未部署。后续固定L4/rank4与L3/rank255公开动作准入已执行并停止：L4同一动作集合上的信息价值0；L3高地形世界被旧observe77三个正分严格排除，原模型数值只作拒绝诊断。没有官方候选评分或整季回放。L4两步承诺的surrogate差+40.390不是信息收益或真实卡增益；完整公共历史支持审查和冻结结果保留。这些研究点不是未见卡测试。来源见 `research/cold_information_value_20261004.md`、`results/cold_information_value_20261004/` 与 `results/information_value_action_gate_20261004/ROOT_REVIEW.json`。
- **无context条件性得分状态商已完成**：独立代理发现单窗口score双向纪录/阈值极端witness属于既有结论后停止重复，另推导无剩余失效、且公开几何证明余季不能再得正factor的目标退场。退场science/required归常数，Jain按RA带计数、REQ按成员计数，活目标仍逐ID；目录、observe rank、反馈与belief保留，未来新请求不能用issuance之前历史作witness。几何覆盖把每夜开始向前扩最长3600秒，包含日间gap发起曝光。最后一夜开始四卡均无可退场目标，最后1小时仅动态得分数组减少 **33.15%–41.51%**；未测搜索树或actor内存缩减。2000组已有六位CSV账本更新最大差2.15e−10；合成256历史压为57终值类，4096次官方结算误差0。数值解析证书留1e−7度容差，非区间算术证明；不能无条件假设正式契约保证无下一次loss。无新赛季、部署或提分证据，停止本轮扩搜。来源见 `research/cold_search_reduction_20261004.md` 与 `results/cold_search_reduction_20261004/`。

- **真实学生数据运输与GPU比较工具已审查并预放置，尚未拟合**：新打包器必须等待driver终止记录，重新核对全部64组、28项v2门检、每个archive/member及原始公开capture字节；完整保留正、负、tie、absent、control-only和失败记录。L1/L2/L3与L4分别打包，候选不会自动接受。13项新合成流水线检查通过；root核对源码锁及凭据隔离。Rhodes1已放置打包器，PRO6000新独立目录已放置五个锁定学生模块和固定比较runner，未复制实际数据或执行训练。下一步由root审查真实终止批次，再仅运输fit/validation、固定单次训练DeepSets与flat，按L3决策收益对比ridge/native。来源见 `results/structured_student_dataset_20261004/ROOT_TOOL_REVIEW.json` 与 `README.md`。

- **无context学习对象研究发现严格的请求关系信息丢失**：两个合法合成公开局面仅改变请求成员图，现有真实feature builder的target/global/edge/scalar/flat全部逐项相同；两个当前候选加同一固定公开续局，经官方动作/几何/曝光和终局结算为 **102.4/2.4** 与 **2.4/102.4**。两世界等权时任何当前表示上的选择器候选regret为50，增加宽度/训练步数不能修复该表示碰撞；这不是实际卡提分或全集最优证明。最小逐request节点与成员join已实际打破碰撞，五学生模块源锁保持不变。root另只读固定64个control的公开capture，训练32状态仅4个活动请求、3个还有剩余请求；数据不足以支持复杂请求模型的泛化。独立小型逐request关系adapter已实现，19项碰撞、重排、ID重命名、空账本及时间窗检查通过，未替换固定比较或训练。原特征器empty-ledger异常的一行dtype=bool修复已精确重现并仅在隔离内存模块验证，未来部署版必须另行修复，当前五模块锁源保持不变。来源见 `research/cold_learning_signal_20261004.md`、`results/cold_learning_signal_20261004/ROOT_REVIEW.json` 与 `results/student_public_coverage_20261004/`。

- **新无context图论路线已完成并停止真实验证**：联合请求gate保留window-aware `(request,target)` occurrence，共享有效witness可计多条请求；相同未来完成列签名可作严格有限列状态商。官方六列合成域净增 **5.348**，300组官方ledger/穷举差0；密集容量65536→64，实际稀疏可达状态没有减少，不能称搜索加速或胜native。四条现成强控制公开历史均只有两条相隔数周、成员不交叠的请求；已知官方生成器也全局排除跨请求重复目标。合成共享target机制符合协议但不来自该生成器，当前没有能改变真实卡动作的联合触发点，不开全季。来源见 `research/cold_graph_policy_20261004.md` 与 `results/cold_graph_policy_20261004/ROOT_REVIEW.json`。
- **新无context公开随机规律审查已完成**：先读examples再查重，补核验固定官方公开v4源码commit e01939d0；目录内部共用catalog流，天气/事件/requests由SHA命名分流，同master不代表同随机状态，部分bundle构建甚至可用不同master。八卡28对同编号目标坐标匹配均0；97/97预报夜条目匹配公告，其中88提前、9同步。官方scorer人工同公开输入不同hidden slot得分 **0.568820/0.049897/0**，仅证明协议上的状态非唯一，非实际seed复现。既有hashed/legacy 32位枚举无命中已归档，本轮不重复或扩大seed域；不能把该指纹家族无命中写成绝对不可恢复。未恢复实际seed、未开GPU/季节、无部署候选。来源见 `research/cold_public_rng_20261004.md` 与 `results/cold_public_rng_20261004/ROOT_REVIEW.json`。

已创建每小时运行的线程 heartbeat **GOSIM 独立算法探索**。每轮启动 `fork_turns="none"` 的代理：先给官方题目、评分与资源位置，不传旧推导；代理独立抽象后再与现有实验对照。轮换群体搜索、图/流松弛、可证剪枝、概率模型、NN/RL及混合方法。只对实质新结果、改进、证明、完成或失败通知，重复状态保持安静。

持续目标已收窄研究优先级：以实际提分、数据规律和隐藏测试准备为中心，不再重复计算松弛得分上界；已有证明用于加速具体求解。算法方向的广度保持，不能反复训练同一失败教师或只扩大旧池搜索次数。

独立初版可以使用简化模型找机制，但必须报告与真实问题的差异。已有方法的名称不能替代模型、代码与实验；失败实验也保留源代码、数据划分和原因。正式采用前统一通过以下三层：

1. **合法性与结算**：使用官方几何和完整季末结算；时间、纤维冲突、观测编号、回溯失效、required、REQ和Jain必须齐全。保留初解时先证明原样重放一致。
2. **公平效果**：同数据、同源快照、同预算，与实际强基线完整重放；训练/选参/最终测试分开，所有试验透明记录。固定天气先知方案与未知卡在线策略分别报告。
3. **部署与官方确认**：2核/2GB/900秒约束；完整包及public check通过后谨慎使用评测额度。最终只称官方整批实测均分，不能用跨批次单卡拼接。

全部源码和有信息的结果进入本地Git及已有私有GitHub仓库。凭据继续隔离；不填写设计备注。

## 固定学生比较的完整性修正（06:22 JST）

在读取本批bulk训练/验证标签前，root把此前已计算但被最终选择遗漏的两种公共启发式纳入，六方案完整比较。NN checkpoint仍以L3候选teacher regret、同分MAE选择；跨方法按同一已实现收益的regret、同分预声明简洁顺序选择，避免用公共utility与NN raw-return不同单位的误差判胜。五训练模块、参数、数据划分与teacher源锁不变；5项合成选择检查通过，更新runner和锁已在PRO6000核对，仍未训练。新comparison锁SHA `1da99ce55032c29d672e236c5ae1d52a02a53de4bfb29b8c43d6b28c133bedd0`。原审查/预放置收据是历史观察；本次修改的前后hash和原因见 `results/structured_student_dataset_20261004/ROOT_MODEL_SELECTION_AMENDMENT.json`、`ROOT_SELECTION_PRESTAGE_RECEIPT.json`。

## 完整学生策略回放已开始（06:40 JST）

NumPy公共候选选择器已实际实现，支持六方法、正确替换sent action/pending prediction并按全部真实反馈重新规划。32项合成集成检查和22项harness argv守卫通过，五学生与20个native READY文件保持字节一致。root已在Rhodes1空闲16/17物理核启动L3 native_control完整官方parity，PID1467968和own-label容器已观察；2CPU/2GiB/900秒，无NN额外计算、无truth或prefix mount。候选参数首轮threshold0，待真实六方法验证选择后再跑；source/动作/score components/summary/diagnostics及退出状态全部核验，未把工具检查当真实提分。源码与收据见 `research/student_policy_agent.py`、`results/student_policy_replay_20261004/`。


## 真正续局教师与普通 NN 的实际结果（07:15 JST）

Rhodes1 批次已经结束：315 条完整续局、64 个预声明状态组，全部原始 gate 通过，0 失败，用时 7408.86 秒。锁定的数据准备器与 root 复核接受全部 48 个 fit/validation 状态（L1/L2 各16训练，L3 16验证），无筛除；正负、tie、候选缺失完整保留。L4 16组仍封存，没有运输给 GPU 或用于学习/救参。315份完整原始档案及6份原始JSON（690,697,240字节）已完成单通道运输，全部大小/SHA匹配。5040个tar成员已流式核验与凭据扫描，不解码L4标签；索引和receipt见 `results/policy_iteration_20261004/bulk_terminal_archive/`。

固定比较实际在 RTX PRO6000 CUDA 上完成，86.741秒；DeepSets 6598参数、普通flat NN 6507参数，未改变五模块/参数/源锁。下表是 **16个L3状态分别选择候选后的完整续局teacher差值均值**，不是一个完整赛季策略的总分或增益：

|方法|平均teacher增益|平均teacher regret|
|---|---:|---:|
|原native|0|6.174745|
|公共gain/second|0|6.174745|
|公共粗终局单步值|−15.501769|21.676514|
|pair ridge|−6.534911|12.709656|
|结构化NN|−4.182847|10.357592|
|普通flat NN|−0.292876|6.467621|

预声明规则选中 **native_control**，这些拟合权重不进入完整策略测试/生产。32训练状态、五动作家族、单世界相关反事实不支持否定NN族或任何全局最高分结论。下一轮学习应改变数据覆盖、目标竞争/请求成员表示、学习目标或候选生成机制；重复同数据增大模型/步数或用L4救参没有新证据。数据、GPU作业、模型权重和root审查已保存于 `results/structured_student_dataset_20261004/actual/`。

完整NumPy策略接口的native对照已完成：受限Linux L3 **6004.504542**，1141动作、全部分项与READY逐项相同，454.603秒，无错误/干预。这仅证明新接口对照正确，不能称NN提分。来源 `results/student_policy_replay_20261004/control_gate_result.json`。

## 新无上下文末动作机制（完整测试进行中）

新代理独立推导：在已经选定、将结束赛季的最后动作之前，使用尚未耗尽的免费误报额度，冻结原动作并跳过报告引起的策略belief重置。真正修复可增加科学分及报告奖励；误报无需模拟时间且没有未来额度机会成本。Jain可能有负边际，需用公开score推导的factor区间逐项约束，不能仅凭“免费”断言不降分。

L3在源/选择冻结后，官方局部末动作packet检验条件增益 **+104.403893**；它不是完整策略结果。首次完整运行初始化0.399秒即失败，wrapper误将官方targets.columns/rows表视为list，0决策。原失败实现和日志保留，正在仅修正公开输入schema后以真实初始化/反馈检查、独立新输出重跑。不得将失败的agent_error罚分当算法性能，也不得把局部packet分替代整季门检。源码与证据见 `results/cold_policy_breakthrough_20261004/`。


### 当前独立探索与完整回放（07:27 JST）

修复后的末动作策略在Rhodes1已实际启动一次新L3，PID1575700，`repaired_L3`独立输出；四项运行来源冻结，真实公开初始化+两反馈的三个JSONL动作与READY完全一致。仍须等待完整结束，暂不宣称+104.403893为整季收益。

新 `cold_population_search` 以 `fork_turns="none"` 实际启动：独立读正式源码后研究跨曝光 `(时刻,fiber)→target` 稀疏图的联合指派，尝试用增广路径/流处理Hall资源争用；不是已有预约时间块方案。化简适用条件、science/required不同witness、REQ gate与loss仍须显式验证，原型尚未完成。

实际L1/L2训练诊断已见明显卡间差异：127非control分支中正56/负69/tie2；L1正49负14，L2正7负55/tie2。正样本数量并非主要不足；独立世界/场景覆盖和行为条件偏移更值得处理。诊断尚未作为验证提分或新模型结果。


### 末动作策略完整L3实际通过（07:30 JST）

修复后的2CPU/2GiB/900秒官方完整L3 **6004.504542→6108.908435（+104.403893）**，accounted454.047秒，42项门检全部通过。report+100、science+4.375265、Jain改善+0.028629，required/REQ不变。移除唯一新增终局report后原1141个动作逐项相同，完整prefix、frozen尾动作、observe rank、旧loss和其他messages都同reference；仅public输入，无truth挂载。`results/cold_policy_breakthrough_20261004/complete_L3/`已保留全部真实输出并核对gate列出的SHA。这个本地真实改善不能称正式alpha–delta均分提升。当前wrapper/参数冻结，剩余L1/L2/L4一次/卡的独立回放工具正在准备，不重复control，不修改L3已锁工具。


### 剩余门检与新的无上下文方向（07:44 JST）

同一末动作wrapper/参数冻结，L1/L2/L4已于2026-10-03 22:41:57 UTC在Rhodes1各启动一次2CPU/2GiB/900秒完整intervention：PID1633392/1633393/1633394，输出`terminal_report_20261004/remaining_L1|L2|L4`，物理核20,21/22,23/16,17。三卡原READY source及自然控制通过receipt的actions/score字节相同，原历史gate只因Mac旧期待分不符标false，原记录不改写。没有重复control或L3；最新检查三个owned容器仍运行。

新无context跨曝光增广匹配已收束：8个L1/L2公开nominal条件微域27.78秒；相对同图逐曝光greedy三个区间science/完整条件净增0.140095/0.024293/0.229600，一处因Jain净减0.816150；8个起点首动作均未变。100图穷举与官方完整条件结算复算一致。不追加整季/GPU；范围仅为固定强时序的joint assignment，不能否定time/field或闭环遗传策略。来源`results/cold_population_search_20261004/`。

新的`cold_closed_loop_evolution`又以fork_turns="none"实际启动，先独立读正式源码，研究群体方法对闭环构造策略/结构变量的搜索；独立判断后才查portfolio。本轮尚无策略或得分结果。


### 对正式赛信息结构的重新校正（07:50 JST）

用户指出静态先知题和正式赛不同。按2026-10-03核对的官方2.0规则，正式A–D仅公开目录/日历/站点/仪器/评分，未来真实天气、未来预报与事件故障逐轮提供，最终E–H未见；练习α–δ文案说全公开，但正常下载仍只有六公开文件。离线回放执行机制不等于参赛者全信息，当前模型应按公开历史上的belief/条件分布闭环策略建立。静态先知搜索可作为本地条件oracle和训练来源，不应成为隐藏卡可执行策略的假设。传统精确几何/匹配仍可用于已知子问题；不确定部分需期望/风险模型、滚动情景规划和跨独立world学习。

本地L3 6108.908435与线上α–δ榜首四卡均分不可相减；此前线上同格式记录6735.0925025与榜首约7580.7075也仅是10月3日页面快照，当前榜单未确认。这次web规则页不可访问，Chrome CUA getTab仍30秒fetch失败，没有伪称本次重新读取到页面。

算力分工：Rhodes1的315完整赛季是CPU标签生成与官方受限验证，普通NN参数拟合已实际在PRO6000 CUDA完成86.741秒。不要把CPU rollout任务称NN训练，不把GPU可用直接等同任意Python官方workflow可获得GPU加速。


### 策略偏差的重新审查与真实强对照（2026-10-04 08:19 JST）

原生Chrome实际刷新δ榜单至2026-10-03 22:55:42 UTC：Pleiades第5/53，总6423.09、science6523.83、8917目标；CCB总7411.98、science7263.27、8515目标。该卡总差988.89、science差739.44。当前其他三卡未重新刷新，不能称四卡最新排名；Mac随后锁定，已请求用户手动解锁。当前快照保存在`results/leaderboard_science_audit_20261004/`。

三项独立审查改变下一步重点：

1. 实际RequestCache四卡来源/SHA与官方已发生轨迹复算通过。α/β触900秒，仅缺第38夜最后18543/18633秒，公开可用夜时间已推进98.3544%/98.2718%，没有未开始的整夜。γ/δ完整，因此超时不能独自解释δ科学差。δ有效加权覆盖93.45%，已覆盖的加权best factor约0.69054；代数1.2∑weight缺口主要是不饱和，而非program。25个required missing均QSO；14个已有hit的目标，在各自历史最好实际quality下即3600秒仍不达0.5，另外11个无hit。这是需要更好质量窗口的证据，不证明其全局不可行。δREQ1曾完成6/6，后loss撤销两条唯一witness成4/6；其100分请求回滚不等于100分science损失。来源`research/cold_science_trace_audit_20261004.md`及对应results，34项审计通过。
2. 确认两个模型误差：terrain clear概率先乘Q再cap/best，与先结算再取期望不同；真实δ前220曝高估合计仅0.157836，不能解释739差。冻结曝光起点Moon/airmass会错误分类program；真实δ observe46、785秒的固定assignment公开模型从BRIGHT换为DARK，已发生8条跨档反馈均显示原BRIGHT失配。它支持有限候选按曝光积分重评分，尚不是季末实测增益。历史best/factor分账与归一化未发现错误；783个官方点值比较一致。来源`research/cold_science_model_audit_20261004.md`。
3. 原native READY是BasePolicy+CandidateGeometryPlanner，未接线上最佳RequestCache的Terrain反馈及请求deadline DP/缓存。此前native对BasePolicy/CPUPhase的提升不能自动作为线上最佳完整策略升级。现在从实际上传29-file ZIP重建control；新35-file组合保留原27文件字节/原参数/terrain/request DP/cache，仅替换科学baseline算子、更新run与manifest并添加6文件。composition通过first-decision JSONL及120秒请求边界重调合同，实际candidate未喂任何旧分叉动作的反馈。来源`results/request_geometry_integration_20261004/`和`research/cold_runtime_budget_audit_20261004.md`。线上γ/δ REQ DP solve仅1.37/0.98秒，baseline与建列才是计算主项；公开nominal短profile的native均值快15.4%而p95更慢，不当作完整季节加速。

root实际启动四条受限完整回放：2026-10-03 23:19:23 UTC，Rhodes1 PID1734265，每条2CPU/2GiB/900秒，L1/L2的实际RequestCache control与native组合各一条，物理核16–23；独立目录和唯一owned容器、public actor挂载，host官方模拟器只用于评分。source及harness已冻结，尚无结果，没有提交线上。

新无context `cold_quality_window_control` 已启动，独立研究目标best-score/max-factor状态DP、未来质量窗口、时间/fiber容量影子价与精确几何内层。目的在于改变整季机会成本，不能靠延长当前QSO曝光或调urgency常数替代。允许PRO6000批量Bellman/几何/条件world计算，须先明确状态与算子；GPU拟合的旧32训练状态教师不足以否定普通NN路线。

末动作wrapper其余三卡已实际结束：L1/L2/L4增益均0；L3 +104.403893，固定四卡mean6291.11739575→6317.218369（+26.10097325），所有gates真，全部原始输出已本地核对SHA。没有平台alpha–delta增益。来源`results/cold_policy_breakthrough_20261004/FOUR_CARD_ACTUAL_RESULT.json`。

新的并发分组闭环GA原型已停止：修正版8条人工微域平均仅+0.01488825，含负例，不扩大此版全季；真实未来机会和强生产对照仍是准入条件。全部正负/失败与实现保留，不能称否定遗传算法族。


### 真实最强组合已拒绝；整季有限模型实际上GPU（2026-10-04 08:49 JST）

四条RequestCache/native完整对照全部结束、survey_complete、2CPU/2GiB/900秒协议通过；本地再次核对每个gate中的全部原始输出SHA及锁定源。原真实RequestCache控制L1 **6267.103017**、L2 **6723.359693**；加native组合L1 **6264.719768（−2.383249）**、L2 **6667.983239（−55.376454）**，两卡平均 **−28.8798515**。science分别−2.341429/−54.870456，其余主要Jain变化，required/REQ/report不变。accounted control610.105/707.024秒、组合594.103/722.224秒。原控制完整结束，不能归因于超时。此composition停止，不用L3/L4救参或浪费线上额度；它不证明native/geometry族无用。完整原始输出、精确分项和拒绝决定在`results/request_geometry_integration_20261004/seasons/`与`ROOT_ACTUAL_RESULT.json`。此前08:19的“仍运行”记录现已终结。

新目标quality-window控制完成独立数学报告、全δ公开目录原型、CPU冻结reference；参见`research/cold_quality_window_control_20261004.md`。状态为公开science best加raw完成概率π，先合并相同six-decimal公开score再更新π；完整belief关联、共享weather、Jain/REQ/loss仍未被消去。有限bilinear随机projection MDP具有凸fiber秒价格dual，不是原题上界。每target独立best-start/一夜一服务是明显机会近似；旧三步固定步长price过冲（38279→49912→55870）全部保留，不能采用。不同duration候选必须补全全目标时间机会损失与16μ容量消耗，不能仅用sum tail_delta/d；初期只准固定baseline duration的物理field/assignment分叉。真正准入控制改为上面获胜的原29-file RequestCache，report §8在组合结果出前写成“组合进行中”，该句由本记录更新。

CUDA后端已实际在RTX PRO6000执行：首次job在Windows RSS计量HANDLE类型报OverflowError，128-target计算已执行，但没有记录gate/full结论；仅修计量后，同冻结输入新job通过。128targets×38夜、非零当前best/π、非零price的B25/P9门检policy差0、value最大差1.42e−14、demand最大差4.00e−11；全δ9400targets B25/P9零价backward1.8307秒+forward.6348秒，CUDA峰453442560B，采样功耗峰205.33W。F=38273.3092、demand37.6807M fiber秒、容量16.9776M；这是有限近似模型的数值，不是正式得分或较CPU B13/P5的改善。真实GPU计算资源并非此算子的瓶颈。接下来同冻结模型做uniform μ凸二分与38维Kelley cuts、明确数值误差与安全价格盒，禁止改分布/隐藏未来/大步长救参。实际价格job WSL PID3224489，独立Windows目录`C:/Users/hedge/gosim-quality-window-20261004`，backendSHA`db8c36ff5feab172861c0118d168f918a9b4c84745950a6d19ef068675d90506`；只在真实终局策略控制通过后才能谈提分。

另独立代理将末动作report适配真实29-file RequestCache，原native四卡+26.10097325仅是不同包的旧结果，禁止迁移为本策略收益。先官方终局时点/公开quota/feedback合同证明与公开prefix action parity；当前未开新整季或提交。


### CUDA资源价格实际终结；共同曝光控制启动（2026-10-04 08:59 JST）

上条所述价格任务已真实完成123.501秒、58新GPU oracle。统一最优μ=.000162101411819458，finite F37730.40414090836；总需求16,977,711.37，略高于容量111.37fiber秒，上端16,977,364.33。最佳统一价仍16窗过载，peak7.60736×。32次Kelley没改善uniform最佳；含数值cut余量LP lower33123.17912734773/gap4607.225432013722，未收敛且无严格floating-point下界证书。交叉cut、梯度单位和统一需求非增经独立审查及现有日志核验通过，但不变为实际全题最优或正式分数。价格阶段Torch峰453MB/RSS1.338GB，整卡242次采样最高229.09W。PRO6000任务全部结束回闲置。冻结backend与去重manifest/原计量失败/两完整数值结果和59oracle原日志在`results/quality_window_cuda_20261004/`。已保存的三步过冲不能被新uniform结果替代为成功部署。暂不增加32Kelley预算、改PMF、重开相同模型。

新`cold_common_exposure_control`以fork_turns="none"实际开始，先读正式源后抽象再查重：用真正共享16fiber曝光弧、nonoverlap时间path与target score-layer coverage MILP研究中早季窗口竞争。固定L1/L2第8/18夜四个无活动REQ公开prefix，4h公共窗口、包含原强action时长及300/900/1800秒，按first arc分别解共同suffix及同duration空曝光suffix，计算全目录时间机会损失；短预算8秒HiGHS/次。模型仍需要公开belief和完整曝光天文积分、不看未来真实天气，固定.9/1/1.1敏感性只作机制稳定性，不是校准概率。此刻尚无微结果/完整策略分。若原完整snapshot字段不可恢复须明确重建state，不能假称重现历史action。末动作RequestCache适配另在进行，尚无新完整回放。


### 最强RequestCache末动作实际提分与策略重新审视（2026-10-04 09:35 JST）

最终适配ZIP保留29原成员，27原源码字节不变；全包31成员SHA fa62269215a7f7d5d5472caa38fb495553d907cd79955e0b4492599b10bc621c。初版terminal判断忽略夜末裁剪，已在首次完整季节前修复，失败审计保留。原RequestCache与适配包的实际L3双对照于00:09:21 UTC启动，PID1854611已结束，两条2CPU/2GiB/900秒完整survey_complete：6141.421958→6242.640810（+101.218852），report +100、science +1.208811、Jain +.010042、required/REQ不变。原全部动作在移除唯一终局report后逐项相同，所有旧CSV决策字段/observe rank/data-loss/messages相同，报告不推进模拟时间，实际gain满足public guard条件下界99.275059；完整原始输出和root复核见 results/request_terminal_pair_20261004/ROOT_ACTUAL_RESULT.json。actual actor请求1169次、CSV/committed动作1745条的差是wait-until自动展开，首次root审查误用actor索引删CSV已修，保留ROOT_REVIEW_FAILURE_1，无需重跑季节。这是原最强包本地L3改善，不是线上均分变化。

同一冻结包剩余检查已启动：2026-10-04 00:28:09 UTC，Rhodes1 PID1900820，terminal L1/L2、control L4和terminal L4四条，每条2CPU/2GiB/900秒；L1/L2使用前次同源真实control，不重跑。记录 remaining_job.json/remaining_launch.log，输出同目录seasons各卡。L4仅作已锁策略的实际完整验证，不打开此前封存的teacher标签，不据L4救参。

最新能核实的线上α/δ均为第5/53。2026-10-04 00:06:17/00:05:52 UTC：α ours science7149.12对CCB7788.10差638.98，δ6523.83对7263.27差739.44；ours目标覆盖均更多。β/γ本次未刷新；Mac重新锁定，原手动解锁问题仍pending。该分差支持研究质量/资源分配，不能由榜单唯一识别对手策略。

策略判断需要数学约束：对于单target已有best B和完整曝光价值A，u(d)=(A·min(kd,1)−B)+；在线性正区间u(d)/d=A k−B/d，导数B/d²≥0。因此不能笼统宣称gain/d必偏短。新的cold_strategy_rebuild以fork_turns=none从官方source重建，研究science anchor额外min(k·900)筛选偏差，以及来自真实共享曝光continuation path的时间机会价，保留control/debias/surplus对照。λ若等于当前max rate则只是原quotient的等价变换，不算新路线。当前已做可运行public入口，L1第8夜实际host短续局尚待结果，不能称已提分。

另发现具有百级损失规模的持续故障控制漏洞：原Policy._repair遇到任何earthquake公告便禁止report，infer-efficiency witness又遇到任意notice便停止积累。当前原强本地L1修复延迟约八天，L3整季未修直到本次terminal intervention。root仅作为事后host诊断读取L1/L2/L3既有truth/已发生factor，保持原hit/有效失效ledger/program不变，对完全位于故障未修区间的曝光恢复efficiency，跨边界曝不改变。科学分损失规模约172.2998/3.5782/438.1723，六位舍入保守区间分别[172.2924,172.3074]/[3.5699,3.5865]/[438.1642,438.1806]。这是固定轨迹条件科学潜力，不是可执行public策略收益/完整net增益；没有读取封存L4。脚本与host证据在 results/fault_timing_diagnostic_20261004/，不得将truth故障时间或参数交给actor。

故障路线cold_persistent_fault_control以fork_turns=none独立从source开始，只获上述损失规模，不读取host诊断时间/参数。研究公开跨曝质量变化、C/E不可识别性、有限免费quota的动态机会价值和false报告后的belief保持；正确修复后继续正常反馈重规划。不能重复曾被拒绝的无条件花光quota/弱基线报修方式。目标是可运行原最强闭环候选及真实完整对照。

已完成的cold_calendar_boundary独立审计找到了真正新动作域：pre-night起曝可提前固定光纤天球方向，明确合成例science .750480胜任意night-inside排程上界.389706；52秒tail合成条件+.745417，但非terminal新增observe可改变loss rank或Jain，不能无条件采用。18条官方短loop、全源/输出manifest保存。新calendar_binding_policy实施研究暂缓，优先资源给持续故障和整季科学决策偏差；其未完成状态保留，不称策略已部署。


#### 上述共同曝光与初次新策略的实际短局结果

共同曝光研究已完成四个固定状态：0/4符合预声明overall winner三档稳定gate，108个有限solve中25optimal，手工fixed-path Hungarian 43次优于MILP当前incumbent；枚举12/官方synthetic72/geometry1617arc+20357assignment通过。手工匹配median16ms但整体build24.9–38秒，不是生产可用controller；不扩大预算。L1night18的稳定pair反转保留作时间机会机制证据，不能称整季提升。报告/audit_summary及全部正负/noincumbent在 results/cold_common_exposure_control_20261004/。

cold_strategy_rebuild初版短harness因官方清理host env，两分支均误跑surplus整季6172.484006，已判FAILED_ENV_SCRUB并保留，不能算control差。修显式participant env后的真实第8夜短对照：L1 surplus−76.942429（science−26.691654、多1required missing），L2−60.782648（science−10.201892、多1missing），停止surplus、不扫λ救参。去science anchor额外min(k900)的debias：L1 +22.055487（science+21.793800、required同），L2−6.095593（science−5.842259、required同），均是短截止完整评分而不是整季收益。单卡负不等于整体期望负；root允许一次同冻结debias正常闭环L1/L2整季判断，不改历史gate，不把短局平均+7.979947当部署均分。

新cold_predictive_world_model以fork_turns=none从官方source独立建立C/E多峰共享天气路径 posterior，先逐slot积分q_exp/q_band并计算cap/program/best，再平均；用公开six-decimal score的band/饱和likelihood更新。若官方生成过程可复用可训练普通NN或批量PF在PRO6000；它不是旧32状态窄教师拟合或同16先验场景bank，要求实际decision regret/官方strong闭环评价。此刻尚无训练/部署/得分结果。


### 冻结候选实际整季批次已开始（2026-10-04 09:49 JST）

RequestCache terminal其余卡已完整结束且源/output/动作插入/旧loss/所有components逐项核验：L1/L2/L4各0，L3 +101.218852；同四卡local mean6303.0384205→6328.3431335（+25.304713），非线上均分。原PID1900820已结束，不重复季节。总表 ROOT_FOUR_CARD_RESULT.json，全部raw在request_terminal_pair_20261004/seasons。

真正五条新的强闭环候选于2026-10-04 00:48:41.580UTC在Rhodes1启动PID1950907，每条2CPU/2GiB/900s，实际owned容器：fault v1 L1/L2/L3（16–21核）和debias L1/L2（22–23、14–15核）。fault原始ZIP SHA bd461164340f4adf490ace91003d49f7205a6ea631f712e9767f3527ec9549ba；debias cb5e8c423d40c85394ac2ab6e50b65005bc26a95cb3a4014b141d2a82884aee1。actor只挂自身代码+NumPy，host原卡truth评分；没有forcedprefix或STOP、无新truth进入actor。现有同源原29file control L1/L2/L3引用完整来源，未重跑。新通用harness run_strong_candidates.py SHA481612511c05a68d07cf5112bf281944cd0a644f71975605091aec08981d00d3，lock963a5c632b096e48dea80e85ae3d095c8e97aebae766542410fa8ed84ad2df4f，job/cases/source lock及待完成原始输出在results/strategy_reassessment_actual_20261004。

fault v1独立冻结后完整public forecast遮蔽修正了分析记录的最早would-fire：L1 rank902；L2无；L3 rank961。早期未遮forecast的L3 rank790不是最终ZIP规则，不改ZIP、不参考实际fault日期。v2单列false后背景level+新下降的条件value控制，ZIP 2a2ab533099c36c32d25a46d532bac8f8c27cbb39b1194c73928d8a4e8ea6412，当前未开整季；其Normal change/prior/value外推未经实际标定，不能将参数choice当保证。v1五任务实际结果需回收完整组件/首次真实触发/协议后再判断，不能把host科学潜力438当candidate收益。

预测world模型已生成192独立官方seed，train44579/val11719/test10936历史；普通MLP1306→128→128→196输出4component×4slot joint(logC,logZ)+16closure模式。初稿synthetic16fiber独立H造成band过度泄漏，在验标前停止own进程，改同field共同H±2%重新冻结；首GPU epoch0因NumPy int64日志JSON失败，未选checkpoint/test，仅修日志重跑同data/seed/config，失败保留。质量模型部署首版保留原强field/duration/REQ/rate域，先同动作重评分program/expected science；训练有限synthetic比较中的λ不可直接部署。当前没有模型整季得分结论。

### 持续故障策略获得完整实测改善（2026-10-04 10:20 JST）

原五条受限闭环批次 PID1950907 已结束；`five_case_complete.json`保留5/5终态，各卡全部raw SHA已经本地复核。原29-file完整同源control未重复运行，actor没有truth挂载。fault v1仍为原冻结ZIP `bd461164340f4adf490ace91003d49f7205a6ea631f712e9767f3527ec9549ba`，没有按这次结果改阈值。

| 实际本地卡 | 原强策略 | 持续故障 v1 | 总差 | science差 | report差 |
|---|---:|---:|---:|---:|---:|
| L1 | 6267.103017 | 6272.923354 | +5.820337 | +5.884817 | 0 |
| L2 | 6723.359693 | 6723.359693 | 0 | 0 | 0 |
| L3 | 6141.421958 | 6553.045588 | +411.623630 | +311.584980 | +100 |

三卡均`survey_complete`，实际accounted623.466/721.531/713.941秒；required/REQ分不变，L3 Jain另改善.038650。L1/L3第一个动作分歧确为新report，此前所有公开动作前缀相同，真实官方report结果正确、旧loss计划不变；L2无guard事件，全部动作及组件相同。根复核`ROOT_FAULT_THREE_CARD_RESULT.json`全部门检通过。这是可执行公开控制的真实整季改善，不再只是host故障科学潜力；仍不是线上提分或正式隐藏卡保证。相对先前terminal L3 6242.640810，此版实际再高310.404778。

同ZIP的一次正常L4验证于2026-10-04 01:08:36.239965UTC启动，PID1999548，2CPU/2GiB/900秒，核16,17。`remaining_L4_job.json`/`remaining_fault_L4_cases.json`锁来源；引用已有strong control6080.269014，不重跑control、不读封存L4 teacher、不据L4救参。实际01:17UTC仍为owned运行容器，待完整输出。

debias当前实现完整L1 6010.923915、L2 5185.892596，均900秒`global_wallclock_expired`，protocol_passed=false；这是预算下的实际失败，不能称完整赛季科学改善，当前包不部署。新forknone `cold_sparse_science_runtime`对原强和debias的冻结工作负载作profile；12个状态9,776细候选与155,724phase候选值/动作一致。`np.maximum.at`仅约8%，简单sorted reduceat反而慢，因此在保持候选域/原评分/参数/最终tie的前提下研究native融合中间score矩阵与fiber max，而不是扩大搜索池或更改预算。尚无可上线加速包。

质量NN已真实完成PRO6000训练85.9104秒、CUDA峰386,113,024B。最终改正后的192-world manifest为train45022/val11514/test11001；上段44579/11719/10936为早期数据计数，不是最终产物。4component full covariance ordinaryMLP的独立1024候选regret .1235935265，比同NN先均值.1333836822及人工point.1878051302低；不是生产整季分。原33-file包`ae8b963c32770975a50aa368e204914a7057f7ea3fe121ec46b1116ede49176c`，原27source逐字不变，模型只改支持域中的program。public强前缀L1/L2/L3实际改动1/3/0次，scope很窄。报告、算子4800对照、NumPy导出、192-world数据及失败日志、模型/ZIP/源manifest全部保存；根`ROOT_ARTIFACT_RECEIPT.json`核对产物及全部源SHA通过，仍没有该策略的完整得分证据。

另一个forknone `cold_report_value_model`建立公共fault posterior+report quota有限Bellman：真正report−wait价值是到下一次证据的science损失、奖励延迟与quota/信息价值之差，不是把全部剩余修复收益都视作立即report相对wait的收益。独立官方世界train/cal/val/test与普通NN在PRO6000，当前验证world已完成，test/真实strong组合包尚待完成；不将fixedsensor子题收益称整季改善。新的forknone `cold_calendar_binding_implementation`接续已完成calendar审计，研究pre-night binding/clip动作域与rank/loss后效的安全控制，尚未交付生产包。

#### 同冻结L4完整结果与四卡确认（10:26 JST）

PID1999548已正常结束，L4 `survey_complete`、accounted744.222秒：6080.269014→7084.531835（+1004.262821），science +1004.051719，Jain +.211102；report/required/REQ三个组件都完全不变。旧control在12月29日才正确报修，新公共持续证据于12月10日01:03:49UTC、observe rank571正确报修；这两个时间仅为已经发生的结果审计，actor没有日期触发。第一个动作分歧为新report，此前621个actor动作完全一致；旧loss `[191,216]`及370条实际失效不变。这个冻结L4没有用于训练、阈值选择或teacher输入。

`review_actual_results.py`复核四卡完整协议、raw/actor源SHA、原27source保留、同场景hash、旧loss/REQ/required、首次插入report和官方正确结果、组件差之和，全通过。`ROOT_FAULT_FOUR_CARD_RESULT.json`给出本地同四卡mean6303.0384205→6658.4651175（+355.4266970）。这是新最佳完整本地四卡方案；没有计算正式alpha–delta增益。10:27JST正常CUA访问Chrome仍返回Mac locked，原manual unlock请求待处理，不能绕过或声称线上已提交。

report quota DP的第一次独立test后发现稀疏kernel回退可能使public correct_count下降（违反状态合同）；原test/旧实现保留并排除部署结论。修复必须保持wait/false计数不变、true严格+1，先穷举小状态/官方分支门检，冻结模型calibration，不用test调参。新test域若需要仅预先锁定一次，不能把此前sensor正结果冒充生产强闭环改善。sparse exact加速已在Mac冻结输入逐rate/动作完全相等，约2倍profile速度；Linux生产Py3.12.15/NumPy2.2.6及quota合同门检未结束，不称可部署。优先交原strong+fault v1的同域算术加速组合，另列debias变域候选，root负责完整900秒验证。

### 精确算术加速与新的受限完整回放（10:38 JST）

cold_sparse_science_runtime已完成冻结Linux门检。不是旧native arrangement或改变candidate池：保留原geometry/classification/duration/最终NumPy sum/REQ quota/tie，仅融合原score/value中间矩阵和fiber maxima。Py3.12.15、NumPy2.2.6、2CPU/2GiB固定镜像公平交错12输入：strong .502823→.229765秒（2.1884倍），debias .292330→.158435秒（1.8451倍），24组动作全部相等；1000随机quota案例/5596719值/2000coarse batches相等。strong/fault/debias×L1/L2共6组官方五decision公开response配对全相同。Linux.so仅libc，运行时无compiler/network；`-ffp-contract=off`。sorted替换更慢、最初stride bug和直接benchmark误用旧.22秒timer三失败全部保留，正常actor包未因timer失败改变。

root新source-locked4任务于2026-10-04 01:36:56.904900UTC启动Rhodes1 PID2072634，remote/local `results/sparse_fault_actual_20261004/`：fault_fast L1/L2核20,21/22,23；debias_fast L1/L2核14,15/12,13。每卡仍2CPU/2GiB/900，正常完整闭环，无forcedprefix/STOP，原control不重跑。fault ZIP `5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`保留原fault v1全部29 source/config，仅改2 run manifests；debias ZIP `0ed97ca010612d7bdf6063d9f07cd240fe021e6a45348dfb4d303ad5ed76a359`。root preflight/actual job、原runtime5source hash、harness4816125、source lock `ef0d31396894ebb574aefffa91f3b65fde3cbcfba573f04f56e905706257ac3c`、cases `c355ea06fdd50d1d2871a822d2a1c6d5939605dd050b92357ceccc5ad089f1fd`保存。fault_fast对照已经完整的faultv1，debias_fast对照原29file；实际整季speed/score尚未回收，不能用微benchmark速度自动声称线上gain。

report posterior+quotaDP v2也已冻结，但拒绝当前域的生产整季。SOURCE_LOCK_V2在01:29:48UTC先锁770000–770031新test：126两epoch穷举树最大误差2.84e−14，3240 transition全部correct_count合同通过，官方同future32 score分支误差0，false frozen action/belief与true正常replan及quota合同通过。新test finite protectedsensor regret DP35.839209 vs同posterior p>.9免费293.520539、平均差257.681329，18赢0输；仍不是strong生产收益。真正public轨迹支持审计L1/L2仅41/46 sensor、0 queries，L3 64 sensor/41 queries但maxp3.97e−5，无一wouldfire。因此不跑无信息的三整季，不宽gate救参。旧缺陷test/全部失败保留，report数据290035845B以64MiB×5片字节hash保存在`dataset_backup`以满足Git单文件限制。原source/model/两ZIP/源SHA由根复核通过。

该代理转独立 `cold_report_sparse_domain_20261004/`：先4独立world pilot，用L1/L2公共catalog/calendar/field/time/assignment仅作采样设计、缓存真实120秒Moon/airmass/alt/az/fiber几何，再在新官方天气/quake/fault/forecast worlds结算各自score。报告后后续score必须按该world故障修复分支重算；新history可跨field/方向/slot稀疏、60–3600秒/30–85°，未支持状态fallback原faultv1。计划训练64/cal8/val8/test16 seed在训练前锁，不调用旧290MB数据、旧teacher或L4；固定公开行为设计明确不是counterfactual strong完整rollout。CPU估算/官方算子合同后再PRO6000普通NN，尚无训练/得分结果。

### 精确加速完成整季证明，科学变域候选收束（11:00 JST）

PID2072634已4/4完整结束、全部raw/source/同场景/协议hash在本地核验。fault_fast L1 6272.923354、L2 6723.359693与原faultv1完全同分；不止总分，actor actions、完整observations和全部官方messages均字节相同。accounted623.466→345.193、721.531→405.599秒，真实整季1.8061/1.7789倍加速，减少44.63%/43.79%。固定输入算子2.19倍不能替代这个完整workflow速度，但现在有真实强闭环证据。`ROOT_FAULT_FAST_TWO_CARD_RESULT.json`全部9类门检通过。该加速与faultv1组合成为当前优先提交候选，线上仍尚未操作。

debias_fast现在也有真正完整结果，而不是前次900秒截断：L1 6267.103017→6229.693628（−37.409389）、L2 6723.359693→6755.858138（+32.498445），accounted528.678/654.466；REQ/required/report组件不变，science−37.500026/+32.131557。两卡均值−2.455472，没有当前冻结包的平均提升证据，停止当前变域候选，不据L3/L4救参；它不能否定其他science机会模型。`ROOT_FOUR_CARD_RESULT.json`保存完整正负和scope，引用原strong control，没重跑控制。

private GitHub已确认`6dceb0d6cbb740a4d2538676981af6f0b7c7a49e`包含所有前轮原始结果、两新模型/失败及大dataset精确分片；byte校验后已删冗余290MB原NPZ，五片仍可按manifest原顺序恢复。新domain pilot原先只核固定hit score算子，发现不能冒称新stress geometry；已保留并补全geometry审计。最终pilot新stress实际assigned→hit/min-alt 56608案例、9368旧hit丢失/5旧miss成为hit，正式2846score误差0、244report/wait分支。actor只按官方公开actual-hit target_id/score列表接纳history，不取隐藏offset算出的actual H作特征。64/8/8 train/cal/val 64625/8075/8082 rows、81298560B、36.15秒生成，新test未生成；PRO6000独立目录开始1568→128→128→1新NN，未有生产得分。

新的forknone `cold_public_rng_identifiability`已独立读官方代码，24源SHA与公开GitHub e01939d0一致。有限1024-domain合成12world master blind恢复全中、4域外正确abstain；同master可复现未来多流，不代表实际同master路径。另用官方build_spec独立weather seeds，构造两world相同catalog/public初始化及9次过去反馈（7正/2共同关闭），下一动作0 vs .038914，证明public catalog/past prefix一般不唯一决定future。实际已存在0..2^32−1公共seed/模型审计，没有受公开证据支持的新小域；不重复0..1023、不读actual truth证明。报告仍须冻结，不视为actor已有future数据。


### 新稀疏公开诊断域完成独立 test（2026-10-04 11:30 JST）

cold_report_sparse_domain 的新1568→128→128→1普通NN真实PRO6000训练16.63秒，selectedepoch3；源/模型/DP于02:15:08UTC锁定，test850000–850015一次完成且所有hash不变。固定public design的16独立world：DPfree mean5298.429271、p90free5014.773878、oracle5467.681328；paired DP−p90 +283.655393(SE104.634663)，11胜1负4平，DP regret169.252056。这是best-only固定动作研究，不是对现有生产faultv1的完整分数收益。研究prior max2fault不属于正式协议保证；actor public correct_count>=2立即fallback原faultv1，不调用NN/DP，原v1可以继续第三次report，微合同通过。

原candidateZIP069c346450412437a96b02d48abe886d4201b7a87dc583c87715b995c42a9823平铺36members、入口python3 -u report_entry.py。root核验SOURCE_LOCK全部hash、ZIP所有成员、report_support与faultv1原persistent_fault_guard逐字相等、新test冻结与count2fallback全通过；ROOT_ARTIFACT_RECEIPT.json记录。数据81,298,560bytes由两40MiBpart按manifest可逆保存，不将public固定轨迹的私有旧score/factor/offset/valid作为训练输入。新world真实指向偏移重新分类assigned→actualhit，而actor只接official actual-hit ID/score与静态公开几何。

原研究包不再修改。独立sparse runtime agent正在自有目录组合冻结native exact算术+新report_entry；原NN/DP/actor/强策略及faultv1source/model必须原样保持，只新增入口和已验证算术安装，先真实protocol及false/true/count2合同。root随后正常2CPU/2GB/900完整L1/L2/L3闭环与已有faultv1比较；不重跑control，不拿test的+283当生产gain，L4留作之后冻结holdout。此时尚未启动新actualfull或平台提交。

最新已完成raw、精确加速四条full、calendar正负/合同与RNG反例/源校验均已privateGit推送并ls-remote确认3727fbbcf1890c62efb0f3250b85e306c63c2d7f。在线仍没有提交新faultv1；Mac locked原手动解锁请求pending。
