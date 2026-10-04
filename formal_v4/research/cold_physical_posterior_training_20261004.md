# 五槽联合物理后验：真实 PRO6000 训练与负结果（2026-10-04）

## 1. 结论

**拒绝本版 NN 及同一无条件路径库生产部署。** 普通 NN 已在 RTX PRO 6000 Blackwell 实际拟合；同一锁源只对预锁 test 执行一次。没有生成新 actor/强组合 ZIP，没有启动实际整季、线上或 L4 调参。原 faultv1 + RequestCache/Terrain/REQ/cache/exact 保持。

原因有两项：

1. 五槽物理路径的期望在固定科学候选微域中优于天气点估计代理，但 NN 相对同库固定先验的 cal/val 世界级区间跨零；test 平均反而更差。物理 bank 与非线性结算带来的改善不能全部归于 NN。
2. 独立只读审查发现固定 dictionary 在多数 cal/val 局面没有满足已知永久地形粗方向公告的原型；有相容原型时也保留矛盾质量。其概率并非满足全部公开证据的条件后验。无条件 bank 具有相同缺陷，不能因优于点估计而部署。

完整机器结果为 `results/cold_physical_posterior_training_20261004/FINAL_RESULT.json`。全部数据、失败 source/model/GPU 日志、每 query 的正负/tie、世界级 paired delta 与独立 audit 均保留。`ARTIFACT_MANIFEST.json` 保存最终全文件 SHA256。

## 2. 独立数学合同与已知支持

本研究先独立读取正式 `v4_runner.py`、`v4_scorer.py`、`v4_workflow.py`、`v4_fiber_map.py`、天气/事件/公告生成器，再完整读取算法 portfolio 去重。另读已完成的 full-altitude 审查，不复跑其旧反例。

记每槽 `C = transparency * sky_quality / (seeing * q0)`，开放标志 O、有效效率 E。H 是目标在积分时刻的 Moon × airmass 项。正式 band 使用按槽边界、每段最多 120 秒切分的中点积分；science 另外按方向事件起止边界切分，再最多 120 秒中点积分：

- `B = Σ span * O * C * H / duration`。
- `Q = Σ span * O * C * E * sector_attenuation * H / duration`。
- `factor = min(flux * duration * Q / (f0*T0), 1)`。
- 单目标 science contribution 为 `weight * factor * program_multiplier(B)`；科学增量为 `(contribution - public_best)+`。

B 与 Q 的切分网格不同，不能通过共用平均 H 或强行 `Q<=B` 代替正式积分。每条 path 用自己的事件边界签名，不能因加入另一条 path 或 host truth 而改变其网格。最长 3600 秒、起点不在槽边界的曝光最多横跨 **五槽**。候选按夜末实际时长截断，末段不足 60 秒仍采用实际 duration。

参考生成先验（不是任意 formal card 的保证）中 seeing∈[.5,4]、transparency∈[.08,1]、sky∈[.05,1.5]、q0=.68，故开放 C∈[.0014705882352941176,4.411764705882352]；scorer 不把 C 截到 1。参考 E∈[.1,1]，修复时按官方故障倍率反除并上界 1，quake/jitter 仍保留。关闭槽存 C=E=0，E 不解释为可测的闭站效率。本 bank 的实际最大 C=2.5764452626、最大开放 E=.999974；全部 prototype 来自真实新 synthetic world，不截旧 Gaussian 样本。

当前 `physical_operator.contributions` 与 `evaluate.py` 限于参考卡 `.65/.4`、program `[1.2,1.12,1.06]`、`f0*T0=450`；World 的 C 使用参考 q0=.68。几何 H 已读 initialize 的 airmass/lunar 配置。成本 helper 已从 initialize 读 contribution 常数，但这不代表整个实验已转换成任意卡生产合同。未来正式实现必须全部读 initialize.scoring；不可把生成器数值范围当公开特征。

## 3. 相比已保存路线的新信息与复用

