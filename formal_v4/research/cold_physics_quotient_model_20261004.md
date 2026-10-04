# 连续物理商与六位分数联合删失似然

2026-10-04。状态：**新小型 stage1 机械原型通过；没有拟合模型、生成训练世界、正式 test、900 秒整季或提交。** 本报告不修改现有 direct195 的 source/model/data/test，也不把它的负验证结果解释成已经证明的模型失败原因。

候选的具体对象是未来目标的连续未截断物理商与 actual band 的条件分布，以及从公开历史 score 保留下来的连续 C/Z 可行区域。已知 flux、weight、cap 和 declared-program multiplier 在解析计算层处理。推荐先在同一有限动作域比较它对科学增量的排序，再决定是否进入完整强策略。这里没有“最高分已达成”的证据。

## 1. 官方来源与读取顺序

先读官方评分、runner、geometry、workflow 与天气生成源码，再读 `ALGORITHM_PORTFOLIO_ZH.md` 和 `SCORE_DISTRIBUTION_STRUCTURE_ZH.md` 查重，最后检查旧 `feedback_model.py`、`belief_clock.py` 和两份 posterior 报告。

实际 scorer/runner/fiber/workflow 位于 `formal_v4/upstream/gosim-observer-examples/runner/challenge/`；该 checkout 实际缺 `v4_weather_simulator.py`。天气源码只读 `results/cold_public_opportunity_cost_20261004/official/challenge/v4_weather_simulator.py`，SHA256 为 `b4675ead09e8cf333c12841ac051786c523394d4fb3cfb0b52397ad75dcc753a`，与 root 官方源码回执一致。没有读取该目录的 world/truth/data。stage1 记录全部六个实际读取 source 的 SHA。

关键接口：`score_target_exposure` 的 quality 是 **cap 前**的 q_exp；band 用 `WeatherTruth.band_quality` 单独计算。actor 的 `last_result.hits` 仅提供 target_id 与六位小数 score；host 的 observations.csv 另有 factor/quality/prog_mult，这些列不是 actor 特征。geometry 只在曝光开始判断一次 hit，随后跟踪固定天球方向；整段最低高度仍须合法。

## 2. 精确预测对象：已知缩放和未知物理分开

记实际裁短后时长为 d，公开几何因子为

```
H_i(t) = lunar_i(t) / normalized_airmass_i(t)^beta
C_s = open_s * transparency_s * sky_s / (seeing_s * q0)
Z_s = C_s * effective_efficiency_s
```

若 effective_efficiency 在槽内改变，可进一步按官方切分 piece 索引 Z，不能强行视为槽常量。directional seeing/transparency/sky/efficiency 的比值、terrain/rocket 强制零项记为 D_i,p。对给定隐藏事件起止/sector 与修复状态，官方 science 中点网格给出

```
I_i = sum_p span_p * H_i(sample_p) * Z_p * D_i,p
Q_i = I_i / d
F_i = min(flux_i * I_i / (f0*T0), 1)
```

band 使用另一套网格：槽边界后每段最多 120 秒，**不含设备效率和 directional multiplier**。science 还按所有重叠 directional-event 起止切分；某个 event 没覆盖目标也能改变中点网格。因此一般不能用同一 Hbar 宣称 Q=E·band_quality 或 Q≤band_quality。

任取只从 initializer、目标、start 和实际 d 算得的正数 Hbar_i，例如公开 band 网格的均值 H，定义

```
R_i = Q_i / Hbar_i
a_i = flux_i * d * Hbar_i / (f0*T0)
F_i = min(a_i * R_i, 1)
S_i = weight_i * m(declared, actual_band_i) * F_i
```

这是代数恒等式。R 把未知事件切点和真实时间加权留在随机量内；Hbar 没有消去隐藏 mesh。若 Hbar=0，单独走零值/不可见边界。

对于固定公开历史、固定未来几何和 start/d，R 与 actual_band 的物理 law 不依赖**未来 query**的 flux、weight、best 或 declared program。历史里的 flux/weight/program 必须保留，因为它们参与解释已测 score。duration 不能完全从输入去掉：d 决定涉及几槽、averaging、closure 和 future hazard；Moon/airmass 的加权形状与 band 阈值也不能完全去掉。真正可消去的是学习 cap、flux/weight 的尺度运算，不能声称整个 law 都与 duration/geometry 无关。

