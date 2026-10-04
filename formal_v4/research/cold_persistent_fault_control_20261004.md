# 公开持续故障控制：冻结候选与因果接口（2026-10-04）

本轮已产出两个可执行候选，均从原 29-file `observer_request_exact_cache.zip` 派生，原策略的科学规划、pointfit、ledger、REQ 参数和源文件均保持字节一致。v1 在跨夜持续效率异常时使用一次免费诊断并保留一次额度；v2 在 v1 的误报后学习公开背景效率，只在新的额外持续下降具有正期望价值时使用最后一次免费诊断。两版都避免新增 false report 改变 C/E 或已选科学动作。当前仅公开轨迹和入口、接口验证完成，官方完整季节由 root 统一启动，尚不声称真实分数收益。

所有材料位于 `formal_v4/results/cold_persistent_fault_control_20261004/`。禁止读取 `HOST_DIAGNOSTIC.json`、fault truth/date/multiplier、teacher 标签；本代理没有读取。原始 `observations.csv` 输入边界只投影 `observe_index,target_id,score`，不使用 factor、quality、prog_mult、fiber label、valid label。

## 1. 独立合同模型

首先阅读官方 `v4_runner.py`、`v4_scorer.py`、`weather_simulator.py` 后才检查原强包和 `ALGORITHM_PORTFOLIO_ZH.md`。

- 官方 report 没有模拟时长，也不推进 observe rank；正确报告修复当前尚未修复的 instrument_fault 并取得 +100，false 的前两次免费；正确报告将 false counter 归零。超过免费额度的 false 为 −150。初始化给出额度和连续 report 上限，候选按实际 public scoring 读取。
- `WeatherTruth` 对 fault 有独立 repair state。地震导致的效率变化不会由 fault report 修复，且地震公告不排除同时存在独立 fault。
- program band 不含仪器效率；真实 target factor/score 则含效率。固定同一科学动作修复后的 factor/score 单调非减，但 Jain 不保证单调，且正确修复后整个原 actor 重新规划可能产生轨迹变化，因此不能把固定 hit 诊断潜力称为真实策略收益。
- 公开 score 一般不能单独识别 C 与 E。free report 是有未来机会成本的公开干预：false 证明**报告这一 UTC 没有可修复故障**，不证明当前 C/E 分解正确，更不应该任意重置科学信念。

原强包 `_repair` 对任意 earthquake notice 硬拒绝，efficiency-upper witness 又要求曝光全过程没有任何 notices 且所有 target 预测高度 ≥65。原 `_ingest_result(false)` 把 E 重置为 .95、C 重置为 seasonal；这正是旧免费 report variant 可能产生科学轨迹损失的机制。已有的“直接花光免费额度”和“保留原 witness 一次”的 weak/strong 失败在组合记录中已查重，本轮保留原科学 actor，并改变新增 report 的因果接口。

## 2. 与 C/E 拟合无关的公开 product 区间

令 `y=score/science_weight`，公开几何积分 `H=mean(lunar/airmass^beta)`，`a=feature_flux*duration*H/(f0*t0)`。真实 declared-program multiplier 只可能为 matched multiplier 或 mismatch multiplier。对公开六位小数 score 使用 ±0.500001e−6 区间。若 `0<y_upper<.985*min(mult_match,mult_mismatch)`，不论匹配状态均未饱和，于是 target 的曝光加权有效 product 满足

```
y_lower / (max(mult_match,mult_mismatch)*a)
    <= Z_effective <=
y_upper / (min(mult_match,mult_mismatch)*a).
```

恒定场景里 `Z_effective=C*E`，其中 C 含 transparency、sky、seeing 和 q0。跨槽天气变化时这里是几何加权曝光 product，不冒充精确的单个全局 C/E。每个曝光至少三个合格 target，取区间端点的中位数，避免少数局部损失主导统计；一个 public slot 中多个曝光再次合并为一个 slot 统计，避免把同槽数十个 target 当独立证据。