旧 32-state continuation teacher 是少数行为状态的单世界动作标签；16-path scenario_value 曾有跨 duration 前缀一致性错误，修正后完整验证为负；quality-window PMF/dual 是有限机会近似；旧四槽 Gaussian(logC,logZ) 尚有 E>1 和第五槽/方向/history 表示缺口。本研究没有改这些旧 test 或重复扩大 K。

新内容是：独立官方世界的五槽联合 C/E/closure/fault + 完整方向 sector path；保留实际 public RA/Dec、duration、geometry、零/饱和/缺 hit 与 report 健康锚点的条件分类器；完整正式积分下的共同候选 regret。复用公共 L1/L2 action 只作为固定采样设计，复用官方函数/原强天气点估计代码作控制。不是新 closed-loop strong teacher，也不是把旧 scenario_value 手工权重扩为更多路径。

256 类选择是一次预锁 farthest-point coverage；标签为 latent distance 最近 8 类的软投影，距离温度 .5 固定。此标签是有限压缩目标，**不是公开 feedback 的精确 likelihood**。不能用较好分类 NLL 遮掩 prototype 投影误差或称其为完整 Bayesian posterior。

## 4. 公共输入、host truth 与同 timestamp 支持

每 query 使用最近八次原始公开曝光，每次最多 16 个已分配 fiber 的目标行：assigned、实际公开 hit、公开六位 score/weight、flux、RA/Dec 三角表示、五槽 H 权重、首积分点 alt/az；曝光 meta 含 program、命令 field、实际 duration、date/night/time 与当时已收到的 notices。Query tail 含当前 notices、此前已公布 forecast、report 年龄/true或false结果/次数、resync 指示。TOKEN_DIM322、tail160、总 XDIM2736。Float32 是表示近似，完整 public sampling cache 保留重建值。

没有原私有 factor、band、quality、program_multiplier、offset、valid 输入，也没有旧私有 score。每个新 world 的物理 hit 用其独立 offset 在 host 重算，公开 target_ids 与六位反馈由该 world 产生。future path 仅用于 supervision/projection 与 realized-value host 裁决；候选赋值没有未来 truth。Independent audit 未找到特征未来泄露。

`report_result correct=true` 与 `correct=false` 都提供报告同 timestamp 无 active-unrepaired fault 的精确信息。标签/推理硬 mask 同时排除 first-slot active fault prototype；校准31条、验证19条该类概率全为零。健康起点后允许新 fault：bank 有五条首槽健康、后槽 fault path。后续 synthetic score 按对应 world 修复重算，保留 quake/jitter；没有旧 reportNN controller。data_loss 发生时重算公共 best ledger，历史测量仍可作为天气证据。

使用完整公开事件 kind/direction 信息不能消去未知 width、alt bound、severity、duration，prototype 这些 nuisance 来自独立世界，host 未来参数不是 actor feature。

## 5. 预锁数据、源与实际训练

锁定 split：pilot909000–909003；bank910000–910031；train911000–911095；cal912000–912015；val913000–913015；test914000–914015。参考事件 count 范围为 synthetic prior：weather 每种0–3、quake0–2、fault0/1/2概率.25/.5/.25。不是 actualcard 参数恢复。

Bank 每 world64 queries，加 report augmentation 共2073paths，压为256真实 prototype。Train/cal/val 每 world128queries，加相同 report augmentation 后12446/2079/2067rows。fit_data.npz 48,585,380bytes；test 在 PRETEST_RECEIPT 后独立生成2078rows、6,079,376bytes。采样固定真实公共 action time/field/duration/assignment，只重算新世界结果；未来源 tape 的 field 用作固定 family sampling design，不能据此给 actor 一个“知道未来 action”的 field generator。

Ordinary MLP2736→128→128→256，399872参数；AdamW lr.0007、wd.0001、batch512、40epochs、seed915441。以 cal softNLL 最低 checkpoint 选第5epoch，cal 单标量 temperature=1.2227642536。没有按 decision regret 选择模型，没有扫 K/domain/temperature 配置，没有用 test 修 bank。

