# 有限历史质量先验：卡识别、反馈门与批量列报价

## 当前完成的核心

独立模块 `quality_profile_prior.py` 已通过小门检，未接生产 agent，未改当前上传包/服务/Git index，也没有网络、GPU choose 或整卡回放。只使用公开六文件、本队已完成输出中反演出的**窄区间**，不载入插值或未收敛 NNLS 曲线。

四卡压缩数组各 20–24 KB，registry 记录来源 SHA。默认只匹配公开身份**不会启用**历史质量：还需当前显式 clean 的正反馈与有限 unit-ratio 区间相容。维修、冲突或无支持时回退。

所有 `lower/upper/point` 都带预测先验范围；不是隐藏未来真值或无条件比赛上界。此前两轮 28,306 行相容提供了经验支持，正式刷新仍要重新检验当前 realization。

## 1. 公开身份的两个 digest

registry 分别保存：

1. 六个已下载公开文件逐文件 SHA，排序后 aggregate digest：scenario/fiber/score JSON 与 targets/footprint/night calendar CSV。
2. `initialize` 可见信息的 canonical semantic digest：完整目标及 required/flux/weight、footprint、夜历窗口/id/date/count、site/min-alt/sun-limit、fiber field/exposure、scoring。

在线严格匹配 semantic digest，并核验压缩 profile SHA；catalog 任一 RA 改变 0.01°会拒绝。任务卡名称仅作显示，不作为身份凭据。

不能从 initialize 重建六文件原始字节：solar dusk/dawn、scenario 产品路径等没有发布到协议，因此不能声称在线验证了 raw aggregate digest。即使六文件都相同，也仅说明公开实例身份，没有证明引用的隐藏天气/故障 realization 相同。

## 2. 有限先验与维修门

只载入 `cell_start/end/lower/upper/support`。每 cell 必须有测量支持、非矛盾区间且宽≤1e−4；夜间之外、宽区间、未观测槽返回 NaN，不插值。

每个 source cell 隐含旧 effective E 的维修 epoch。调用 `note_report(moment, correct=True)` 只记录当前已经确认的正确维修。报价未来时只知道当前 `now` 前已确认的报告；旧 cell 的维修序号与当前已确认序号不同则拒绝。**不假定未来一定会报告修复。**

这也拒绝“当前修得比旧版早，但旧 cell 尚未修”的差窗口。正确 report 会清除 live compatibility 门，重新等待当前反馈。相同维修序号只是使用先验的必要条件，没有证明故障身份或基础天气相同。

模块不把旧 Z 除以拟合的 E，不恢复 W，也不宣称分别估出了 E、透明度、seeing。

## 3. 当前 score-only 反馈检验

官方在线 hits 只提供 target/score。给定目标 weight、flux、实际曝光时长和声明 program，对每条显式 clean hit 枚举两个真实可能倍率：声明匹配倍率或 mismatch。未封顶分支反推当前 q 的舍入区间，与旧预测 q 区间相除，得到 `q_current/q_old` 的区间并集；跨 hit 求并集的交集。

封顶分支只给下界，不凭它启用先验。只有交集中**有限**区间包含 1 才允许启用。这个量是 effective profile 比例，不能区分天气、E、残留方向污染或 band 歧义，因此没有向未来传播一个“新 E 倍率”。

`clean_mask` 默认全 false，由调用方提供已检查的当前方向条件；没有这个显式条件就没有自动校准。若当前 clean 正反馈排除了 unit ratio，关闭 live gate，禁用此次曝光触碰的所有 source cells，让调用方用现有 belief 回退。没有为了凑一致而调大误差、重新拟合或插值。

仍属经验兼容检验，不能从有限反馈证明全部未来 realization 相同；后续每次可用反馈应继续检验。

## 4. 批量列报价接口

```python
registry = ProfileRegistry('.../quality_profile_prior_data/registry.json')
prior = registry.identify(initial_payload)  # unknown -> None
prior.note_report(utc_seconds, correct=True)

check = prior.feedback_ratio(
    start, actual_duration, target_indices, hit_scores, weights, flux,
    declared_program, clean_mask=checked_clean_mask)

values = prior.price_columns(
    starts, durations, target_indices, now=utc_seconds,
    program=declared_programs, direction_scale=conditional_clear_scale,
    fallback_Z=caller_belief_Z)
```

