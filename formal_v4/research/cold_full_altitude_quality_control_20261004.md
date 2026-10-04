# 完整曝光的联合质量积分审查：本轮收束

日期：2026-10-04。结果目录：`formal_v4/results/cold_full_altitude_quality_control_20261004/`。

结论：**不交付新的参赛策略，不启动整季，不训练同路线 NN。** 旧 NN 的科学价值算子已经能把四槽天气路径乘上任意仰角的公开几何积分；80.05°限制主要来自模型适用域。完整 3600 秒、低仰角方向事件和历史特征的限制，不能仅靠数学换元全部解除。独立提出的分布饱和断点时长机制属于已有 `scenario_value` 的路径内 cap/program/best 后取期望路线；改变 posterior 的模型质量可能有价值，本轮没有证明它胜过当前强策略。

当前优先包仍是 fault v1 加 exact CPU 算术的 ZIP：

`formal_v4/results/cold_sparse_science_runtime_20261004/observer_sparse_exact_fault_20261004.zip`

SHA256：`5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`。本轮没有修改它、原27 source/config、旧模型、portfolio、其他产物，也没有创建参赛入口或提交线上。Rhodes1 和 PRO6000 均未使用。

## 独立抽象与查重

先读正式 e01939d0 的 runner、scorer、workflow、fiber map、catalog/weather generator，再完整读 `ALGORITHM_PORTFOLIO_ZH.md`。科学收益来自每目标的有效历史最大 **program 倍率后分数**；重复曝光不累计 factor。required 使用独立的最大 raw factor 阈值；REQ 的 witness 必须完整位于请求窗口；Jain 可能有负边际；loss 依赖 observe rank 和失效后重新扫描。局部期望 science rate 改善不能自动推出终局改善。

公开输入是目录、日历、仪器/计分、已发公告/预报、实际 hit ID 和六位 score、report result 与 resync。未来槽真实天气、具体方向 sector、故障时间和偏移都不能作为 actor 输入。本轮生成的未来 truth 仅用于 host 算子检验，没有读取任何 L4 封存标签或真实 local-card future truth。

查重后，以下内容已有：完整曝光积分、逐路径 program/cap/best 再平均；共享天气路径、前缀一致性；随机时长阈值与完成分位；强对照的 scenario_value 路线最终 L1/L2 平均负收益。原 predictive NN 的四槽 joint(logC,logZ) 是更丰富的 posterior 模型，但其 `utility_samples` 已实现上述数学次序。因此“降低 gate 后重评分更多原候选”不能作为本轮新机制。

## 可以精确消去的积分维度

在一条天气/方向事件路径中，令 `C_k = transparency_k × sky_k / (seeing_k × q0)`，`Z_k = C_k × efficiency_k`，`O_k` 表示该槽开放。目标几何 `H_i(t) = lunar_i(t) / airmass_i(t)^0.6`。

每目标每槽只需两个权重：

```
wB_ik = (1/d) Σ band用120秒积分片 [Δt × H_i(mid)]
wE_ik = (1/d) Σ science用积分片 [Δt × H_i(mid) × D_i(mid)]
qB_i  = Σ O_k C_k wB_ik
qE_i  = Σ O_k Z_k wE_ik
g_i   = min(flux_i × d × qE_i / 450, 1)
u_i   = max(weight_i × program_mult(declared, band(qB_i)) × g_i − best_i, 0)
```

`D_i` 包含方向乘子和闭锁。band 与 science 的切分必须分别保留：官方 band 不受方向事件影响；science 在每个方向事件实际起止处先切分，再以最多120秒片积分。直接复用同一组 midpoint，会在非120秒对齐的方向边界处失去官方等价性。

固定 assignment/program 下，期望 science 是 `Σ E[u_i]`，无需保存目标之间的全部联合分布；但每个目标的 `(qB_i,qE_i)` 联合分布、槽间相关性仍须保留。actor 应先按每个目标的期望收益选 fiber assignment，不能把未来每路径最优 assignment 的值取平均。REQ quota、Jain、信息和 loss 也不允许直接拆成独立目标期望。

这个算子不要求80°，甚至不要求55°。它要求方向路径权重和所覆盖槽的质量分布正确；仰角合法性和实际 fiber hit 仍是独立门检。

## 算子检验与反例

`integral_audit.py` 以正式 scorer 为独立对照：160个构造曝光、480次 program 得分检验，起点仰角30.0648°–89°，24个五槽曝光，106个方向事件边界案例。band 最大误差 `6.66e−16`，factor `2.22e−16`，gain `4.44e−16`。

