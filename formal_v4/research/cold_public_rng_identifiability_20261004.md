# 公开随机流的可辨识性审计：有限域盲恢复与生成器原生反例

2026-10-04。正式公开源码锁为 `e01939d060f304c2a7cf04d9b3e46009b564fc23`。本轮只写本文与 `formal_v4/results/cold_public_rng_identifiability_20261004/`，只在本机做小型 CPU 实验，没有线上动作、GPU、SSH、真实季节或全局得分上界计算。

**结论：SHA 命名分流没有目录状态到天气状态的直接转换，但同 master 的各流仍有确定性联系，不能称为信息论完全脱钩。** 在已知的小 master 域、完整生成配置和相同源码/runtime 下，可以由公开目录恢复 master，再精确预测其他流；本轮新的 blind 合成实验已验证这个条件命题。另一条官方构建路径允许 weather 使用独立 seed；本轮用该生成器实际产生两个公开输入和过去反馈相同、下一曝光得分不同的世界，证明那一模型中 future weather 不可由这些公开量唯一识别。

实际 α–δ 没有恢复结果。六个公开输入没有 master、seed 域或完整 catalog/weather 生成配置；实际卡是否使用同 master、哪个构建路径和哪个生成 runtime，也未被本轮确认。不能把下面的合成成功移植成实际天气已知，也不能把合成反例升级成所有同 master 实例均不可恢复的证明。

## 1. 来源和读取边界

原位置 `formal_v4/runs/official_generator_e01939d0/` 不是独立 Git checkout，`git rev-parse HEAD` 会返回父仓库的 `6dceb0d…`。因此没有以目录名或父仓库 HEAD 认证源码。本轮从官方公开 GitHub 的固定 commit 下载 24 个 source/reference 文件到自己的 `official/`，与本地对应文件逐字节比较，**24/24 相同**，逐文件 URL、SHA256 和长度保存于 [source_manifest.json](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_public_rng_identifiability_20261004/source_manifest.json)。参考配置是官方公开样例，具有已公开的参考 seed；没有读取实际卡的原始生成 seed/config。

源码定位时用旧报告的 `rg e01939d0` 检索找到路径，检索结果带有少量既有结论。完整正式源码审读先于后续整篇报告查重，但本轮不能描述为对既有结论完全盲的冷读发现。下文的 **blind** 只指新合成世界的种子与未来标签在恢复器预测冻结前被隔离。

