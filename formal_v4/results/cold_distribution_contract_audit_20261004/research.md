# 独立数学与公开输入契约审计

2026-10-04。审计对象为 `cold_target_score_distribution_20261004` 中的 `target_core.py`、`public_features.py`、`pilot.py`、数学/输入 probe，以及同目录 `official/challenge` 的原始评分、runner、workflow、生成器和验证器。只运行独立本地机械核查；没有拟合、线上操作、旧 sealed L4/旧 calibration/test 读取，也没有修改被审计文件或 Git。

结论：**当前核查范围通过，原夜尾时长缺口已修复。** 这证明数学算子与当前公开特征的机械契约；不证明尚未冻结的训练数据 builder、NN 拟合准确性、完整部署策略或完整赛季收益。审计源码 hash 见 `AUDIT.json`/`PROBE_RESULT.json`，后续源变更须重新核查。

## 1. 官方预测对象与公式

官方 [v4_scorer.py](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_scorer.py:393) 的单目标公式为

`F = min(flux × actual_duration × q_exp / (flux_zero_point × exposure_zero_point_seconds), 1)`，

`science = science_weight × F × program_multiplier(declared_program, physical_band)`。

官方 reference 生成器产生非负效率/transparency/sky、正 seeing；公开 flux 非负，归一化常数正，因此 F 在 [0,1]。这里说的是合法生成器真值域，裸 scorer 并不自行把任意非法负天气截成零。目标的 science_weight 不参与 F 或 physical band。V4 目标没有 `complete_score` 字段；若用此术语表示饱和一次贡献，其值依赖 program/band，为 `w*m`。F=1 不蕴含 score=w。

physical band 的 [band_quality](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_scorer.py:248) 积分站点 transparency×sky×目标 Moon/seeing/airmass，忽略 instrument efficiency 和 directional event multiplier。F 积分额外包含设备效率、故障修复、方向事件、terrain/rocket closure。[score_target_exposure](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_scorer.py:341) 按 slot overlap、event start/end boundary 切分，再以不超过120秒的中点积分；关闭区间贡献零，部分方向覆盖只影响相应区间。ALL-scope 事件已折进 slot truth，不能再次按方向事件相乘。

命中检查和整个曝光的 min-alt 检查在 [runner](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_runner.py:718) 外层完成。实际一次 action 贡献为 `I_actual_hit*w*m*F`。现有 pilot 明确分别保存 physical F 与 effective `I_actual_hit*F`；下一训练选择 physical `(F,b)` 合理，但精确 action science 等式要求外层 hit/altitude 准入成立。未知 offset 的几何风险仍由原强公开 calibration/admissibility 处理；不能把未确定的 hit 概率擅自与 F 独立相乘。

scorer的physical F与band参数均不含pointing center/fiber。因此固定同一target、start、actual duration、site/scoring与weather/repair分支，换指向中心完全不改变F/b；变化只能来自外层I_hit。fresh最小例：940901的V4T000002，2026-10-02T00:00Z，d=900；两次公开nominalglass fiber10指派的command altitude均67.4180622794，az分别109.0005546980与109.3905546980。其physical F都1、band都DARK，actual hit却一真一假，effective F为1/0。证据在 `POINTING_INVARIANCE_EXAMPLE.json`。当前pureF future query已删center/relativeoffset的末5维（56→51），换public center的query逐元素不变；history仍保留nominal tangent offset以解释已公开miss。同decision/context下可按target/start/actual duration缓存physical features与PMF并跨field/program复用；context、model/temperature、site/scoring/flux或repair分支变化必须让缓存失效。

## 2. 联合 PMF、同分布矩与 science hinge

[target_core.py](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/target_core.py:15) 的标签将 F 按均值保持的线性权重分配到同 band 的相邻 factor knots。K=64，3×65=195；0、1 端点质量与首矩精确。[moments](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/target_core.py:31) 从这个同一 PMF 导出 `mu_b=E[F*1_band=b]`、`mu=sum_b mu_b`。

[expected_gain](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/target_core.py:38) 计算

`G_p(B)=sum_bj p_bj * max(w*m_p(b)*j/K-B, 0)`。