## 3. 正确的单步值与可证明不变量

科学增量为

```
G_i(B) = E[(S_i-B)_+ | public initializer/history]
       = integral_B^(weight_i*m_max) P(S_i>x | public) dx
```

同一条件 law 下，G 关于 B 非增、凸且 1-Lipschitz；B=0 与首次贡献期望一致。固定历史后提高未来 query flux 会提高/保持 G。齐次性是 `G(c*w,c*B)=c*G(w,B)`；固定 B 时不能称 G 对 weight 齐次。对 duration 没有一般齐次或单调 rate 定理。

固定一个 field/d/program、且科学项可加时，对各目标先求 G，再每 fiber 选其中 G 最大的一个目标；期望线性不要求 fiber 间天气独立。不能在每个隐藏场景先挑最佳 assignment 再平均。若 point-offset 未知，正确对象实际是 `E[hit_i*(S_i-B)_+]`；除非证明条件独立，不能把 P(hit) 与 G 简单相乘。本文保留现有公开 pointing/outergeometry 控制作为共同动作域，并将 fresh-world actual hit 用于 host realized 裁决；stage1 的已命中范围不证明未知 offset 的生产合同。

请求阈值、required/Jain、未来回溯失效及信息价值不是单步科学 G。公开 best 来自 rounded score：重建有效 raw-score ledger 时 true best 与取公开 bin 中心的 best 相差≤.500001e−6，对单目标 G 的误差同样≤.500001e−6。resync 移除有效贡献；被 invalidated 的历史测量仍可作过去天气证据。

## 4. 六位分数是区间似然，饱和和 missing 必须分开

公开 y 对 true S 给出 `[max(0,y−.500001e−6), y+.500001e−6]` 的保守半 bin 区间。固定一个可能的 actual-band pattern 后，m 确定：

```
ylo <= w*m*min(a*R,1) <= yhi
```

未饱和时是 R 的窄区间；bin 包含 w*m 时只给 R 的下界；若 ylo>w*m，则该 band pattern 无支持。由于 actual band 未知，score/w 接近1不证明 F=1：另一个倍率下可能是未饱和 F。必须保留可行 pattern 的混合概率。

missing target_id 表示没有 hit，约束 pointing/fiber/最低高度，不能给天气添一条零测量。存在 hit 且 score=0 表示该目标有零/极小 contribution，可由 closure、terrain、directional closure 或 rounding 等解释，不能一律反推全站关闭。stage1 没有 directional latent，因此 mixed zero/positive 暴露明确的零支持并拒绝，不作强行天气拟合。

整次曝光 score 向量是共享隐藏状态下的**联合事件**。在无额外独立读出噪声的官方机制里，同一 hit 复制16次不应把 likelihood 乘16次。可在真实联合 likelihood 中保留每个 target 的确定性 interval constraint；不能把16个同曝目标当成16份独立天气样本来夸大置信度。

## 5. 可执行的传统算法小核：单槽连续 band cells

在 **同一槽、C/E 恒定、无 directional effects、已命中** 的限定中：

```
band_quality_i = C*Hbar_i
Q_i = Z*Hbar_i, Z=C*E
```

每个 target 的 band 只在 `bright_threshold/Hbar_i` 与 `dark_threshold/Hbar_i` 两点变化。将 N 个 hit 的2N个阈值排序，在正 C 轴最多得到2N+1个 cells；每 cell 中全 target 的 multiplier pattern 固定，所有 score constraints 的交集是一个 Z interval。饱和 cell 的 Z upper 可为∞。16个 hit 最多33个 cells，无须穷举3^16个 pattern。

stage1 使用明确 toy prior：C uniform[.02,1.8]、E uniform[.1,1]、closure atom probability .08。这些值**只是 toy prior，不是 initializer 公开常数或任意卡保证**。变换后的联合密度为常数乘 `1/C`，且 E 范围给 `e_min*C<=Z<=e_max*C`。每 cell 的后验质量为

```
integral_Clo^Chi [min(Zhi,e_max*C)-max(Zlo,e_min*C)]_+ / C dC
```