审读包括 contracts、catalog/weather/request generator、bundle、v4 scenario/workflow、runner/scorer 和旧 `scenario_builder`。旧 builder 是 `example3` 的 tiles/weather layout，并会把 seed 写入旧 manifest；正式 v4 bundle 的公开初始化没有此字段，不能跨格式套用旧泄漏。参见 [旧 scenario builder](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/scenario_builder.py#L61)、[v4 bundle](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_bundle.py)、[v4 初始化](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_workflow.py#L112)。

查重读了 `ALGORITHM_PORTFOLIO_ZH.md`、`GENERATION_MODEL_ZH.md`、`PUBLIC_SEED_AUDIT_ZH.md`、`GPU_PUBLIC_SEED_MODEL_ZH.md`、`cold_public_rng_20261004.md` 和 generator_forecast 的模型源码/汇总报告。没有打开既有 prediction 标签、实际 truth、L4 sealed teacher、private factor/quality/prog_mult/valid 表、实际故障/私有事件日期、浏览器凭据或平台私有 API。查重来源 SHA 见 `dedup_source_manifest.json`。

## 2. PRNG、子 seed 和依赖关系

官方 contracts 定义

```text
h(m, stream) = big_endian_integer(SHA256(UTF8(str(int(m)) + ":" + stream))[0:16])
R_stream = random.Random(h(m, stream))
```

没有选择 `sha256-v1` 的历史配置则用 `m + legacy_offset`。每个 `Random` 对象有自己的状态；不是在一个巨大共享 RNG 中跳过固定段。依据：[contracts.py:28–52](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/contracts.py#L28)。

| 对象 | seed 来源/流 | 还依赖什么 |
|---|---|---|
| footprint、类别 shuffle、required 抽样、簇中心、目标坐标、flux | `h(M_C,"v4.catalog")`，同一 RNG 顺次消费 | catalog 完整生成参数、站点和几何拒绝条件 |
| 背景质量、背景关闭、效率 jitter | `h(M_W,"v4.weather.slots")` | calendar、quality/closure 参数；全局事件和地震 effects 进一步影响输出 |
| 五类天气事件 | `h(M_W,"v4.weather.events")` | 事件次数、时长、scope 等参数；五类共用这一个流 |
| 火箭、地震、地形、故障 | 分别为 `v4.rocket_launch`、`v4.earthquake`、`v4.terrain`、`v4.instrument_fault` | 各自 family 参数、calendar |
| 丢失区间、固定 pointing offset | `v4.stress.data_loss`、`v4.stress.pointing_offset` | stress 配置；after_earthquake trigger 还依赖 quake 输出 |
| 请求成员 | `h(M_C,"v4.observation_requests")` | 已公开的 catalog、calendar、几何和未公开的完整 request settings |
| bulletin、forecast | **不产生新的随机数** | 上述事件/effects 的确定性粗投影与 publication 配置 |
| 曝光反馈/终局结算 | **scorer 不生成随机数** | 已生成 hidden 状态、公开动作/几何/评分配置、修复及有效历史 |

流定义和消费顺序来自 [catalog generator](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_catalog_generator.py#L725)、[weather generator](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py#L491)、[request generator](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_observation_requests.py#L155)。请求只检查公开目标和窗口几何，不读未来天气；其被选成员不会成为天气流的 raw sample。

两条构建路径不能混同：

- `build_card_bundle` 显式令 `M_C=M_W=spec.seed`，catalog/weather 均为 SHA-v1，要求 hashed seeds；requests 接收相同 seed。
- `build_spec_bundle` 使用 catalog/weather 配置各自的 seed，把 catalog seed 给 requests；cross-check 检查站点/季节等，但没有要求两 seed 相等，也没有在此调用中强制 hashed 模式。本轮反例主动把二者均设为 SHA-v1，只改变 `M_W`。依据：[bundle:38–104](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_bundle.py#L38)、[cross-check](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_config_check.py#L49)。

因此“独立 RNG 状态”是源码事实；“实际卡独立 master”不是已确认事实；“同 master 的各流统计完全独立”也不是数学事实。事件影响 weather output、quake 影响 loss trigger、catalog 影响 request 资格，都属于可见的跨模块依赖。

本轮运行的 CPython 是 **3.10.12**。相应 `random.py` 与 `_randommodule.c` 也从固定官方 tag 归档并记 SHA。MT 使用 624 个 32-bit word 的存储状态与 index，周期为 `2^19937−1`；Python state 还包含 `gauss_next` 缓存。`random()` 用两个 word 的高 27/26 位构造 53-bit float，舍弃低 5/6 位。完整 32-bit 连续输出的 MT state recovery 与本问题的 rounded 几何/score 观测不同。源码：[CPython 3.10.12 C 实现](https://github.com/python/cpython/blob/v3.10.12/Modules/_randommodule.c#L153)、[Gaussian 缓存](https://github.com/python/cpython/blob/v3.10.12/Lib/random.py#L591)、[Python 文档](https://docs.python.org/3/library/random.html)。实际卡生成 runtime 未知，其他 `sample`/分布实现的版本消费差异必须保留为模型条件。

## 3. 可观测量、舍入和熵

令 `P` 是合法公开初始化，`H_t` 是到 t 已发布的 bulletin/forecast/request、自己的动作和反馈；`θ` 包含 master(s)、生成参数和运行规则。精确 future 可辨识要求

```text
O_t(θ1)=O_t(θ2)=(P,H_t)  ⇒  Future_t(θ1)=Future_t(θ2)
```

即 future 在每个公开观测等价类上为常数。seed 恢复比 future 恢复更强：可能多个 seed 相同未来，也可能无需唯一 seed 就能确定某个 forecast-supported event-night 命题。仅报告“seed 候选剩几个”不能代替相应 future 命题的检验。

| 公开量 | 保留的信息 | 不能直接恢复的量 |
|---|---|---|
| site/calendar/instrument/scoring | 几何、时间及评分映射；calendar 本身无 RNG 调用 | 不提供公开 master 域；不等于完整 weather/catalog 生成配置 |
| targets/footprint | 坐标、flux、class/required 序列约束 catalog 流 | 坐标/顶点 6 位、flux 8 位小数；拒绝采样、shuffle、Gaussian 缓存使消费步数复杂 |
| bulletin | 当前 coarse kind/direction，terrain 首条一次，重复 kind/direction 去重 | 数值天气、精确边界/强度；fault 完全不发布 |
| forecast | coverage 内 forecastable 事件的确定 night 支持 | 精确 slot 时刻/扇区/强度；quake、fault、背景关闭不在 forecast |
| observe feedback | hit 的 target_id 与六位小数 score，以及 hit_count 等 | raw factor/quality/prog_mult/valid 不在普通反馈；score 的饱和、未知 program match、积分与乘积产生多对一关系 |
| report/request/resync feedback | 当前故障报告正确性、成员完成状态、已经触发的失效窗口等 | 不提供未发生流的连续 raw PRNG 输出 |

字段与舍入依据：[catalog serialization](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_catalog_generator.py#L75)、[publications](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py#L872)、[score integration](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_scorer.py#L319)、[score-only last_result](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_runner.py#L820)。

舍入和非线性使直接 untemper 不适用，但**不能据此断言没有 seed 指纹**。footprint 的少量谐波 phase 正是已有便宜指纹；大量公开输出可以筛掉一个有限 seed 字典的大部分甚至所有错误候选。本轮也在一个预声明有限域内得到唯一候选。

若同 master 为随机变量 `M`，则任一子 seed 的熵不超过 `min(H(M),128)`，全部子流的联合熵也不超过 `H(M)`，不能把十个流当成新增 1280-bit entropy。MT 存储字数和周期同样不等于实际 seed entropy。SHA-v1 的 128-bit 截断有碰撞可能，seed→state→rounded 文件也可能多对一；没有源码承诺映射在所有非负整数 master 上单射。

恢复完整 catalog 状态不会自动给出 weather state，也不会把 SHA 逆像变成一次 `+1000`。但是如果 `M` 只取公开已知集合 `D`，可枚举 `h(m,"v4.catalog")` 并验证公开指纹；若 `D` 内唯一且其他生成参数/共同 master 关系确实已知，即能预测全部流。SHA 对高熵/未知域的计算隔离需要密码学及分布前提，不能证明信息论独立；反过来，大量公开约束理论上足够区分候选，也不能证明有便宜的求解算法。实际种子的分布、min-entropy、范围及配置域均未公开，**本轮没有赋予它们 32、64 或 128 位的实际熵值**。

## 4. 预声明 blind 合成恢复

这不是此前已知 public demo seed 的复现。协议、fixture、配置及恢复/评估源先冻结，然后 organizer 脚本用 `SystemRandom` 取 **12 个域内** seed 和 **4 个域外** seed，并打乱为 opaque world ID。恢复器只读自身合成的 public footprint/targets/calendar 和完整 **nonseed** 合成配置，不能读取 synthetic world/spec/truth 或 sealed label。预测文件冻结后才由单独 evaluator 打开这些新造的 labels/truth。输入读取 audit、冻结 SHA 与全部候选保留于 `blind_predictions_frozen.json`、`EXPERIMENT_SOURCE_LOCK_BEFORE_SAMPLING.json`、`FINAL_VERIFICATION.json`。

冻结条件：候选 `D={0,…,1023}`；域外 seed 从 `{1024,…,2047}` 取；两 RNG root 为同 master；SHA-v1；固定 31 夜、96 targets、两组件/24 顶点和显式合成配置。完整配置是本实验人为给定的知识，**不声称实际卡使用 reference defaults**。各天气 family、rocket、quake、fault 均有一次事件，stress 打开，两条 request；不只预测一个人工随机数。

恢复器枚举 1024 个候选，使用正式 generator 生成六位小数的 footprint CSV，以 SHA256 作字典索引。1024 个 rounded footprint 全部不同，无候选生成失败。12 个阳性世界的候选全部唯一且 master 正确；预测冻结后额外逐字节确认相应候选 CSV 与 blind public CSV 完全相同。独立 evaluator 对 CSV scalar serialization 做必要规范化，逐字段比较预测与合成真值。

| 预声明项目 | 结果 |
|---|---:|
| master 候选 | 1024 |
| rounded footprint 碰撞/候选失败 | 0 / 0 |
| 域内 blind root 恢复 | 12/12 |
| 每个域内世界 future weather slots | 919 行精确相同 |
| events、earthquake effects、stress、requests | 12/12 世界的五项 future comparison 全部相同 |
| 域外世界 | 4/4 无候选并 abstain |
| 核心 CPU 枚举及预测时间 | 1.471 秒 |

完整正负世界、所有候选、预测、标签和生成错误状态见 [blind_evaluation.json](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_public_rng_identifiability_20261004/blind_evaluation.json)。16 个世界均成功生成，没有删除负例或调阈值。本轮没有训练或选参；12 个域内世界都是恢复器未见 labels 的 holdout。这个 10-bit 域中唯一指纹确实把条件熵降到零；它不能外推到未知实际域，也不是 MT state 恢复或实际 weather 预测性能。

复现顺序为 `fixture.py` → `generate_blind.py` → `recover_blind.py` → `evaluate_blind.py`，必须在一个新的输出副本中运行以保留本次归档。合成 labels/worlds 目录均明确带 `SYNTHETIC` 标识；这些 truth 是本轮自己新造的，而非实际卡 truth。

## 5. 同公开输入、同过去反馈、不同 future 的原生反例

冻结反例使用官方 `build_spec_bundle`：catalog seed 固定为 **7**，weather seed 在 **100…131** 中按预声明规则选择。两者均 SHA-v1；所有 event counts 为零，terrain 为 `[0,0]`，stress 关闭，request count 为零；quality 和效率为常数，背景关闭的 start/reopen 概率为 `.2/.5`。zero sigma 仍消费相应 Gaussian RNG；没有人工编辑输出 truth。此配置通过官方 generator、bundle、scenario 验证。

预声明规则要求首四槽共同开放，在第 5–12 槽内首次出现 hidden openness 差异；取首个字典序合格 pair。完整保留 32 seed 的前缀状态与全部 496 pair，而非先找到好结果再指定 pair。选择结果为 `M_W=100` 与 **104**，在第十槽首次不同。

实际生成的两 bundle 的 **3 个 config 文件与 5 个 public 文件全部字节相同**，包括整个合成 season 的 bulletin/forecast；initialize 完全相同。用一个公开几何决定的相同动作带，经正式 runner/fiber/scorer 执行每槽 60 秒单 fiber 曝光和公开 wait。分岔前所有 decision snapshots 完全相同；过去 **9 次 observe 反馈中 7 次正分、2 次共同关闭零分**，全部相同。

| 同一个下一动作 | 世界 A | 世界 B |
|---|---:|---:|
| 合成 slot | `N20270101-S010` | 同左 |
| 合成 time | `2027-01-02T03:30:00Z` | 同左 |
| target / duration / program | `V4T000079` / 60 秒 / BACKUP | 同左 |
| assigned / hit | 1 / 1 | 1 / 1 |
| 合法公开 score feedback | **0** | **0.038914** |

两个 runner 都正常 `agent_finished`，无非法动作。原生反例门检全部通过，来源及公开快照见 [counterexample_result.json](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_public_rng_identifiability_20261004/counterexample_result.json)。因此在此官方允许的模型家族中，同 `P,H_t` 不满足 future 为常数的条件；即使把完整合成 public publications 提供给观察者，也识别不了 background stream。任何只依赖同一公开历史的确定预测器在分岔处给两世界相同输出，至少一个世界的精确得分预测错误。

该反例的作用边界明确：它依赖 independent weather seed 和人为设置的合法合成参数。**它不是同 master 碰撞构造，也没有证明实际 α–δ 使用独立 weather seed。** 若实际确是 shared master 且完整配置/小域已知，上一节的恢复结果成立；如果实际 weather seed 独立可覆盖，相同 catalog seed 的恢复本身根本不识别 weather。

反例脚本首次有三个实现问题，完整失败代码、输出和已生成世界均保留：`min_altitude_during` 参数顺序、initial `last_result=None` 的聚合、`run_scenario` 返回值的 termination schema。三次修正只修接口/证据聚合，没有改变冻结生成参数、seed 域、pair 规则或动作决策。各前后 SHA 和原因见 `counterexample_revision1/2/3_receipt.json`；最终源码与最初锁不同的唯一实验模块是 `counterexample.py`，明确记录在 `FINAL_VERIFICATION.json`。这些失败不作为预测错误率或策略得分。

## 6. 实际公开资料的准入检查与查重

随后单独冻结了一个仅 schema 的实际公开检查：只打开 α–δ 各自 **6 个合法 public/config 文件**，不读未来 publications、truth 或 seed 规格，不做实际 seed 字典。24/24 文件已记路径/大小/SHA；JSON seed-key paths 均为空，config 目录无完整 `v4_catalog_config.json` / `v4_weather_config.json`。catalog CSV 先检查 header 不含 private 字段，再计数。结果见 [actual_public_schema_probe_result.json](/Users/kamico/work/GOSIM/OBSERVER/formal_v4/results/cold_public_rng_identifiability_20261004/actual_public_schema_probe_result.json)。这是当前下载公共输入的事实，不能推断组织者未使用其他 generator config。

官方 practice 构建说明也明确：organizer 使用 secret seeds，generator inputs 不在公开仓库；公开 card facts 并不包含这些 seed。依据：[公开 practice 构建脚本说明](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/scripts/build-v4-practice-cards.py#L8)。由公开默认值或样例 seed 推定实际 master 域，没有依据。

既有 `PUBLIC_SEED_AUDIT_ZH.md` 已建立 phase 指纹及公共 demo seed=5021 正对照；`GPU_PUBLIC_SEED_MODEL_ZH.md` 已归档 SHA/legacy 两种模式的完整 32-bit、中心池 offset 家族扫描无匹配。这里仅读既有报告，不独立复跑或认证 GPU kernel。重复 `0…1023` 实际搜索只是旧搜索子集，不能新增实际可识别性证据；故本轮没有做它。旧无命中只排除当时的源码/消费/中心池/容忍度假设组合，不能证明实际 master 高于 32 位，也不能否定其他配置/版本。

`GENERATION_MODEL_ZH.md` / 原 `v4_generation_audit` 路线已说明 AR、事件时点和 score 状态反演；`generator_forecast` 的双层滤波固定工作量对照为 L3 **−28.938401**、L4 **−73.902698**，强 diagnostic 汇总也拒绝当前版本。本轮不再拟合这些模型或把条件状态估计改名为 PRNG 破解。此前 `cold_public_rng` 的 scorer 人工槽反例和人工 `tiles` 小域 SHA 示例属于协议/派生性质验证；本轮新增的是 **真实 v4 footprint 上的 blind root 恢复与全部子流 holdout**，以及 **真正经官方 generator+bundle+fiber+runner 的 same-public/past 反例**。

## 7. 停止结论

三类结论分别成立：

1. **源码确定事实**：正式 shared-master builder 用命名 SHA-v1 子 seed；没有 catalog MT state 到 weather MT state 的 offset 捷径。spec builder 则允许不同 root，publications 是粗投影，scorer 不会补充未来 RNG 输出。
2. **配置条件下的已验证事实**：已知 10-bit master 域和完整 synthetic config 可 blind 恢复并精确跨流预测；independent weather seed 家族存在相同完整 public、相同非空 past feedback、不同下一 score 的正式原生反例。
3. **未确认的实际关系**：α–δ 的完整生成参数、root 同一性、seed 域/熵与 runtime 未知。当前证据不支持恢复实际 future，也不支持“用了 SHA 所以一切算法下绝对不可恢复”。

继续实际恢复研究应先有新的合法公开证据收窄 seed 域、确定生成 runtime/配置，或证明 catalog 与 weather/request 共享同一个 master。届时先冻结候选/参数空间和 abstain 规则，只用已经发生的公开 feedback 做盲验证；验证失败就保留并拒绝，不把 reference 未来交给 actor。当前没有这样的新证据，本轮到此停止，不盲扫 64-bit，不扩大既有枚举、不复算全局 bounds，也没有部署候选。