概率非负且总和1时，G 关于 B 连续、非增、凸、1-Lipschitz；B=0 精确化为 `w*sum_b m_p(b)*mu_b`。其斜率区间是 [-1,0]。Query 不含 B/w/declared program，所有 best/program 共用同一次 physical PMF，避免首次矩与重访分布不一致。

固定合法 assignment 后，跨目标相关性不影响 science 增量期望的可加性。应先求每目标期望，再在同 fiber 选择目标，或求合法 assignment。`positivepart(mean_score-B)` 与先对每个隐藏 world 取同 fiber 最佳目标后平均，均不是相同可执行目标。目标可相关，所选 program 为整个合法 action 共用。

设区间 [l,u] 宽 Δ=1/K，a=w*m>=0，hinge kink r=B/a。区间弦插值上偏；只有 kink 落在该 bin 时有误差，最大在 F=r，等于

`a*(r-l)*(u-r)/(u-l) <= a*Δ/4 = w*m/(4K)`。

所以真实条件分布的投影误差满足 `0 <= G_projected-G_true <= E[w*m_B]/(4K) <= w*max_b(m_p(b))/(4K)`。w=0 或 m=0 时误差为0。这个一般公式覆盖 reference 的 w∈{.3,.45,1,1.7}、匹配倍率{1.2,1.12,1.06}以及 mismatch=1。全局单目标界为1.7×1.2/256=.00796875；16目标为.1275。`1.2/(4K)` 是当前配置每单位 weight 的值，不是任何自定义配置的通用常数；若 mismatch 将来超过对角倍率，也应把它纳入 max。

该界不约束 NN 预测误差，也不约束硬完成阈值。最小反例：F=.5−1e−6 的官方 `F>=.5` indicator 为0，但线性投影在0.5 knot 上放质量.999936，按 knot 求尾概率几乎1。硬阈值尾误差可趋1。当前提案保留原 required/REQ/Jain 处理，没有把此 histogram threshold mass 接入它们；因此这不阻断 science-only PMF。REQ k-of-n/Jain 另需联合事件处理；普通 required 罚项虽逐目标可加，其硬阈值也不享有 hinge 的量化界。

## 3. score precision 与 public history

[workflow initializer](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_workflow.py:55) 公布的 science_weight/flux/坐标是 [runner](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_runner.py:206) 从同一 CSV 解析出的值，因此 host label 与 actor weight 没有使用两份不同精度的值。

[last_result](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_runner.py:820) 只给实际 hit 的 target_id 与六位 score；assigned miss 没有 score 行。公开 history 必须区分「miss」与「hit but score=0」，现有 token 做到了。六位 score 的物理反推是区间与 band 混合，不是唯一 F：除w之后半宽为 `.5e-6/w`，如果 band 已知再除对应m；program声明必须保留。饱和 score 同样不能唯一解出 latent efficiency/weather。

此前 history 只保留 score/w，没有精度信息，且 w=0 会除零。当前 [history_target_features](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/public_features.py:144) 对w<=0安全返回不含score信息的空 token；命中/REQ仍在外层公开结构。第21维存 `.5/w`，单位是百万分之一 score/w，乘1e−6才是半宽。reference 的非零 weights 没有裁剪该精度字段；极小自定义w受1e6 cap，不能声称任意权重下精确舍入似然。

公开 best 是 raw ledger 最大值的六位舍入。保留每次六位 score 后取 max 与舍入真实 max 一致；max本身是1-Lipschitz。因此 `|B_public-B_true|<=.5e-6`，science hinge 每目标由best舍入引起的误差也<=.5e-6，16目标<=8e-6。官方最终 score report 再对总和舍入，若直接比较报告值，还需计入额外.5e-6；目前算子目标是 raw science 增量。硬 completion / request progress不可把这一个score误差界当成事件正确性保证。

数据损失只撤销 ledger 有效性，原始过去测量仍然真实发生。[PublicHistory.resync](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/target_core.py:80) 按官方 observe index window 标记 invalid，不删除 score；重新取best时忽略invalid。官方 [invalidate_window](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_scorer.py:434) 和 resync具有相同语义。REQ在loss后的差额settlement并不等于旧score天气测量失真。

## 4. 原时长缺口与修复

