# 公开日历边界：提前绑定光纤方向与短夜尾曝光

2026-10-04。先独立阅读官方 `v4_runner.py`、`v4_scorer.py`、`v4_workflow.py`、`v4_fiber_map.py`、协议和公开配置/日历，再读 portfolio 与旧研究查重。仅写本文件与 `../results/cold_calendar_boundary_20261004/`。没有服务器、SSH、GPU、API、提交、完整赛季或隐藏天气读取；没有读取 sealed L4、真实 factor 列或教师标签。强 ZIP 仅只读检查，29 文件，SHA256 `e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`。

**新结果：合法动作起点可以改变光纤格的天球朝向。** 一个官方短循环合成例中，夜前 2700 秒起曝同时服务两个目标，科学分 **0.750480**；已证明该合成 900 秒夜窗内，任意中心、任意起时、任意次数和三种 program 的全部夜内排程科学分均不超过 **0.389705882**。因此条件优势至少 **0.360774118**。收益来自提前固定网格方向；白天段没有积分。这不是实际卡收益或部署效果。

另外，生产 Policy 在剩余不足 60 秒时直接等待，漏掉申报 60 秒、实际裁短到 1–59 秒的合法曝光。官方合成末段 30 秒例全项净增 **0.036528**。真实强 L1 公开历史中找到 52 秒漏尾；用目录/几何冻结的 14 目标动作，在明确声明的合成天气下，全项条件增量 **0.745417**。实际该时刻天气没有裁决，不能称真实增分。

## 1. 完整时间域

设 survey 为 `[S,E)`，公开夜窗为 `[a_j,b_j)`，曝光申报范围 `[m,D]`，这里为整数秒 `[60,3600]`。

- `observe` 没有独立起时字段，起时就是内部 `now`。初始 `now=S`；`report` 不推进时间；`wait` 与 `observe` 只能向未来推进。
- `wait until_utc` 只要求合法 UTC 时间且严格晚于当前内部时间，没有 60 秒的下限，并自动展开为不超过 D 秒的等待。故任意 `S≤s<E` 的整秒起点都可到达。ISO 解析亦保留亚秒；snapshot 格式只显示整秒，本研究动作全部使用整秒，没有利用这种精度差。
- 不能在首次 `S` 前起曝。后续夜开始前的 gap 可以起曝；动作契约没有太阳高度或 public night 起时过滤。
- 申报 `d` 必须为 `[m,D]` 中的整数秒。runner 先令 `e=min(s+d,E)`；若 `s` 位于某个真实 weather slot `[u,v)`，再令 `e=min(e,b_j)`。这是按曝光**起点**是否落在 slot 中判定的夜尾截断；关闭 slot 同样会截断。
- 起点在 gap 中时，没有上述夜尾分支，只有 D 与 survey 末端裁剪。普通公开日历的日间 gap 远长于 3600 秒，因此实际卡不可能穿过两个夜晚。一般的合成 calendar 若 gap 或夜长很短，应按原实现处理，不能自行加上不存在的截断。
- 实际计分 duration 为 `int((e-s).total_seconds())`，因此夜尾可短于 m。整秒的非空可评分起点支持集为 `⋃_j(a_j-D,b_j)` 与 `[S,E)` 的交集；`s=a_j-D,d=D` 恰好在夜开始结束，积分为零。该集合仅是时间必要条件，不保证天气开放、光纤命中或全程高度合格。

边界端点也须区分：`s=a_j` 属于 slot；`s=b_j` 不属于结束的 slot，通常是 gap。同一夜内跨普通 slot 正常积分；从夜内起曝不能穿过该夜末端。天文 dusk 到首个保留 slot、最后 slot 到 dawn 的未保留部分也没有天气积分。

官方动作链依据：runner `normalize_action` 943–1027；wait-until 展开 599–609；曝光裁剪 709–717；geometry/altitude 718–745；积分与 ledger 747–786；终局 833–849。workflow 194–207 只剥离协议 envelope，再交同一 runner，未增加 public-night 检查。

## 2. 零段不能当免费科学积分

`WeatherTruth.segments` 返回 gap 的 `(seconds,None)`；closed slot 与 `None` 均不贡献光子积分。`score_target_exposure` 的积分分母包含整个实际曝光时长，再乘实际 duration；对整秒起止，padding 的时长在 raw factor 中严格抵消。它不产生额外光子。

官方对照中，同一 target 的 900 秒有效夜段，提前加 2700 秒 gap 或在夜开始直接发 900 秒，factor 都是 **0.352113**。但 q_band 从 **0.352113299** 降至 **0.088028325**，是原来的 1/4。program band 的平均也包含零段；它没有 instrument efficiency、directional multipliers，却仍由 gap 稀释。必须分别计算三 program 的完整 score，不能只复用去掉 padding 的 q_band。

