# 公开数据与隐藏随机状态：独立研究（2026-10-04）

此初稿先于读取 `ALGORITHM_PORTFOLIO_ZH.md`，只依据 `upstream/gosim-observer-examples` 官方源码/说明和 L1–L4、practice_cards 的 public/config 文件。未读取任何卡片 truth、teacher 标签、凭据、评测服务内部数据，未运行完整季节。

**完成结论：本轮没有恢复任何实际卡 seed，也没有证明它在所有算法下不可恢复。** 可以证明官方构建器用命名 SHA 流，目录状态没有到天气状态的旧式 offset 捷径；公开合约一般不能唯一确定隐藏天气。查重发现 32 位 master seed 的公开目录指纹枚举已完成且无命中，因此不重复扫描、不扩大域。可用的事实是确定预报支持、当前发布顺序、目录的公开几何和请求生成结构；这些事实不能自动变成终局提分。

## 初始模型

设公开初始化内容为 P=(目录 C、边界 F、夜历 N、评分参数 S)，截至时刻 t 已发布公告/预报与合法动作反馈为 H_t。目标是判断隐藏环境 E 或生成 master seed 是否由 (P,H_t) 唯一确定。源码已知 seed、公开输出恢复 seed、猜测有限 seed 域、平台未知 seed 四种情形分别记账。

1. **域分流模型。** 官方 `contracts.py:28–52` 支持旧式 `seed+offset` 与 `sha256-v1`；后者 `s_j=int(sha256(str(seed)+":"+stream)[:16])`，每个命名流建立独立 `random.Random`。`v4_config_check.py:5–9,83–86` 说明比赛生成卡要求 hashed seeds。即使能恢复目录流 MT 状态，也没有公开的算术关系把它转成 weather.slots/weather.events/requests 的状态。这个结论有密码学假设和 seed 熵前提：若 master seed 仅取已知小集合，仍可枚举 SHA 派生并匹配目录。不能把“SHA 分流”写成无条件 seed 不可恢复的数学证明。
2. **生成器范围模型。** 所附 `tile_geometry_simulator.build_catalog` 输出 Txxxxx/TGxxxxxxxx、四种类别及 redshift；v4 public 目录输出 V4Txxxxxx、RA/Dec、五种类别且没有 redshift。旧 weather generator 输出 event_id/revision/severity/uncertainty 数值；v4 发布 weekly notices，仅含 event_kind/direction/nights。公开 runner/scorer 是 v4 真正执行评分的代码，但当前 v4 目录/周公告的生成代码与其 seed/config 不在所附文件中。因此先不尝试把 v4 小数坐标倒推成该旧生成器的 random() 输出，也不假设目标顺序与 weather 共用同一流。
3. **状态非唯一模型。** `v4_workflow.initialize_payload` 只发布 public 目录/边界/夜历与评分规则，之后按 issued_at 交付公告和预报。`v4_scorer` 读取预生成 SlotTruth/ScoreEvent，动作评分本身不调用 RNG。同一初始化/空公告可以对应不同 seeing/transparency/sky/efficiency 或背景关闭；官方指南明确空 notices 不保证天气良好、无背景关闭或仪器正常。用两个人工 SlotTruth 与同一公开评分规则即可检验同一 P,H 的下一动作结果不同。该构造证明公开合约一般不唯一识别状态，**不声称**证明所有可能的 master seed 在当前 v4 实际生成器下存在该等价关系。
4. **仍可证的替代。** 当前 v4 预报没有误报/漏报概率字段；官方指南说所列事件一定与所列观测夜相交。不确定性在精确起止、扇区、高度边界与强度。把未来一个夜晚是否受某 event_kind/direction 影响建成约束（而非天气均值预测）；把当前 slot 公告用于更新存在性，仍不可把粗 direction 视作整个 45° 区间都关闭。事件恢复/结束与曝光反馈可建立隐藏扇区的可行集合；这里先做公开资料一致性检验，不运行季节策略，也不重做 Kalman/AR。