证据只使用已发布的 bulletin 和 forecast。非 earthquake 的 ALL 天气公告遮蔽曝光；方向公告在 target 距离 public direction ≤60° 时遮蔽该 target。forecast 只有实际 published coverage 内当前 public night 对应的 notices 生效，绝不读取未来 forecast。earthquake 保留为 E 的 nuisance，允许进入持续异常模型。几何 H 使用原 public 几何模块的同一 ≤120 秒 mesh，并按公共夜历、slot_seconds 对齐。

## 3. v1 已冻结算法

完整参数在 `PREDECLARATION.json`，在查看公开轨迹触发位置之前冻结。将 product interval 以上界除以原策略相同的 seasonal C×.95 reference。最近三个 public nights 的最后八个不同槽中，至少六槽 normalized upper ratio <.60，并要求低槽跨两夜、至少两个 90°视野方向、累计 observing span ≥5400 秒。0.60 是明显超过 program multiplier 最大约 20% 歧义的严重异常阈值；跨槽、跨夜、跨方向要求用于抑制同一云层和同槽相关性。这是显式 weather/fault 决策先验，不是概率证书，更不保证异常一定可由 report 修复。

新增报告只发生在 actor 已经选出 observe 动作以后，需要 live wallclock 剩余至少 15 秒、保留一次免费额度，并满足 14400 observing seconds 冷却。missing wallclock 不会补为历史值，候选直接不主动诊断。false 后该相同 anomaly level 被记录为 negative level，除非新的 product 比值降至 negative level 的 .60 以下，否则不重新触发；同时 v1 的剩余一次额度始终保留给原 witness branch。v1 并不会主动使用最后一次额度。

### 公开轨迹结果

`audit_public.py` 用原强 L1/L2/L3 actions、decisions 与 public message/score projection 重建**观测特征轨迹**。删除不可恢复的历史 wallclock，也不借用隐藏 active-request completion。没有把记录未来 actions 当作 actor 的真实重新规划，更没有为额外 report 伪造真假标签。

| Card | 首次公开 qualified UTC | observe rank | product ratio upper | 低槽 / 总槽 | 跨夜 / 方向 | 原公开 report |
|---|---|---:|---:|---:|---:|---|
| L1 | 2026-11-29T02:44:05Z | 902 | .517049 | 6 / 8 | 2 / 2 | 原策略后续公开 correct report |
| L2 | 无 | — | — | — | — | 原策略公开 correct report |
| L3 | 2026-12-19T02:00:00Z | 961 | .410733 | 8 / 8 | 2 / 3 | 无 |

L3 首个草稿只遮蔽 bulletin 时曾得到 12月5日的触发；按预声明完整加入 published forecast 当夜的公告后更新到上表。草稿分析不是旧 ZIP 的官方季节数据，最终只冻结 forecast 版。候选不包含这些日期或 rank；表仅是记录轨迹的可复核结果。它不宣称时点 true，也不等于正式策略 fire 时点，因为正确 report 会改变未来实际轨迹。

## 4. 新增 report 的因果接口

原 actor 先正常 ingest 当前 observation、更新公共 ledger 和选择科学动作。随后旁路冻结 action 和整个 pending。

- extra false：确认 UTC/rank 不变、score_delta=0、只新增 public report_result；同步 public false quota/report_count；直接释放完全相同的缓存动作，并恢复原 pending。完全不调用原 actor 的 false-report ingest，保留其 C/E、belief_clock、last_report、low-efficiency/witness queues 和 ledger。
- extra true：将 pending 设成正常 report，discard 缓存科学动作，由原 actor 正常 ingest correct feedback、将 E=.95，再正常重新规划。公共 guard 的 false counter 同时归零。
- 原 actor 自己发出的 report 保持原有处理，旁路跟踪它们的实际 public quota；新增 guard 不绕过连续 report 上限。

