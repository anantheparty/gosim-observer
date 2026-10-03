# 独立安全剪枝与账本压缩：有限族验证完成

先从官方评分器独立推导，再对照自己的已知强轨迹。完整证明在 `proofs.json`，实际计数与耗时在 `summary.json`，源码SHA在 `experiment_source_sha256.json`。

| 本地卡 | 支配后叶数 | B&B剪枝率 | B&B / 穷举秒数 |
|---|---:|---:|---:|
| L1 | 171600 | 70.65% | 9.33 / 6.32 |
| L2 | 161051 | 99.06% | 1.11 / 5.87 |
| L3 | 31104 | 99.74% | 0.072 / 1.23 |
| L4 | 161051 | 98.78% | 2.05 / 5.00 |

规定五阶段、每阶段10个固定中心×3个program及empty，共31^5=28629151原始序列。program分数向量支配先减少约99.4%–99.9%；总计524806个保留族叶子全穷举，53016个内部上界零违例，B&B与穷举最优一致。原始三阶段族另穷举119164序列，支配前后最优相同。最佳序列经官方runner完整结算一致。L1界计算开销高于收益，是明确负结果。

Jain的连续区间最大值使用 `x=clip(c,l,u)` 与 `sum(x²)=c sum(x)`：任意区间内y满足 `(x-c)·(y-x)>=0`，结合Cauchy给 `Jain(y)<=Jain(x)`。整数可达计数落在该连续箱中，因此可用于乐观上界；没有假定覆盖更多使Jain单调。400个随机整数箱、8119个整数向量另经全枚举验证。

存活签名账本压缩保留每target科学max、rawfactor完成门槛、REQ窗口完成门槛，并保持原动作编号/数量。L1观测13587→8287；L3前缀8635→6597，检查214个未来trigger的冻结N；L4前缀6436→5899，检查174个N。N是loss触发时已完成observe数，多个未来loss必须使用N tuple，不是季末总数。结果在 `ledger_compression.json`。

**范围：规定中心和assignment的有限动作族、空起始ledger、已知本地truth、REQ2夜的post-loss条件、无报告与无后续排程。** 不能外推剪枝比例到连续全局动作空间，也没有生产高分改善或云隐藏卡上界。未知天气在线状态还须包含信息/信念及仪器状态；单有ledger不充分。

```sh
.venv-solver/bin/python formal_v4/research/cold_pruning_proofs.py
.venv-solver/bin/python formal_v4/research/cold_pruning_ledger_audit.py
```