官方 [v4_runner.py:711](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_runner.py:711) 先把请求end截到survey_end，若start在夜slot中再截到night_end；以实际整数秒做min-alt、band、F。初审时 query/history/labels 使用请求时长；stage1 pilot已主动提前clip，因此这个缺口不否定原pilot结果，也不影响旧最强ZIP。

具体例子来自本阶段fresh world 940901：N20261001，V4T000919，2026-10-02T08:59Z开始，请求900秒，官方实际60秒。未截短band_quality=.0519377735，band=BACKUP；实际band_quality=.7790666027，band=DARK。两者F≈.049602855887，但声明DARK时贡献分别为.049602855887与.059523427065，相差20%。详细数字在 `NIGHTTAIL_PRE_FIX_EXAMPLE.json`。

负责实现的代理在收到审计反馈后添加公开 [clip_duration](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/public_features.py:15)，query/geometry/history/action metadata都调用它；[pilot.labels](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/pilot.py:109) 同样使用actual duration，并分列requested/actual。独立probe确认900请求与60 canonical action的query/history/meta逐元素相同、F/b相同；最终survey尾部52秒也匹配；3600秒曝光从slot内偏移1秒开始完整表达5个slot，overlap fraction总和1。

actual H有两种全公开获取方式：预测前用initialize的public night/survey end计算canonical duration；实际past history用下一decision snapshot的 `now_utc − saved_start_utc` 得到曝光实际秒数。last_result本身不含duration。后者须在刚结束该observe的snapshot处理，不能跨后续wait/report时刻取差。最稳妥的是二者交叉核对。

当前query域要求start在公开observing night中且actual duration>0；daytime动作与非reference「超过5slot」的配置不在此51维契约域，外围准入需执行这一限制。

## 5. 已发布信息、terrain、forecast与report

[publication_state](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/public_features.py:22) 对 `issued_at_utc<=available_until` 显式过滤。历史动作使用当时available_until，future query使用当前公共信息可用时刻；不能用query的未来start去放行将来才发布的消息。公开完整night calendar和可计算Moon/airmass轨迹允许预测未来几何，不属于future truth。

terrain只出现在 [首公告](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_weather_simulator.py:903)，代码从保留的公开消息累积9方向bits，所有256个八方集合可表示。当前天气公告是latest published coarse kind×direction；真实sector边界/幅度/起止时间不在输入。forecast同时按已发布时间和public coverage判断query night；「覆盖且无notice」与「尚无coverage」用meta中的coverage位区分。未来时间消息即使错误附加到seen列表，也不会影响当前特征。

forecast generator按 [coverage window](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_weather_simulator.py:947) 裁剪night列表；fault/quake不预报。quake年龄锚仅使用首次公开quake公告时刻，不冒充隐藏震源起时；当前表示用于统计推断，不能从粗公告精确推回物理天气参数。

true report立即修复未修active fault，false report则表示该时刻不存在未修active fault（也可能原fault已被修）。官方 [report action](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_target_score_distribution_20261004/official/challenge/v4_runner.py:667) 不推进simulated time，所以两者均是同时间healthy anchor；不保证以后没有新fault。新代码的report年龄/真假位符合此含义，没有用false结果反推出具体隐藏efficiency。

## 6. 验证证据与范围

独立 `audit_probe.py` 通过15,000个target-program hinge cases，first moment error=0；reference全权重、各program倍率的逐样本解析界均通过。独立constant-position directional事件在30秒/60秒边界切分的积分与手算F一致，误差0；band不乘该方向事件。其余机械检查覆盖canonical query/history/meta、night/survey boundary、full5slot、query不随w/B/program/pointing改变、zero-weight安全、舍入精度单位、future消息censor、coverage、terrain集合、loss retainedmeasurement、assignedmiss与zerohit、falsehealthyanchor。现有 `INPUT_PROBE.json` 仍是原stage1的56维输入票据，不能拿它代替新51维源码的机械证据。

没有发现当前reference science-only physical PMF的剩余阻断错误。下面仍须由下一阶段自己通过：单一195 softmax与实际训练loss实现、数据builder当时public cutoff、后续report/loss分支生成、可执行动作先选择后读取future label、NumPy export一致性，以及正式资源与完整策略gate。未拟合randomweight成本不能作为这些gate的替代。