在 endpoint 切换点切分后，积分是线性项与 log 项。query gain 的 z-inner integral 是分段二次/线性；再对 C 解析积分。保留 interval width 因子，避免对六位窄 bin 相减两个近似相等 primitive。prototype 直接用 cell probability mass 计算 G；没有 grid MAP 或训练 classifier。

多槽时，条件于事件 nuisance、open pattern、effective-efficiency piece 与 actual-band pattern，band 是 C 向量的线性半空间，quantized score 是 Z 向量的线性 strips/saturation halfspaces。N=16、五槽的全部 band cell 数不再≤33；二维 endpoint 算法不能原样推广。公开 generator reference 的 E≤1可作明确研究先验；官方 initializer 不公开 quality bounds，不能把任意卡的 `0<=Z<=C` 当协议定理。模型要保留允许范围及 out-of-prior 拒绝收据。

原始 night/slot seeing、transparency、sky 是分别 clipping 的 AR 状态，C=其比值一般不是严格 Markov sufficient statistic。传统动态 filter 若要复用 official transition，应扩到原字段/night_state、closure、fault 与 event nuisance，不能继续把 C/Z 的 scalar AR 称 exact Bayes。

## 6. 普通 NN 可执行下一对象：连续 (R,band) density head

下一拟合候选可采用两层128 ReLU的普通 MLP，joint output 为3个 band 的 R=0 atoms和每 band 4个 positive-lognormal component。共15个 joint probability logits、12个 μ、12个 positive σ，共39标量；它不学习 cap、future flux、weight、B 或 declared program 运算。维度不是本路线的创新，变化在连续未截断标签、joint band/R law、已知物理解析层与 exact score interval 输入。

对于一个 component、`log(R)~Normal(mu,sigma²)`、`M=w*m` 且0≤B<M，令 r0=B/(M*a)、r1=1/a：

```
G = M*a*E[R * 1(r0<R<r1)]
    -B*P(r0<R<r1) +(M-B)*P(R>=r1)
```

截断 lognormal first moment和probability用Normal CDF直接算；再按 joint probability 混合。R=0 atoms贡献0。`quotient_mixture.py` 已提供该无需采样的 gain kernel；没有 NN、权重或fit。普通 lognormal mixture仍是近似，不自动满足真实多槽状态/公告的所有支持约束，也不保证尾部、band transition或NN校准正确。

**标签**：只从新独立生成世界的 official scorer 得到 cap前 `Q_i/Hbar_i`、official band及纯物理 zero indicator；为 nominal miss仍单独计算物理值，不能把 miss误标R=0。future actual hit另列，只供 host评分，不作模型query输入。不得采用旧 opaque artifact、旧worldtruth或旧NN输出作 teacher。

**输入**：public initializer scoring/site/calendar/targets；最近8次曝光，每次最多16个 assigned目标的 public score、hit/missing、已知历史flux/weight/program、actual裁时、RA/Dec与公开H、几何及age；initial permanent terrain完整粗方向集合；已到达 current notices/forecast；public report true/false/同timestamp健康锚点、resync与有效ledger。query保留实际start/d、5slot overlap、H的归一化shape和amplitude、target direction与公开事件条件；移除future flux/weight/B/declared program。history的exact cell编码仅在其scope成立或对每条允许event-nuisance branch分别计算；不能看hosttruth决定actor是否使用该scope。

**公共支持**：永久 terrain nuisance按已经公布的完整粗方向集合生成连续sector参数，可重复粗方向的个数未知；未来事件不因“没有当前notice”被硬置零。current/forecast只约束已公布的kind/direction/night。任何 scene sampler必须在每个query生成相容支持，禁止选择一个固定whole-terrain-set bank再对空支持补概率。report true和false都给同timestamp没有unrepaired active fault的证据，新fault后续仍允许。

## 7. 查重结论与边界