## 初稿已排除的推断

- V4T 的编号表示当前目录的标识；同编号出现在不同卡片不证明同一物理目标或 seed。
- public 文件完整离线可见，不等于平台在初始化时提供全部未来预报/公告。验证未来文件只能用于公开数据一致性，策略必须按 issued_at 过滤。
- 本地公开 truth 可以用于调试，但直接读取 truth 或源码中给出的 seed 不构成公开恢复证明。本研究不读取 truth。
- contracts 中的 hashed 设计说明不能单独证明某张现有 v4 卡的具体 seed/entropy 或分流实现；当前 bundle config 不带生成 seed。

## 待运行的小检验

仅读 public/config，输出脚本、manifest 和结果到 `results/cold_public_rng_20261004/`：目录规模/编号/跨卡相等性；预报夜级条目对 public bulletins 的因果一致性、提前量；人工 hidden slot 的评分非唯一性；低熵合成 seed 枚举反例。运行后再读取算法台账，明确查重结论和下一步价值。

## 查重后补充的正式 v4 源码

台账的已完成 generator 研究指向本地固定官方公开源码 `runs/official_generator_e01939d0/challenge/`（commit `e01939d060f304c2a7cf04d9b3e46009b564fc23`）。这里只读了 catalog/weather/request/bundle/contracts 的公开生成模块，没有读取其 reference 真值、实际 seed 规格、平台运行服务或凭据。初稿中的“examples 所附 generator 为旧格式”成立，但不应据此说整个工作区没有正式 v4 生成器。下面以该正式源码补正。

### 哪些共享 seed，哪些没有共享 RNG 状态

| 对象 | 正式 v4 流名/关系 | 公开恢复能说明什么 |
|---|---|---|
| footprint、class roster、required 抽样、聚类中心、target 坐标/flux | **同一个** `v4.catalog` RNG 顺次消费，catalog generator:630–707,730–733 | 目录内部确有共同随机状态；这是 candidate seed 指纹的来源，不是目录完全独立随机的证明 |
| 背景天气、背景关闭、可观测槽效率 jitter | `v4.weather.slots`，weather generator:761 | 与目录不同 SHA 域；不能将恢复的 catalog MT 状态加1000变成天气状态 |
| 天气系统事件 | `v4.weather.events`，weather generator:508 | 与背景天气、目录不同域 |
| 火箭/地震/地形/故障 | `v4.rocket_launch`/`v4.earthquake`/`v4.terrain`/`v4.instrument_fault`，543/573/605/625 | 每族重新构造不同流；可公布事件的粗标签不会给故障流 raw draws |
| loss/pointing offset | `v4.stress.data_loss`/`v4.stress.pointing_offset`，702/723 | 不共享目录或背景天气状态 |
| 请求 | `v4.observation_requests`，request generator:23,187 | 直接 SHA 派生；与目录不同域 |
| 公告/预报 | weather generator:872–983，**不调用任何 RNG** | 它们是 event 的确定粗投影；没有可供反演的“预报噪声 RNG” |

`v4_bundle.build_card_bundle:45–80` 用同一个 secret seed 给 catalog/weather，均强制 SHA；requests 接收该 seed。**这是同 master，不是同随机状态。** `build_spec_bundle:81–107` 则使用两个 generator configs 各自的 seed，把 catalog seed 给 requests，未要求 catalog/weather seed 数值相等。因此无法从 public bundle 单独识别一张实际卡究竟使用哪条构建路径、是否同 master，或 master seed 的熵/取值域。

`v4_catalog_generator:594–611` 把确定类别数量的 roster shuffle，`631–632` 随机抽 required 序号，`701` 才把序号写成 V4T 标识。**ID 字符串自身是序号，随序号发布的 class/required/coords/flux 仍能约束候选 seed**；不能把“编号顺序没有短程相关”当作信息论无泄漏。目标采样又有聚类/边界/几何 rejection 以及 lognormal rejection，可变调用数和六位坐标/八位 flux 舍入使直接 MT untemper 不适用。即使完全恢复 catalog 流状态，仍要解决 SHA 逆像或 master seed 字典问题才能跨流。