全程高度过滤同样包含 padding。合成上升目标在夜开始为 31°，提前起曝的全程最小高度 **20.755157794°**，于是无 hit/无科学分；夜内对应动作的最小高度为 **31°**，有正分。提前起曝不能预先绑定尚未升到 30° 的目标然后只计算夜内部分。

请求 witness 要求整次曝光 `issued_at≤start` 且 `end≤deadline`。在请求恰于夜开始发布的合成例中，夜前动作虽然 factor=1，但不能完成请求；夜内动作获得 100 分奖励。夜前总分 **1.06**，夜内 **101.2**。夜前动作也收不到在其进行中才发布的夜初 bulletin/request；消息要到下一决策才送达。

## 3. 提前起曝提供额外网格方向，且可以胜全部夜内域

本例只用官方公开 L1 site/fiber/scoring 常数，天气是明确构造的 synthetic 常量：下一夜只有 `[2026-11-03T00:30:00Z,00:45:00Z)` 的 900 秒开放窗口，seeing=4、transparency=sky=efficiency=1；前夜所有 slot 关闭。无事件、offset、request、required。两个 target 的 flux=.5、weight=1，由公开公式构造于夜开始的 `(alt,az)=(70°,0°)` 视场中心上下各 1.4° 的 gnomonic 位置。

夜前 **23:45:00Z** 发 3600 秒 `BACKUP`，指向 `(67.247720090°,30.275682354°)`，两个目标分别绑定 fiber 0 与 15。命中只在起点判定，然后 sidereal tracking 保持相对光纤位置。完整官方 loop 给科学分 **0.750480**。每个 factor<.5，故该合成域的 Jain、required、request 均不变。

这不仅是原中心的弱对照。如下证明覆盖全部夜内合法排程：

1. 方形 field 的球面外包半径 `R=atan(√2·radians(fov_side/2))=1.788273478°`。任何命中 target 的中心都在此球冠内。两个目标在整个 900 秒区间的高度不超过夜开始的 **71.399721476°**，从同一上中天单调降低。故中心与目标的 az 分离上限为 `zmax=asin(sin(R)/cos(71.399721476°))=5.614578384°`，令 `c=cos(zmax)`。
2. 对任意这样的中心，其 vertical tangent 角由 `θ_i=atan(tan(h_i)/cos(az_i-az_center))` 减中心高度得到。两个目标的 vertical 角差下界为 `g(t)=h_high(t)-atan(tan(h_low(t))/c)`。field 的最大允许角跨度为 `2 atan(radians(fov_side/2))=2.529411247°`。
3. 官方几何逐整秒求 901 个 g 值，最小 **2.663195807°**。天球旋转给 `|dh/dt|≤360.98564736629/86400` 度/秒，而 `dθ/dh≤1/c`；故 g 的 Lipschitz 常数不超过 **0.008376290°/秒**。用最近整秒的半秒误差并留 `1e−7°` 容差，得到全连续区间下界 **2.659007562°**，仍严格大于 field 跨度。任意夜内时刻和中心最多命中一个目标。这个数值实现不是区间算术，但留有约 0.1296° 的解析余量。
4. seeing=4 时，公开 lunar≤1、normalized airmass≥1，所以 `q_band≤1/(4·.68)<.4`，夜内全部动作的真实 band 为 BACKUP；其他声明 program 不能取得更高乘子。任意次数曝光的总有效秒数≤900，每次最多一个 target，best-only 得分又不超过各次贡献之和。因此全部夜内排程科学分≤`1.06/(4·.68)=0.389705882`。所有 factor 同样<.5，完整终局差至少 **0.360774118**。

这是局部两目标合成域的动作空间证据，不是整季上界重算，也不是证明真实 catalog/天气会提供同样收益。后续实际候选必须同时比较 lead、完整 duration、q_band dilution、whole-altitude、REQ 窗和原强 nightinside 候选。lead 还占用 3600 秒申报长度，因此早起越多，留给夜内有效曝光的最大时长越少。

## 4. 1–59 秒尾曝的公开遗漏与条件验证

ZIP `policy.py` 的 `_night` 82–83 只接受公开夜窗；`decide` 325–331 在 gap 等到下一夜开始；334–335 在 `remaining<p.tmin` 时直接等到夜末。这两个域均未被生产策略搜索。旧 `cold_search_reduction_20261004.md` 已为可达性证明扩夜前 D 秒，并承认夜尾裁短；没有此方向绑定收益证明。旧 global-field v2 还明确拒绝 `up<60`，其短夜尾核验也不覆盖实际 1–59 秒动作。本轮不重复旧退场商或全局 bounds。

官方合成 30 秒末段：申报 60 秒通过 workflow envelope 与 normalize 校验，runner 决策 CSV 记录实际 duration=30；全项净增 **0.036528**，没有跨 completion 阈值。未添加额外时间。