`causal_interface_checks.json` 验证上述 false/true、保留额度、拒绝无 clock、UTC/rank invariant。这些合成接口检查不声称 season payoff。L1/L2 的原真实 public initialize + 首三次 feedback 等输入 fixture，原入口、wrapper disabled/enabled 的三个 response 全对象相同；`firstentry/` 保存 stdout/stderr，summary 显示 guard enabled 开关。该 fixture 的 wallclock 是测试显式输入，不声称恢复原历史 clock。

## 5. v2：negative-anchor + 新变点 + 最后额度机会价

Root 指出了 v1 的局限：第一次 false 后如果永远保留最后一次额度，就不能利用 negative intervention 学到的背景去报告随后独立发生的 fault。v1 ZIP 保持不可变，v2 在 `V2_PREDECLARATION.json` 独立冻结，尚未查看任何 host 真假结果。

v2 从 extra false 之后的公开 product 数据中，寻找跨至少两夜的八个不同干净 slot；upper product 的相对 IQR ≤.20 时冻结背景 interval。这个背景包含永久或长期地震效率损失，不再强制把它当 normal .95。如果后来的八槽中至少六槽 upper product <背景 lower product×.70，且跨两夜/两方向，则形成新 common change。

再显式比较两个未校准的模型：`x=log(current upper/background lower)`，H0 均值 0，H1 均值 log(.5)，两者 σ=.22/sqrt(低槽夜数)，H1 prior .10。只有模型 posterior≥.90 才有最后额度候选。此 posterior 是明示先验下的决策值，不能称经过标签校准的故障概率。

最后一次 free report 使用如下机会成本比较：

```
p*(correct_reward + B_now_science) > (1-p)*V_future_quota
```

`B_now_science` 用当前已选动作的原 public prediction factor、program、catalog weight 和 current science best，计算 hypothetical .50 multiplier repair 的当次 scientific uplift。按 remaining public observing seconds/current duration 外推，仅保留 5% novelty，并 cap 在当前 public catalog science room。`V_future_quota` 用最多 .10 的 future-fault prior 乘 remaining observing fraction，价值为 reward 加 5% 当前 room。这里只外推显式期望，不读取未来 target quality、actual hit 或 truth。Jain、required 和 REQ 仍未被该小期望模型精确建模，因此需要完整强策略对照。

`candidate_v2_package.zip` 可执行。`v2_mechanism_checks.json` 检查 negative background 可建立、相同 level 永不重试、新额外持续下降可触发、正净价值可使用最后 free、负净价值拒绝。L1/L2 firstentry disabled/enabled 仍与原三动作完全相同。这些检查是 causal mechanism 验证，v2 尚无官方整季收益标签。false 至 background 建立之间若已经发生隐藏故障，背景可能被污染；新地震变化也可能仍然混淆，属于该显式模型的实际局限。

## 6. 交付和运行

- 原对照：`control_package.zip`，原 29 成员 bytes。
- v1：`candidate_package.zip`，项目 `run=[python3,-u,wrapper.py]`，默认 enabled。
- v2：`candidate_v2_package.zip`，相同项目入口，使用 adaptive guard。
- 对照开关须置于实际 participant entry 命令，例如 `env REQUEST_PERSISTENT_FAULT_ENABLE=0 python3 -u wrapper.py`。官方 runner 会清洗 host environment，不能只在 host subprocess env 中设置开关。
- `package_receipt.json`、`v2_package_receipt.json` 保存完整源 SHA；原27个非 project/build-manifest 成员全部字节不变，remote runtime 仍禁用。

v1 ZIP SHA256：`bd461164340f4adf490ace91003d49f7205a6ea631f712e9767f3527ec9549ba`。v2 最终 SHA 见 `v2_package_receipt.json`。本轮不改原最强 ZIP、root report 或其他代理输出。

官方完整验证应报告实际 extra report UTC/rank/public correct、原报告变化、完整 total/五分项、required/REQ、wallclock 和 termination。false 的冻结动作应逐项相同，true 分支则允许真正重新规划；任何固定未来 tape 或固定 hit 估计都不能替代该季节结果。