## 本轮可复现结果

运行：`python3 formal_v4/results/cold_public_rng_20261004/check_public.py`。纯本机 CPU，约0.42秒；脚本只打开 eight bundles 的 public/config，读取官方 scorer 执行三个**人工**隐藏槽。`input_manifest.json` 记录这些公开输入 SHA256。

### 目录与 ID

| 卡 | targets | required | required 比例 | seed 公开字段 |
|---|---:|---:|---:|---|
| L1 | 7800 | 390 | 5% | 无 |
| L2 | 8600 | 430 | 5% | 无 |
| L3 | 8700 | 435 | 5% | 无 |
| L4 | 8800 | 440 | 5% | 无 |
| alpha | 10000 | 500 | 5% | 无 |
| beta | 9600 | 480 | 5% | 无 |
| gamma | 9900 | 495 | 5% | 无 |
| delta | 9400 | 564 | 6% | 无 |

八卡全是从 V4T000001 起连续编号。28对卡共享大量 target IDs，**同ID精确RA/Dec匹配和完整行匹配均为0**。不可跨卡把 V4T000xxx 当成同一目标来迁移标签或历史状态。各卡类别比例完全相同：ELG34%、BGS24%、LRG20%、QSO14%、Star8%，与确定 roster 数量后 shuffle 的结构一致，但类别本身不加额外评分倍率。这里只是公开统计；不推出 future weather、hidden seed 或泛化效果。

lag1 的 sin(RA)、sin(Dec)、flux、required 相关绝对值均不超过0.023；邻接同类别比例0.2368–0.2457，边际随机重排参照为0.2392。该诊断只未发现简单相邻序号信号；没有做多重检验，也不是不存在复杂 seed 指纹的证明。

### 预报是确定的事件夜支持，不是数值天气均值

| 卡 | forecast night notices | 同夜/同kind/同direction公告匹配 | 提前条目 | 同时发布条目 | 提前条目中位小时 |
|---|---:|---:|---:|---:|---:|
| L1 | 15 | 15 | 15 | 0 | 72.25 |
| L2 | 20 | 20 | 18 | 2 | 111.25 |
| L3 | 32 | 32 | 29 | 3 | 72.00 |
| L4 | 30 | 30 | 26 | 4 | 101.75 |

97/97条与 public bulletins 一致，88条有正提前量，9条在首个对应公告同时发布，**没有负提前量或过期条目**。非地震/地形的 public bulletin night-kind-direction 对也全部能找到预报。以上用完整 public JSONL 做离线资料一致性，不是把未发布信息提供给在线策略。practice_cards 未含 forecasts/bulletins，因此不假装核验了其隐藏事件。

正式 `generate_forecasts:931–983` 从真事件枚举 coverage 内相交 nights；没有 miss/false-positive/timing-noise 随机调用。因此已发布预报可以排除 coverage 内没有列出的 forecastable 事件；但不能排除背景关闭、地震或故障。`night_date` 以公开夜历为准，不能用 UTC 日期直接替换。粗 direction 是扇区中心标签，不能当整段45°均关闭；rain/storm 的标签也没有公开 force_close 数值保证。完整支持区间证明及首末槽加强已存在 `FORECAST_CAPACITY_ZH.md`，本轮只做public对public核验，不重复实现。

### 隐藏状态不唯一：精确评分器的人工构造

取公开 L1 V4T000002、2026-11-02T00:30Z、同一900秒曝光、相同公开月光/高度/评分规则，三个人工 SlotTruth 的官方 scorer 结果：

| 合成隐藏槽 | quality | factor/score（program multiplier=1） |
|---|---:|---:|
| seeing1, transparency.9, sky.9, efficiency.95 | 1.0152218641 | 0.5688202826 |
| seeing2, transparency.45, sky.5, efficiency.6 | 0.0890545495 | 0.0498965160 |
| background closed | 0 | 0 |