另用16个独立官方 hashed seeds **869600–869615**、与旧生成器相同的38夜质量配置，产生384曝光/1152次 program 检验，其中160个五槽曝光。起点仰角30.1286°–88.9783°，最大差 `5.55e−16`。这些是 **host scorer 算子** 对照，未构成合法完整 fiber 动作、posterior 校准或生产策略分数；起点30°案例也不意味着目标在整段曝光始终合法。

`counterexamples.py` 保存三个反例：

1. **第五槽不可从四槽精确消去。** 起曝时刻在槽内899秒，时长3600秒。两个合法质量路径前四槽 `C=.65` 完全相同，第五槽 `.2` 或 `1.4`；在同一正式目标几何下，qB分别 `.530711500/.824062862`，最优 program 分别 BRIGHT/DARK。旧四槽输出无法精确表示这两个条件分支；套一条 C 的 AR 均值不提供缺失槽的联合分布。C 是三个裁剪 AR 分量的比值，本身也不是精确的一维 AR 状态。
2. **单 Cbar 与平均 H 不闭合。** 相同 Cbar、两槽 C 顺序互换，使用 `H=.72/.75` 时 qB `.4009/.3991`，BRIGHT/BACKUP不同。这是代数权重反例，没有声称这两个精确 H 数字来自某一个官方 field。旧 `score_token` 对历史使用平均 H 与一个 C/E 的 likelihood 近似；它不保存 H 与槽质量的时间关联。旧路径输出未来积分可精确，不等于历史特征对真实跨槽曝光充分。
3. **closure 和质量各自的边际不够。** C/Z 边际相同、open 边际相同，但把开放状态与高/低 Z 配对，期望 best science gain为 `.1352/0`。旧 NN 的 Gaussian mixture 与16 closure模式各自归一化；这不是任意联合 posterior 的精确表达。该反例证明表达缺口，未证明参考生成器或当前真实前缀上存在这么大的影响。

## 分布饱和断点的时长机制与停止原因

固定同槽、常量几何、给定 program 时，有限路径的 science gain 为分段线性函数；除以 d 后，每个开区间的导数符号固定。最优时长可来自各路径的 saturation 断点，均值模型只保留均值断点。两等权路径 `C=.25/.95, E=.95, H=1, flux=1, weight=1, best=.35` 的60–900秒枚举中，路径期望选 **498秒 DARK**，均值模型选 **789秒 BRIGHT**。这给出了同时改变 program/duration 的机制存在性；该例是在检查五个固定 flux 值后记录的 `flux=1` 构造例，不是预声明或真实world策略收益测试。

完整曝光下还要处理随 d 改变的部分120秒 midpoint、slot/方向边界、离场高度和历史损失 rank。将更多路径断点交给优化器，在方法上仍属于既有随机情景时长机制；本轮停止，不用增加路径数、换分位或调 gate 重复旧路线。

## 冻结 NN 的新独立物理支持审查

使用原 synthetic history 设计，另生成16个同分布官方 seeds **869620–869635**，每world固定抽64个查询，总计1024 queries/524288 sample paths。原 `joint_model.npz` SHA：

`0f83f6d639822c1c72a7c25c13dc2d49fe17519da1e35d6a5cc946c1cc7d4ce5`。

源/模型未改，未做训练或 checkpoint 选择。1987054个 open sampled slots 中，**110316（5.5517%）出现 Z/C>1**；97767条路径（18.6476%）至少有一槽越界。参考 protected-field 模型的 E 限于0.1–1，这些路径不满足物理支持；没有 E<.1 或 C 超物理上限的样本。

这说明 joint Gaussian(logC,logZ) 是近似模型，不能因积分数学等价而称为物理精确 posterior。它 **没有证明生产 regret 或减分**，也不撤销原独立候选 regret 改善。事后 `Z=min(Z,C)` 或把 mean 代入 cap/program/best，会改变概率模型而缺乏新校准；本轮没有这样修模型。

下一次实质不同的模型可以使用受限 E 参数化、联合 closure 与质量、五槽输出，以及实际公开 geometry/hit 的历史特征。训练必须重新锁独立world数据和强策略决策门检；它属于新数据/新表达的研究，不是本轮已完成的改进。

## 完整性与范围

- 原27 source/config、原 fault v1、exact runtime、旧模型均保持；没有候选ZIP/actor改动，因此 false/true report、required、REQ、Jain 和 loss 没有新策略差值。
- 未开900秒季节；未更换为 BasePolicy 对照；未把 toy、host积分或物理支持比例称为强策略/正式隐藏卡收益。
- 首次 `integral_audit` 的 NumPy bool JSON序列化失败保留为 `integral_audit_v1_json_failure.py`。修复仅显式转Python bool，未调整门检或参数；失败日志摘要在 `failure_history.json`。
- 全部复现脚本、锁定新seed域、原始JSON/log与引用源SHA在本结果目录。结果 source manifest 不包含凭据。