| 已有路线 | 已有内容 | 本候选的具体区别与仍未证明处 |
|---|---|---|
| `SCORE_DISTRIBUTION_STRUCTURE_ZH` | 已推导R商、query flux不变量、随机best正部 | 本报告**不称商变换为新发明**；新增可运行连续cell mass kernel与lognormal stop-loss kernel |
| `feedback_model` / `belief_clock` | 六位factor unconditional lower/upper、band阈值插点、同曝C/E robust grid拟合、单point+scalarAR | 保留全部连续可行region及其mass；不用 .012+.025·score伪噪声、residual clipping和MAP后丢失多峰。transition仍须另验 |
| 四槽 predictive world NN | score likelihood-grid、Gaussian C/Z共享path、先cap/best再期望 | 同一类物理问题已有；本候选减少到未来商jointdensity并明确six-decimal interval，未证明胜过其实际有限test |
| 五槽256path bank | 完整event mesh、zero/saturation/miss、共享futurepath | 连续support不绑定whole-event-set字典；当前单槽解析算法不是完整五槽posterior。禁止把已拒绝bank作teacher |
| direct195 F/band | 同一PMF导首次/复访、joint195类、固定公共query/outergeometry | 学cap前R、移除future flux head关系、连续尾部与解析cap；不是把旧MLP增加epoch或尺寸。负验证未证明物理重学是因果失败原因 |
| 完整模式列生成 | 确定系数的共享time/fiber/target capacity模型 | 本候选给单步G；将未来多次观测换成均值columns不能等于 `E[max(B,S1,...,Sk)]`，不称未知天气LP exact |

若要跨夜资源选择，必须保留同一目标多次贡献的联合law，并在共享场景内部取max；自适应续局还须只按未来公开反馈分支。这是独立后续对象，本stage1没有做未来资源排程。

## 8. 本次 stage1 实际结果、成本和失败

运行：`python3 formal_v4/results/cold_physics_quotient_model_20261004/stage1.py`。只用seed970401现场生成的toy随机C/E；不加载旧world/truth/data。

| 机械门 | 实际结果 |
|---|---|
| 50新toy状态×16目标 official score/band | 800项，max误差8.881784197001252e−16，含55个饱和例 |
| official quality/Hbar 与 C*E | max误差6.661338147750939e−16 |
| 16目标joint六位score | continuous C∈[.7337964701,.7455864944]，Z∈[.4587999934,.4588000453]，含真实(.74,.62)，保留region未选单C/E |
| 同hit复制16次 | posterior cell/mass逐项相同 |
| 饱和、hit-zero、emptyhit | 单侧Z upper∞保留；限定prior内allzero posterior closure1；emptyhit保留prior closure.08 |
| mixed zero/positive | 限定模型zero support，明确拒绝 |
| analytic G 与独立二维密度直接positive-part积分 | abs误差1.6868936802971746e−12 |
| 250 fixed-history query变换 | G对B非增/凸/1-Lipschitz、future flux非减；joint w/B齐次max误差8.88e−16 |
| unfitted lognormal kernel | 4个normal坐标直接数值积分对照，max误差9.79430270220405e−9 |

本机darwin/Python3.10无限制小核：16hit update median约.35ms；**该fixture仅1个可行cell**的32query评分median约.092ms。这是小核成本，未测最坏33cells，也未含publicH计算、encoder、five-slot/event/filter、全field search或2CPU/2GiB生产容器。不能据此称正式actor成本已合格。原强约百万candidate的全量逐cell调用应先batch/profile；如只对point shortlist重算，必须对所有controls固定同shortlist并报告scope。

失败完整保留：首次import root指错层；原primitive相减在六位窄bin中产生6.68e−11 convexity residual，未放宽原2e−12 invariant tolerance，而改成按width因子分段积分和log1p后通过。failed source、JSON与原trace都在本自有results目录。

## 9. 独立实验计划（PLAN_ONLY）

下列split只预声明seed namespace，**尚未生成任何world**。从 `SHA256("cold-physics-quotient/v1/{role}/{index}")` 的前8字节derive独立非负seed；pilot4、train96、cal16、validation24；test24只在gate后生成。publiccatalog/geometry采样、weatherprior、eventcount/ranges、historycontroller、candidatefamily、fit目标与earlystop规则必须在第一个新world生成前一起锁source。现有direct数据和test不接入。