真实 public-prefix 准入使用既有 native READY L1/rank858 的 `public_capture/capture.json`，没有读取其私有 teacher 或 observations factor。仅按公开时间选择首个≥30秒漏尾，得到 **rank235 / 2026-11-05T08:14:08Z / 剩52秒**，原动作字面为 `wait until 08:15:00Z`。这是公开强轨迹，非声称当前 ZIP 的整季轨迹相同。

随后用公开 catalog、全程 altitude 和 100 个确定 target anchor 选择 14 个历史公开 best score=0 的目标，固定指向 **(39.018117064°,229.311196812°)**、申报60秒、BACKUP。完整 action 在 `summary.json.public_prefix.candidate`。官方短 loop 在声明的 synthetic `seeing=1.5,transparency=sky=efficiency=1` 下实际裁成52秒，科学增量 **0.745417039**；各 factor 为 .008584–.317311，全部<.5。

历史 raw factor 不公开，故只从公开 score/program 构造 lower/upper 两套 endpoint ledger，经官方 required、Jain、request、science 全部结算。两套原 Jain 不同，但新增动作的五个终项差均是 science **+0.745417039**、其余 **0**。一个已公开且已经过期的请求在两分支都保持100奖励。由于选中目标此前没有正 score，它们的旧 factor 必为0；新增 synthetic factor<.5，所有既有 completion/request 位保持不变。因此这个条件 delta 对任何与原反馈相容的旧 ledger 都成立。端点计算不是实际 raw-factor 重放，也不是实际天气评分。

真实天气/方向事件/offset 尚未裁决。关闭可令收益为0；更好天气或更大 flux 可能使目标跨.5，改变 Jain；新的 observe 还改变编号。因此不能直接把此条件结果部署或宣称实际增分。

## 5. 尾曝的非单调性与 terminal 子域

- **Jain 反例**：两个 RA band 原完成比例各 .5；30 秒 tail 使其中一个变1。科学分增加1.2，Jain 罚分增加20，官方总分净 **−18.8**。新增正 hit 不能单独保证总分不降。
- **非末夜 rank 反例**：原 N=4 的未来 loss 窗 `[floor(.4N),floor(.6N))=[1,2)` 只删除一个空动作；增加尾部空 observe 后 N=5，窗变 `[2,3)`，删除高分动作。官方完整结算净 **−201.2**。gap/短尾的 observe 不能当作无成本 wait。
- **真正终局 tail 的限定证书**：该动作从最后夜内起曝并被裁到 `E=survey_end`，则 runner 设置 `now=E` 后退出 while，终局结算不再检查 data loss。已有 loss 在当前 snapshot 之前已冻结 N；尚未在 while 头处理的末段 trigger 不会产生新增处理。合成 trigger 位于尾部中途的 wait/extra-observe 两分支，N分别4/5，均无 invalidation、同原 ledger/总分。这一结论只适用于动作直达 E、没有后续决策的真实 terminal 域，不能推广到“末夜任意时候”。

terminal 动作仍需公开 score/factor 区间与 RA 计数控制 completion/Jain 风险，天气未知不能保证正 science。生产接入应留固定 CPU 预算，完成新增候选和协议回复后才到 global deadline；合法模拟尾秒不是多出的墙钟预算。

## 6. 后续可执行接口与停止范围

提前绑定方向可由普通公开策略执行：上一夜结束时，把 `wait until next_start` 改为 `wait until next_start−lead`，再用当时已经公开的 forecast/history 和几何选择整次曝光。原 wait-until 自动展开期间不会再调用 actor，故只修改 gap 分支判断而不提前截止等待无法执行此动作族。首夜之前不允许提前；未发出的 bulletin、request 和真实天气不能进入候选。新动作执行后必须按实际反馈继续重新规划，不能喂旧 future tape 或把旧 suffix 当真实反馈。

本轮停止在动作域、强局部合成证书与公开条件机会；不改生产、不救参、不开完整季节。是否值得加入新包，应由公开候选冻结后的一次正常完整对照裁决。日间零积分本身没有科学收益。

## 7. 复现与文件

运行 `.venv-solver/bin/python formal_v4/results/cold_calendar_boundary_20261004/audit.py`。18 次短官方 loop 总用时约 **1.17 秒**；每次只替换 `load_scenario` 为 `validate_scenario` 通过的内存 synthetic Scenario，所有 action→fiber→altitude→weather integration→ledger→terminal scorer 逻辑原样。没有载入任何真实 scenario truth 产品。`summary.json`、各 case 的完整 decisions/observations/messages/score_report/snapshots、protocol 验证、source manifest 都保留。两次研究脚本错误也保留：最初 synthetic request 漏 `record_type` 被官方校验拒绝；后来“prefix 无已发布请求”的断言错误，已改为从 delivered messages 重建请求并调用官方请求结算。没有把失败数字当算法效果。

所有 output 和官方/公开源的 SHA 见 `MANIFEST.json`；基线 ZIP 最终复核 hash 不变。源码与结果只位于本文件和指定结果目录。