这三种状态不要求在公开公告中增加 notice。相同 P 与空事件公告不足以确定下一动作得分。我们没有声称三个槽来自实际卡生成器的三个 seed，也没有执行 fiber hit 全链路或季节；这里检验的是已通过命中/高度条件后的评分映射，区别完全来自隐藏环境。

### SHA分流不排除低熵字典

独立人工设 master seed=2718、候选域0..4095，发布 `sha256(seed:tiles)` 派生流首个 random() 的六位舍入值0.477509；穷举该人工域仅找到2718。**这不是任何官方卡 seed 恢复**，而是反例：仅凭“用了SHA”不能证明小域 seed 无法枚举。脚本没有把此人工流误写为正式 `v4.catalog` 流；前者只测试 contracts 算法的字典性质。

## 与既有研究查重及停止条件

- `ALGORITHM_PORTFOLIO_ZH.md:34` 与 `results/generator_forecast_20261003/` 已完成双层AR/Kalman、确定forecast支持、SHA独立流研究；固定工作量L3/L4策略增量为−28.938401/−73.902698。本轮不增加一个滤波名字，不训练天气模型，不跑同路季节。
- `FORECAST_CAPACITY_ZH.md` 已证明单notice跨夜确定核心、首末槽、缺失信息、force_close前提；本轮97条公开公告一致性是额外核验，不是新算法或提分证据。
- `public_seed_audit_summary.json` 的known public seed5021控制复现目录/边界，仅是**源码已知 seed 阳性对照**。实际公开卡没有命中。
- `gpu_public_seed_sha256_allpool_32bit_result.json` 和 `gpu_public_seed_legacy_allpool_32bit_result.json` 两个既有归档均称完成0..2^32−1、pool3..2^32−1、phase_tolerance1e−4，候选与签名匹配为空，附known seed/offset阳性控制。这里仅读归档、保留hash；**未重新运行GPU或独立复审GPU内核正确性**。无命中排除的是该指纹模型/实现覆盖的假设集合，不能证明seed一定>32位；版本/RNG消费/配置模型不匹配也可能产生无命中。
- 因没有新的更窄seed先验、可恢复raw stream输出或版本契合证据，不再拓宽扫描域。新研究必须首先提出一个能在public样本上判别、且尚未被既有扫描覆盖的模型差异；否则停止seed路线。

## 一个保留的生成结构替代：请求资格与跨请求排除

正式 `v4_observation_requests.py:157–242` 使用一个seed派生shuffle顺序，从公开targets中筛选符合flux/设置、请求窗口几何的成员；**不读取future weather**（文件说明:2–7，函数输入无weather）。每个已选成员写入跨请求 `used`，后续请求跳过（203–220）；因此该生成器产生的所有请求成员全局不重复。一个请求的几何选择并不预言该夜天气会好，不能根据请求成员反推天气流。

在此生成器模型下，合法公开历史中的既有成员可从未来请求成员候选中排除；实际已发布请求的factor门槛、成员图与quota应交给关系决策模型。公开默认 `count`/window参数能给时点候选，但custom settings可覆盖，public scenario没有给未来count/window，故不硬编码未来发布日期。该结构未在本轮以真实请求历史或完整season验证，更不是每张未知正式卡契约保证。它是有意义且低成本的模型先验候选，不是建议立即部署。

与“重建整天气数值”相比，这些可证明关系的用途更具体：先区分某段时间确定有/无forecastable事件，再在合法发布的请求成员图上进行选择，并保留未知强度、扇区与背景关闭的不确定性。预报支持已有实现，后续只能围绕它**是否改变一项具体候选选择及终局结算**做新检验；此次没有发现支持立即开新策略季节的候选。

## 交付和边界

本轮只写本报告及 `results/cold_public_rng_20261004/`。无truth读入、teacher标签、凭据、服务内部读取、SSH/GPU/网站行动、完整季节、生产/bulk改动或提交。现有结果引用为查重证据，均与本轮新测结果分开。