Stage2先4fresh worlds验证官方scalar R/band、actual裁时、两套mesh、roundscore、public feature可重建、initialterrain/current/forecast support、report anchor、miss/zero/saturation和离群范围；label物理与actualhit严格分列。若支持为空则保存失败并停止，不能靠变teacher救标签。

Stage3 Rhodes只生成新世界truth供hostlabels/评分，GPU PRO6000普通NN fit；保留world级split、不按target随机混world。一个明确trainobjective为zero-atom+joint band/positive-R mixture NLL；cal用于checkpoint与一次globaltemperature，不按val或test换mixture数。source、data、model、CUDA/NumPy导出、微决策候选选择与误差阈值都先锁；parity比较既测logit也测最终G与actions，不能拿旧parity失败当性能负结果的解释。

同一finite family预声明control：原strong point C/E公开算法、相同encoder的query-current-only quotient、完整history quotient；candidate同field/d/program/assignment；逐target先期望再fiber max后只能选一个公开动作。先完整官方scalar与kernel分解门，再val以world等权paired realized rate比较selected与strongpoint，95% world-bootstrap下界>0才开新的test一次。另报告full-vs-current、band/zero校准、R tail覆盖、firstvisit/revisit、sat/unsat、notice/fault与实际duration切片。NN较小NLL或history胜current不等于point胜出。finite realized oracle只是该family先知诊断。

2CPU/2GiB成本阶段必须实测完整public query build和同预算selector，包含最长3600秒跨5slots、worst-publicnotice、最大catalog与saturation/empty-support；至少保留原strong动作的候选。只在这些gate与独立test全部通过后，另由root冻结生产整合并进行正常900秒同卡完整闭环，保留faultv1/REQ/cache/exact。未到该阶段不称正式赛提分。

当前产物：[stage1结果](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_physics_quotient_model_20261004/STAGE1_RESULT.json)、[连续posterior小核](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_physics_quotient_model_20261004/continuous_posterior.py)、[连续mixture gain核](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_physics_quotient_model_20261004/quotient_mixture.py)。Git备份交root；本代理不改其他路线目录。

## 10. stage2 的真实曝光扩展与执行停点

精确模型的隐状态应写成 `(night/slot raw seeing,transparency,sky; closure; efficiency/fault/repair; sector/event boundaries; pointing offset)`。给定一个事件/offset nuisance branch，science 的各 piece 系数和 hit 确定，band 的公开网格系数确定；历史每个 target 的 score bin 则给该 branch 的 C/Z strips。跨槽、terrain、部分rocket关闭可以使同曝光16目标各自有不同系数，但共享同一个状态向量。公开score只能约束这些积分组合，通常不足以唯一恢复所有槽C/Z、severities和event boundaries。当前粗方向与forecast nights约束nuisance支持；false/true report结果约束同timestamp的fault状态；missing约束point-offset branch。由这些联合constraint和明确prior定义连续后验，不声称feedback足以唯一识别truth。

若实际实现此filter，需要guided proposals在极窄score strips内采样，并保留互不连通的band/event branches；直接从先验抽C/Z再用六位exact bins rejection会几乎全部权重为零。传统完整filter的cost和mixing尚未实现，不是本stage1成功后自动成立。C/Z单点AR也不能替代原字段/night_state transition。

建议下一次**先执行可直接与失败directF比较的商density NN**，暂不要求一个尚未实现的完整Bayes filter。它是以上连续后验的amortized marginal approximation。history仍按整曝光shared context输入；附加每个hit的3band `R_lower/R_upper/saturated_or_impossible` exact interval编码，这个单target反演恒等式跨槽/事件仍成立，因为R包含其实际unknown积分。该编码不假设同曝所有目标R相同，不冒称已经得到了联合posterior。历史likelihood中的flux/weight保留，未来query对应字段消去。通过fresh-world公开context训练实际transition和forecast条件；不硬编码“forecast没列出就晴”、fixed fault数量或scalar C-AR。

forecast校准以**决策时已收到**的coverage/start/end、事件kind/direction和列出的query night作features；night外预测保留unknown状态。数据按query lead time、距上次观测的observing slots、新夜次数、quake/current-direction/forecast-only/fault-history切片报告joint band Brier、zero Brier和R的50/90% interval覆盖。对连续天气先验的night/slot AR、clipping和事件边界完全使用新的official generator；其参数是明确研究prior，不能当正式卡公开配置。cal只调预声明global logits temperature与positive-R sigma multiplier，固定cal NLL准则；不据validation失败新增forecast规则或改teacher。