真实训练通过 elevatia-wsl 的 Windows Python3/Torch2.7.1cu128/NumPy2.2.6 在 **NVIDIA RTX PRO6000 Blackwell** 执行。修正后 trainer 内部耗时5.042465s（fit/校准/导出），CUDA peak230,416,896bytes；训练已结束。GPU原始日志 `train_gpu.log`；所有后续 regret 是 CPU eval。

| soft label NLL | cal | val |
|---|---:|---:|
|NN|3.202890|3.143633|
|constant prior|4.462751|4.792825|

后期 train NLL 降到 .7881，cal 升到4.1406，过拟合已保留，不作为选中模型。更好的 NLL 不证明公共支持正确或决策泛化胜利。

## 6. 数值门检与可执行共同候选

新四 pilot world、48曝光、1743 official contribution checks，分别计算 band/science geometry 与三 program；最大误差 **8.881784197001252e−16**。这是参考域的数值等价门检，不是 posterior support 门检。

157cal公开 fixture（含31report锚点）的实际 CUDAfloat32 与 NumPyfloat64导出比较：最大概率差4.808599520234047e−7、sum差4.44e−16，有限且同timestamp forbidden mass0。Mac NumPy 有浮点 warning，原记录保留；无 source/parameter rescue，Linux cost stderr 为空。

共同 candidate family 最多为两个 public sampling field × 五 durations × 三 programs。Durations 为 source actual、300、900、1800、3600，去重且 clip 夜末；每个 field/duration 的公开 assignment 先统一形成，再按各 path 结算 cap/program/best，平均其科学增量/秒，选一个可执行动作。不会各 path 先最佳匹配再平均泄露先知信息。

Field0 保留 source assignments；field1 将同夜 next source action 的 center RA/Dec 转到当前时刻，并用公共 point estimate 统一按 fiber 选择、实际整个 duration 最低高度过滤。所有模型/先验/oracle 共用这些候选与 assignment。独立 audit 发现 source field0 在 L1/L2 原 public pool 分别有2/13404、2/14900个 zero-offset nominal miss，预测假定命中而 realized 值重算新 offset；此小范围合同不足也保留，test 后未修。

`strong_point` 仅原强 fit_feedback+BeliefClock 的 C/E、公共方向尺度对这个共同有限 family 的 point proxy；不是完整 strong actor 的得分。Rank 仅 science gain/second，没有完整 REQ/Jain/机会成本/续局/repair介入的外部效应。原 strong 原27source 与 production field/duration/assignment 未更改。

每 world 预声明最多16随机 queries，regret 子集排除即刻 post-report augmentation，以免同 j 决策前/后混淆。cal/val/test 为253/253/252queries。所有新 world 重建输入与冻结 feature 数组逐项一致。分类及 export 的 report 检查仍保留 augmentation。

## 7. 独立一次 test：改排序而未确证 NN 增益

Regret 定义为同候选 family 的 host realized 最佳 science points/second 减本方法选择的 realized rate，越小越好。

|方法|cal253|val253|test252|
|---|---:|---:|---:|
|NN posterior|.0004596766|.0006156605|.0006196083|
|same-bank unconditional|.0004732221|.0006489305|.0005914474|
|strong point proxy|.0010767931|.0012079094|.0014062320|
|nearest physical prototype|.0007702019|.0007682193|.0008087013|
|perfect top8 label projection|.0006322036|.0005954403|.0005862241|
|clairvoyant dictionary coverage oracle|.0000123327|.0000251649|.0000124218|

Nearest/soft projection 用 host truth 找 prototype，旨在分离 dictionary 压缩风险，不能部署。Coverage oracle 进一步在各单prototype所选动作中挑 realized 最佳，仅是先知上界，不是 posterior 收益。完美压缩 label 本身也未稳定优于 learned mixture，表明 latent距离不等于候选决策损失。

