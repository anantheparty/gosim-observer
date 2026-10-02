# 公开目录的 seed 可恢复性：限时 pilot

2026-10-03。只读已下载的 α–δ 六个 public/config 文件和官方公开源码，未读取卡片 truth、服务器私有文件或探测接口。代码 [public_seed_audit.py](public_seed_audit.py)，机器结果 [public_seed_audit_summary.json](public_seed_audit_summary.json)。

**结果：找到了一个廉价且可验证的公开目录指纹，但指定的窄候选集没有 seed 匹配。**这不能证明官方 seed 高熵，也不能证明更大空间不可恢复。当前没有由公开资料恢复 α–δ 隐藏天气或请求的结果。

## 1. 为什么六个文件不能直接完整重生成云端目录

六个文件公开了目标坐标、类别、flux、科学权重、required、footprint、日历、站点、仪器和评分；不包括 `v4_catalog_config.json`、`v4_weather_config.json` 或 master seed。官方 [`scripts/build-v4-practice-cards.py`](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/scripts/build-v4-practice-cards.py) 明确说明真实练习卡使用秘密种子，生成器输入不在公开仓库。

可直接确定的部分：

- 目标人数、每类人数、required 人数；本次 α–γ required 比例 .05、δ 为 .06。
- 观测 season、站点、最低高度、太阳门槛、footprint 顶点序列。
- 每张卡都有 3 个 footprint component，每个 40 个顶点。
- science_weight 已公开，不需要推断。

仍缺少的生成参数包括：完整中心候选池及其原始顺序、生成范围/面积配置、簇中心数量、混合比例和宽度、精确 flux 分布参数、最低有效观测窗口与拒绝条件；天气/事件/请求配置也不在六文件中。经验上估计这些参数并不能保证重生成第一目标的随机消费路径一致。因此不能把“参考配置能产生相近统计量”宣称为恢复实例。

但这些缺口并不阻止建立更早、更小的 fingerprint。

## 2. 从 footprint 恢复 RNG phase 指纹

官方 [`v4_catalog_generator.generate_footprint`](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_catalog_generator.py) 对一个 component 的顶点半径使用：

```text
rho_j = scale * cap_radius * [1 + sum_k a_k*cos(k*alpha_j+phase_k)]
alpha_j = 2*pi*j/Nvertices
phase_k = rng.uniform(0,2*pi)
```

顶点 0 沿中心正北，因此它的 RA 就是中心 RA。四分之一圈的顶点沿正东，其向量在中心和东西切线构成的平面上，故中心 Dec 满足：

```text
tan(center_dec) = tan(quarter_vertex_dec)
                 / cos(quarter_vertex_ra-center_ra)
```

由公开顶点求出中心后，算球面中心角序列 rho。FFT 的第 k 个复数 Fourier 系数的角度即 phase_k；面积整体缩放和 amplitude 的大小不改变 phase。

本次四卡所有 component 的第 1–3 阶幅度显著；第 4 阶以上仅约 1e-8，确认公开形状与三阶谐波一致。中心 Dec 距离两位小数的设计值均小于约 5e-7 度。

| 卡 | 按公开 component 顺序恢复的中心（RA,Dec） |
|---|---|
| α | (79.82,-17.30)、(350.32,-17.30)、(26.82,-50.40) |
| β | (94.61,-14.20)、(356.11,-25.10)、(40.51,-54.10) |
| γ | (337.25,-18.60)、(45.75,-56.90)、(76.25,-15.40) |
| δ | (64.78,-57.70)、(107.58,-11.00)、(7.28,-17.20) |

seed 候选无需生成全部目标：先执行 `rng.sample(center_pool,3)`，然后依次抽取每个 component 的 3 个 phase 和 3 个 amplitude，共 18 个浮点随机值。比较恢复的 9 个 phase 即可筛掉候选。中心值、面积、amplitude 配置均不影响该段 RNG 消费；候选中心池大小仍会影响 `sample` 的随机消费，因此需要列为测试条件。

若 phase 匹配，还可继续用公开类别人数重建 class roster 的 shuffle，并比较整个 target_class 序列；随后 required 的抽样集合也可精确比较。这些步骤发生在簇中心、坐标和 flux 抽样之前，不依赖后半段目录生成参数。

## 3. 已知公共种子的正对照

使用官方公开 demo（不是 α–δ 或正式卡）的 seed **5021**、完整公开 CATALOG 配置以及现有 demo public 文件。源码 [`scripts/make_v4_demo_card.py`](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/scripts/make_v4_demo_card.py)。

结果：

- 从 6 位小数的 footprint 坐标恢复 phase，最大误差 **3.50e-7 rad**。
- 继续 RNG 消费得到的全部 **2400 个类别**与 CSV 完全一致。
- required 抽样集合与 CSV 完全一致。
- 用官方 generator 重生成第一目标完全一致。
- 重生成的整个 `targets.csv` 和 `footprint.csv` SHA-256 与公开 demo 完全一致。

因此这个 fingerprint 在已知公共实例上经过了实际验证，没有依赖真实卡片的未知 truth。

## 4. α–δ 的窄扫描结果

固定审计的源码 commit 为 `e01939d060f304c2a7cf04d9b3e46009b564fc23`。本次条件：

| 参数 | 测试范围 |
|---|---|
| master seed | 整数 0–10000，以及 37 个额外公开日期/月候选 |
| 总 seed 候选 | **10038** |
| 中心候选池大小 | **3–16** |
| component/harmonic 数 | 3/3，由公开 footprint 确定 |
| seed 模式 | SHA-256 派生 `sha256-v1`，以及 legacy 直接 seed |
| 比较 | 每卡全部 9 个 phase，允许最大误差 1e-4 rad |
| 总 card signature 检查 | **1,124,256** |
| seed 匹配 | **0** |
| 普通 CPU 总耗时 | 初次 **8.361 秒**，含正对照重生成 |

额外日期包含 2026-10-01 至 10-31、公开 demo/reference 的日期数字和 L1–L4 已公开的起始日期。完整候选列表及文件 SHA 在机器摘要中。

“无匹配”只排除了上述候选集、中心池大小和同版本 RNG 消费模型的组合。其他 master seed、其他中心池大小、其他生成实现/版本、额外随机消费、非标准 phase 算法均不在排除范围内。没有熵证据时不能改写为“随机数不可破解”。

## 5. 当前结论与下一步门槛

这个扫描已经比完整目录逐 seed 重生成便宜很多；当前没有必要先把它迁移到 GPU。继续扩大搜索须有新的可检验依据，例如主办方公开生成规格、某个更明确的 seed 范围，或公开实例验证的额外消费路径。仅凭日期直觉扩大未知空间，不能保证得到天气真值。

即使有 catalog seed 候选，也须先验证完整 public signature 和目录一致性；随后天气流仍需要相应生成配置。`sha256-v1` 将 catalog、天气、事件和请求分流，catalog MT 状态本身不能直接推出其他流。

在候选集未命中之前，已经确认可用的规律是强 AR 相关天气、确定性的粗公告/预报、分层事件时间先验及公开 score 反演。它们可直接进入当前策略并由本地/线上得分验证，无需假定已恢复秘密种子。

复跑：

```sh
python3 formal_v4/research/public_seed_audit.py \
  --official-repo /tmp/gosim-generation-audit-20261003 \
  --cards formal_v4/practice_cards \
  --out formal_v4/research/public_seed_audit_summary.json
```

脚本只读取 public/config 与官方 demo 公共配置，临时正对照生成目录在结束时自动清理。