具体stage2实施预算与停点如下，root review后才能启动，不由本代理执行：

| 阶段 | 固定对象 | 资源/成本合同 | 停点 |
|---|---|---|---|
| 2A真实pilot | 4fresh worlds，每world32完整public-history states；同field/d候选纯R/band、actual-hit两套label | Rhodes CPU；每world≤120秒/≤1GiB的预声明pilot预算；额外记录officialscalar、historybuild、feature、write各段成本，不预报总秒数 | source/hash/public重建、真实eventmesh、forecast初始terrain支持、quantized-score合法性或budget任一失败即保存停止 |
| 2B锁源数据 | train96/cal16/val24，每world32states；两public fields×最多5actual durations；每field最多64个公开候选target供fiber选择；上限2,785,280 future physical labels | Rhodes独立workers与world分片；float32 query≤64维时单query总数组上界约680MiB，history按world共享不复制到每target；这只是内存计划，正式measure后再允许运行 | source/model/data locks完成后不换menu/prior/splits；超pilot外推成本预算则停止并保留 |
| 2C普通NN | full-history/current-only两控制，各两层128，39-output joint R/band head；NLL拟合，cal选模与两标量校准 | PRO6000；首次预算每模型≤120秒fit、≤1GiB CUDA peak；要求NumPy logits、G与最终同menu动作parity；不是报告已发生训练 | 不通过导出/支持/数值门不生成test；fit/val不胜point不换head或加epoch救本批次 |
| 2D共同决策 | 同public fields/durations/programs，逐target先算期望再fibermax；strongpoint、full/current quotient、同head先均值control | 真实2CPU/2GiB actor fixture，包含H/querybuild/NN/nativeassignment；predeclared每selector额外≤20ms median/≤50ms p95且≤64MiB新增working set | val world-paired Δstrongpoint均值>0且95%下界>0，并通过完整cost门，才允许24fresh test一次；否则test未生成 |

两fields必须由决策时publicgeometry/point controller产生；field0包含原point当前建议，field1由同刻公开目录anchor规则产生，不能取下一条host future action。五durations包括point当前实际duration、300/900/1800/3600，按实际night/survey末端裁时去重。64target cap若丢弃了point的任何候选须显式将其补入或把该state拒绝，不能把缩窄menu伪装成strongpoint本身。val的原strongpoint只是这一共同family的真实公开point控制，整季最佳6658.465不是micro分数。

与directF的明确改动只有新物理标签和解析关系：futureflux从head消去、未截断R尾部不被F=1丢掉、cap/weight/program/best在同一analytic kernel计算；known duration/H amplitude在外部scale。仍需学习的是C/E/closure未来transition、未知sector和event时间、band与R的相关、forecast条件和history信息的利用。需要NN学习的随机性没有因为换商而消失。以上只是可证结构与可执行新实验假设，未指定刚失败directF的因果原因。

full/current版本按cal world等权joint NLL一次选定，validation只作上述decision gate；不按val逐head/checkpoint救参。选中版本、cal参数、candidate、source和split在test前全部freeze。

root新写的 [STOCHASTIC_PATTERN_MODEL_ZH](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/research/STOCHASTIC_PATTERN_MODEL_ZH.md) 已明确有限joint情景的(i,s)得分层coverage可以保留随机复访，pricing仍按fiber分离。**本文39-output NN的stage2只预测当前候选一次曝光的(R,band)边缘分布，不能为该随机未来排程模型提供正确joint输入。** 不同曝光/target各自从head独立抽R会破坏共享weather和复访相关性。若进入跨夜模式排程，须另立实验：由连续full隐状态posterior采样原字段/night_state、closure、fault与相容sector参数，再沿official transition生成同一条joint future path，所有候选共用path和eventmesh；或用普通NN学习这个完整state/path生成law。其共同path校准、未来forecast/publicfeedback分支、随机max与actor成本都需独立验证，不外推本单次曝光核成功。