NN 对 point 的 query win/loss/tie：cal61/62/130，val73/58/122，test63/61/128。相对 point，NN field/duration/program改变 cal53/105/30、val58/105/47、test67/104/27；确实能改变科学排序，仍不等于生产提分。

16独立 world 等权 paired Δ（NN所选 realized rate−控制所选 rate），SE 按 world 均值：

|split/控制|Δ|SE|world win/loss/tie|
|---|---:|---:|---:|
|cal/point|+.0006230952|.0001800852|14/2/0|
|val/point|+.0005920672|.0001495196|16/0/0|
|test/point|+.0008034844|.0002989966|13/3/0|
|cal/unconditional|+.0000132296|.0000388738|7/7/2|
|val/unconditional|+.0000332990|.0000328267|10/4/2|
|test/unconditional|−.0000253337|.0000969530|11/4/1|

NN对unconditional的三份描述性 normal95区间均跨0；test为[−.0002153615,+.0001646941]。不以11个小赢掩盖4个损失或负平均。共同路径期望对 point 的结果提供有限非线性分布机制证据，不能把它归为 NN 强策略或整季 GOSIM gain。实际整季 gain 未测，字段为 null。

## 8. 原型量化与公共支持：拒绝的具体机制

Nearest prototype 单目标 contribution 绝对误差 p0/p50/p90/p99/max：

|split|p50|p90|p99|max|
|---|---:|---:|---:|---:|
|cal|.019693|.251895|.646968|1.724910|
|val|.035007|.258332|.639728|1.514329|
|test|.013818|.238628|.609718|1.289131|

Prototype band不一致比例为 cal20.65%、val29.00%、test14.37%；truth B 距 .4/.65<.02时分别64.19%、58.40%、58.03%。临界点与饱和会改变 score 排序，有限粗网格未解决该风险；较小 coverage oracle regret不证明当前标签投影好。

独立 audit 只读 cal/val（未读 test），没有修改 frozen model/source。地形 sector 在开季全部公告，方向按官方 sector center 映射，公告去重。令公开永久 terrain 粗方向集合为 T，任一可能 path 的完整 terrain 集合为 T_k，则 **T_k=T 是必要的公共支持条件**。连续 az/alt/width 可未知，但不允许凭未知 width 将另一粗方向的完整永久地形当作当前世界。

|必要相容条件|cal无相容class/rows|val无相容class/rows|
|---|---:|---:|
|permanent terrain set|1297/2079 (62.39%)|1419/2067 (68.65%)|
|terrain + 当前非ALLweather方向|1362/2079 (65.51%)|1451/2067 (70.20%)|

对应 incompatible posterior mass 中位数为1；即有相容class的记录也有矛盾 mass，terrain mass最小仍约.056(cal)/.049(val)。本实现未施 notice mask；空支持本身也不能靠 hard mask 修正。**此错误是固定 whole-event-set dictionary 的离散支持/条件建模不足，不是 future truth 泄露；它足以推翻精确 conditional posterior 声称。** 无条件 bank 同样不能满足这些已知公告。

参考 config 规定 ALL rain/storm 强制关闭，因此同槽 O必须0；cal70条、val69条该公告下 NN open mass 中位数.2255/.3583、最大.9644/.9251。这条强制关闭结论限于本冻结参考 prior，不能泛化任意未知 card config。相比之下 report 同timestamp healthy anchor 的硬支持检查通过。

天气方向集合相容条件限于本实验官方slot对齐生成域，ALL事件未存成 sector event，不能通过 sector集合恢复所有ALL类型。Independent audit 详细说明这些限定，而非假称严格完整posterior检验。

## 9. 失败、锁与可重现文件

