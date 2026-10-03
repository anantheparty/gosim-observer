# 公开 E/W 边界审计与多次自身运行的条件合并

## 公开规则能否保证额外边界

检查当前下载的公开 `participant-guide.zh.md`、`v4_scorer.py`、`v4_config_check.validate_scenario` 及公开 scoring 配置，**没有找到普适的 E 正下界或 W 数值上界**。这是对这些公开来源可推出事实的结论，不能代替主办方其他未发布的生成配置。

- Guide 第 202、426 行只说明 seeing/transparency/sky_quality/efficiency 的意义及预报不含数值；第 544 行说明成功 report 修复仪器故障、不能消除地震损失。没有最差效率或最小 seeing 的常数承诺。
- Scorer 的 `_apply_fault` 第 234–246 行只对“当前仍处于 active fault 且已修复”的效率作 `min(1, efficiency/fault_multiplier)`，不提供正下界，也没有把未处于该分支的所有 slot 效率统一 cap 为 1。
- `band_quality` 第 250–287 行直接使用 `transparency*sky_quality/seeing`。没有 clip W、B 或 q 到 1。完成因子的 `min(...,1)` 只 cap factor，不能推出 W 或 B 的 cap。
- Validator 第 227–263 行检查 slot 顺序与持续时长、事件时间和公开参数一致性，没有验证天气数值的 E 正下界、seeing 正下界或 W 上界。这里没有调用 scenario 构造或读取它加载的隐藏文件，也没有读取生成器。

因此以前 `Z<=3` 或 `E<=1` 等参考域假设必须保留其条件性质，不能从“效率通常是百分比”或 report 成功提升为任意 slot 的正式数学保证。

## 小型反例与可识别性

脚本只构造人工 `SlotTruth`，没有构造真实 task：保持透明度与 sky_quality 为 1，设 `seeing=1/W`。两组正参数：

| W | E | 同一几何的 B | 同一几何的 clean q |
|---:|---:|---:|---:|
| 1 | 0.001 | 1.349255809605 | 0.001349255809605 |
| 1e9 | 1e-12 | 1.349255809605e9 | 0.001349255809605 |

官方 scorer primitive 接受这些人工正参数，两组 `E*W` 相同、q 相同，而 W/B 相差十亿倍。取 `E=ε` 或 `seeing=ε` 的参数族，可令 E 任意接近 0、W 任意大。这个反例说明 **scorer 自身不包含相应普适边界**，不声称真实生成器会生成这些值。

方向遮挡、关闭或几何 miss 可以令原 q/score 为 0，但 band 不含方向遮挡与效率。这样的零质量记录不能作为 `Z=E*W=0` 方程，更不能据此给 W 一个零上界。只有已经证明方向净空、整段可见且正质量的原测量，才可进入 clean Z 反演；之前的净空证明仍依赖明确的参考方向几何范围。

## 正确结合 Z 与 W 所需的最小信息

W 保持原 900 秒 slot；Z 可以在 repair 时刻细分，且每个 Z 子 cell 归属某个原 W slot。不能把二者数组按相同 index 直接相除。

若官方或可验证的机制给出每个干净 Z 子 cell 的 **有效**效率界 `0<e_min<=E<=e_max`，且 clean Z 外区间为 `[z_lo,z_hi]`，那么所属 W slot 才能加入：

```text
W_slot >= z_lo / e_max
W_slot <= z_hi / e_min
```

同一 W slot 的所有 repair 子 cell、所有可合并运行都取交集，再与 band 标签的不等式/析取相交。有限的 `e_max` 只给 W 下界；要从有界 Z 推 W 上界，必须有**严格正的 e_min**。另一种足够的信息是官方直接给定 W cap，或独立给定 seeing 最小值以及 transparency、sky_quality 最大值；还必须保证所有适用事件后该边界继续成立。

如果能给出某段稳定且已标定的 E 精确值，Z 即可直接标定 W。report 成功只证明故障被修复，并不报告恢复后的 E 数值，所以不满足这项条件。

## 同队多运行的有限一致性

新取回的 Verified Portfolio α/β/γ 与之前 Phase α/β/γ：

| 卡 | 完全相同且时刻相同的 observe 前缀 | 相同目标/曝光起止的记录 | 相同 declared 下 prog_mult 不同 | 匹配 q 最大差 |
|---|---:|---:|---:|---:|
| α | 24 | 415 | 0 | 0 |
| β | 278 | 4384 | 0 | 0 |
| γ | 334 | 5007 | 0 | 0 |

共享 bulletin/forecast 内容差异均为 0，完整 scenario YAML hash 相同。**所有这些相同测量都在双方 repair 差异发生前**；repair 差异间隔及双方修复后没有相同目标/曝光起止记录，因而它们不能额外验证修复之后的质量或整季未观测天气一致。

从 scorer 公式可知 repair 时间改变不会改变某一给定 W 真值的 band 矩阵，所以数学上无需排除 repair 时间差异来合并 W 标签。但跨运行“给定的是同一个 W 真值”仍然需要额外身份承诺或测量证据。相同前缀和消息只能支持有限一致性，scenario hash 不覆盖 weather truth；不自动将两套未来 W 标签变为同一个正式可行域。

## α 条件合并实验

明确假设同卡四次运行的 W 真值相同，合并 CD2/Phase/Request/Verified Portfolio α 自己输出中的 **57250 条凸 band 不等式**（4193 条 BRIGHT mismatch 精确析取只记录、未进入凸 LP）。没有给 W cap；没有加入任何 repair cut。

联合凸 LP 可行，finite-upper W cells 从 **365 增至 492**；仍有 **760 个无上界 cell**。这只是该共享 W 假设没有被当前凸条件反驳，不能证明实际整季真值相同或未编码析取联合可行。

对当前 192 个 α coupon、2523 个分配目标，所有 B 上界仍然无穷，DARK 没有被排除，科学上界减少量仍为 **0**。因此增加这几次自身运行的 band 标签，依然不能解决当前 coupon 的上界宽松；此前的无上界方向证明仍适用。

## 文件与复现

```sh
.venv-solver/bin/python formal_v4/research/public_W_bounds_and_merge_audit.py
```

`summary.json` 保存反例、运行匹配、repair 时间、有限界数量及所有自身输入/公开来源 SHA。`conditional_shared_alpha_W.npz` 保存条件合并矩阵与 W box；`alpha_coupon_bounds.json` 保存 candidate B 界。所有结果是独立研究，没有产生新调度、比赛分数或全局最优声明，也没有修改生产策略、ZIP 或 Git index。