- `starts/durations` 形状 K，`target_indices` 形状 K×F（一般 F=16）。统一 UTC 秒；必须全部处于同一各自夜间窗口，不能跨白天。指向、fiber 合法性、整段最低高度由列生成器检查。
- 几何分段严格按官方 900 秒槽与≤120秒中点；paired H 计算是 K×F，不产生 K×(KF) 全配对大矩阵。
- 输出 `supported_column[K]` 与 `quality_lower/upper/point[K,F]`、`factor_lower/upper/point`、`base_science_lower/upper`。
- `direction_scale[K,F]` 范围 [0,1]，是调用方明确的整曝光条件模型；静态地形/临时方向事件若需要逐 piece 变化，须在下一版逐 piece callback/device tensor 集成，不能称当前常数 scale 是精确 terrain 积分。
- unsupported bounds 为 NaN；若给 `fallback_Z`，只产生 fallback 点预测，不产生伪界。当前 helper 完全不推断 program band。

### 科学增益不能使用 Z 判 DARK

program band 积分的是 W=τK/seeing，不含 E；Z=E·W 不能直接确定 DARK/BRIGHT/BACKUP。给定 declared program，真实倍率只可能是声明匹配倍率或 mismatch。因此 helper 返回科学贡献的两端：

\[
w_i\,g_{i,\mathrm{lower}}\min(m_\mathrm{declared},m_\mathrm{mismatch}),\qquad
w_i\,g_{i,\mathrm{upper}}\max(m_\mathrm{declared},m_\mathrm{mismatch}).
\]

若不传 program，用全部公开 program 倍率的最小/最大值。相对于已有效 best(i)，单列科学增益两端是 `max(0, contribution_bound-best(i))`。跨多个列对同目标只能最后取 max，不能把独立增益重复累加；全季数学模型需以 target cap/coverage 变量处理。

required/request 只依赖单次 raw factor，不依赖 program 或是否曾有 .49。列能否完成应比较整个该次 factor 与对应阈值，不能累计补差。

## 5. 独立门检与 CPU 预算

`quality_profile_prior_checks.py` 验证：四卡身份匹配；篡改 catalog 拒绝；身份本身不激活；clean 正反馈相容激活；冲突回退；维修差 epoch 拒绝；正确报告重置兼容；paired H 与原公共实现误差 0；批量积分与逐列原实现最大误差 3.33e−16。

本机 CPU、随机 60–3600 秒列、每列 16 个目标的批量报价：

| 列数 | target integrals | wall time | 输入数组 |
|---|---:|---:|---:|
| 100 | 1600 | 6.19 ms | 14.4 KB |
| 1000 | 16000 | 27.2 ms | 144 KB |
| 10000 | 160000 | 274.5 ms | 1.44 MB |

识别与加载四卡约 27–32 ms，各 profile 20–24 KB。按本次大批吞吐外推，一百万列的几何报价约 27 秒（不是完整全季求解耗时）；列生成、合法指向、regret、DAG/MIP/定价迭代另计。对 900 秒整卡预算，可以在初始化缓存一次大批候选，然后只对反馈影响的 frontier 重报价。此基准没有声称候选本身全部 fiber/高度合法。

## 6. GPU 后续接口设计

尚未调用 GPU 或改服务。可复用相同 contiguous 输入协议：starts/duration FP64，target_indices INT32 K×16，RA/Dec/flux/weight 数组，约 1,200 个 profile cell 的 start/end/bounds/support/维修 epoch，以及列级 program、方向 scale 与 dual price。

GPU kernel 按 `(column,target)` 独立遍历≤120秒子段，slot 900 秒边界计算、cell 二分查找、paired sun/moon/airmass 几何、支持/维修检查后，累加 raw quality 区间并封顶 factor；program 只用公开匹配/mismatch bound。可输出每列 reduced-cost 或 mask coverage，仅把正定价/最优若干列回传。物理几何与正式舍入门检先用 FP64；降精度须按误差预算单独证明。

若每次仅 1000 列，CPU 已约 27 ms，GPU 网络/模型 API 开销可能更大。应在跨夜全局定价的万级/十万级批次才比较 GPU 端到端成本；未经基准不承诺加速倍数。

## 产物

- `quality_profile_prior.py`、`quality_profile_prior_checks.py` / `_checks_result.json`。
- `quality_profile_prior_data/{registry.json,alpha.npz,beta.npz,gamma.npz,delta.npz}`。
- 本文，独立 helper gate，无全季策略变更。