以下原始失败均保留：operator NumPy bool JSON序列化；第一实际GPU trainer误把 TOKEN_DIM设330导致错误report mask（模型/训练/源全部在failure_mask_v1/，拒绝）；cal/val空field floatmask索引异常（failure_eval_empty_v1/）；2CPU浅挂载导入父路径异常；Mac NumPy浮点warning。唯一模型重跑是330→322与正式feature合同一致的修复，同dataset/config/seed，test未读。没有按 test 救参。

`SAMPLING_LOCK`记录初始source；`SOURCE_LOCK`记录等价operator向量化、trainer mask修复、emptybool修复等前测修订。PRETEST_RECEIPT 在生成test前核对source/model/data及cal/val/export。test后核对18个source/data/model/GPUlog与26个official .py SHA全部未变。最初SOURCE_LOCK未列reference weather JSON；最终manifest补列该文件sha，不能声称它属于最初18项。

关键 SHA256：

- SOURCE_LOCK：`a4515d36c105c1840bf6738ab6c481d9bced6733b1cca92262d5acf1cfacbec7`。
- 最终model：`9e75eb175695cadb915cd79e0919dcd38f018172eb06816f9acda65719f139cb`。
- fit_data：`ba5b660d322bcb4501ed70325e2aedb6fff0a6a9fa9705bce2cda2be21ab0d9d`。
- test_data：`0a34e625150dbcbe2ae11e54bd1fe439f97f6b679d42c2875b47c210fe4d75a6`。
- 原最佳strong ZIP：`5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`。

源码可执行入口：`build_data.py`（预锁bank/train/cal/val，--test仅单独test）；`train.py`（需CUDA与现有fitdata）；`physical_operator.py`（1743正式数值门检）；`evaluate.py cal|val|test`；`independent_public_support_audit.py`；`runtime_bench.py`。这些是研究重现入口，重新执行会覆盖某些同名输出，归档后应在复制目录使用；本研究没有重复执行test。`physical_core.Predictor` 与 `physical_operator.qualities` 可在publicstub上调用，**没有完成可移植生产 actor**。

## 10. 实际 2CPU 成本与部署限制

Rhodes1 资源检查后仅用物理核12,13，2CPU/2GiB、readonly、无网络、非root、无capabilities、NumPy线程1的容器测四个 public fixture×5次。只挂5.50MB研究runtime包与依赖；无train/test label、world生成或私有未来输入。包中bank是已训练预测参数，属于允许的独立syntheticprior。具体限制与image digest见 COST_CONTRACT.json；完成容器已清理。

- NumPy posterior mean .1173ms、P95 .1626ms、max .2427ms。
- 一个固定field、14–16targets、5–6durations×3program×256paths的完整积分 mean35.42ms、P9548.59ms、max49.32ms。
- RSS51224KiB≈50.02MiB，stderr0bytes。

这是受限 publicfixture 成本，不是全strong多field候选/assignment/REQ的生产循环或整季预算。浅挂载失败暴露host模块路径依赖；通过更深挂载运行不构成可移植actor修复。没有为了成本另开大量trial。

## 11. 下一研究合同（未启动）

下一机制应先令支持条件可执行且非空：在每个publicquery上生成共享已知coarse terrain/当前/forecast kind与方向的path，只对相容连续width、alt bounds、severity、duration采样；或建立bounded连续五槽C/E与closure联合模型，并将event-conditioned nuisance独立显式表示。必须保留closure-quality相关、未来slot hazard、真/假report同timestamp健康锚点、完整geometry两套mesh、真实末段duration。

训练前重新锁新split与candidatefamily，先做notice support/prototype oracle/projection regret，再做NLL；在同一family单列posterior与unconditional世界级paired增益。候选expected edge increment先于一个公共assignment。未来生产质量替换要读initialize.scoring，并从原strong evaluator中明确移除已经在path中包含的Terrain/方向乘子，避免double attenuation；faultv1/REQ/RequestCache/cache/exact保持。未知方向nuisance不能用host未来特征解决。

本轮到此归档，不重启训练、不改bank、不扩K、不再读test选模型、不启动actualfull。当前结果为明确negative。
