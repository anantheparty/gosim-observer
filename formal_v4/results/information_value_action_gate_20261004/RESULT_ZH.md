# 固定两个公开状态的信息价值准入：均停止（2026-10-04，完整历史资格修正）

实际执行代码：`research/information_value_action_gate.py`。本轮只写该独占脚本与本目录；先前 Git 归档的 `cold_information_value_20261004.md`、probe、MANIFEST 不改写。

## 公开状态恢复与强原动作门检

- L4 rank4，时刻 `2026-11-23T01:03:52Z`。既有旧 snapshot 与自然 public_history 的前5条公开请求恢复后，所有请求 hash 精确一致。旧 actions.jsonl 的 assignments 曾按字符串键排序，造成 hit 列表顺序不同；采用自然历史中的原插入顺序，未改变分数或选点。
- L3 rank255，时刻 `2026-11-21T06:21:10Z`。没有完整现成 snapshot，实际调用本地官方 evaluator 重放严格过去的273个 actor 步；原 Policy 继续处理 C/E、report、calibrator、完整 ledger、request 与 resync。只用过去 trace 恢复 planner_action/prediction/terrain/stats。每条请求 hash 与过去完整 action 均一致，取得 cut 公开请求后立即结束，未执行 rank255 曝光或后续季节。
- 两个 cut 均自然调用冻结 READY native kernel；与独立留出的原完整动作字面一致。L4 380 次成功 field 评估，L3 410 次；源、C/E、report/ledger 和原工作量参数没有改动。当前 frame 在当前 native call 重建，没有借用 rank64 的旧 frame。

请求 hash 分别为 L4 `3f47c53222fcae2da735087d8fde20fcb629edd13f360f5032fc1814ce4b1254`、L3 `9a78c821197f3efbf5805a659ee7008344407123a561cfd8cdcd706ca50b9ba6`。原动作只给比较器，未参与候选生成。

## 已冻结的微域

actor 仅使用 cut 前的公开消息与 hit `(target_id,score)`。L4 得到20条 positive/7条 zero 支持约束（最大 rank3），L3 为759/6（最大 rank254）。只接受同 slot ≤120 秒、无非terrain公告、具有同场正分 anchor 且满足舍入严格下界的 zero 约束。

两场景采用一个明确而有限的条件模型：只有一个 E 地形扇区，中心固定公开 E 标签中心90度；半宽为包住全部 zero 支持点的最小宽度；高度两端分别由最高 blocked 点和扇区内最低 positive 点确定，等概率。它们最初只检查了上段资格短曝光的 point constraints，**该检查不足以建立整个公开历史的支持**。L4 高度32.508929/61.430185、半宽33.365525度；L3 高度49.107918/49.798201、半宽28.538125度。这不是官方概率先验，也不穷尽所有可能边界/多个地形扇区。最终完整历史审查拒绝 L3 的高地形世界，见下段；原冻结 JSON 保留以便审计，其 `only_public_support` 声明受 `MODEL_SUPPORT_REJECTION.json` 修正。

fields 和 target pools 只来自原 native 已经实际评估的380/410个 field。program 固定该原 field 已选 program；duration 保留该 field 原时长并按当前公共 slot 余量截短；不增加 seeds、fields、targets、program 扫描或时长列表。60秒探针仅取按原 native utility 排序的**首个**具共同 positive anchor、且有 zero/positive 区分的 field，不用结果换其它 probe。

微域截止当前 slot 边界，L4 余668秒、L3余530秒。比较的是两条动作路径：`60秒probe + 一次完整续局 + 必要wait`，与`原强native首动作 + 一次完整续局 + 必要wait`。同样只有两个 observe，截止时刻相同。未来 continuation 指向跟踪原 field 的公开天球中心，并在原 target pool 内重做纤维指派。

全目录已知 score ledger 与 factor_lower 均保留。叶值按模型结算 best science、required、全RA band Jain；C/E不因预测反馈重置，原 empirical blocked_spots 等非静态地形因素保留；真实模型的 program 不受方向地形影响。两状态均无 active REQ。这个停止于当前 slot 的 surrogate 未建模未来季节价值/未来data_loss，factor预测沿用父策略的保守 duration margin，因此叶值不是官方真实季末总分。

先生成 frozen 与两个预测反馈组下的完整续局动作，再取已有解码结果的公共去重集合。probe 的公共完整动作族为 L4 407个、L3 419个，所有 posterior 均在同一动作族求条件期望 max；这是同一批 field 内的 assignment 变体，不是增加 field/target/program/duration 池。严格按公开预测 feedback 分组，不采用各隐藏世界独立 max 后求均值。

## 全部历史 positive 的资格审查

实际运行独占 `public_world_support_audit.py`，仅用已保存的 public_history、cut snapshot、公开 targets 与初始化 site 字段，不读 terrain/weather truth，不重放 actor，不生成新候选。它将每段旧曝光拆为至多60秒，按官方恒星旋转速度给出连续 altitude/azimuth 保守包络。固定 terrain 在整个周期生效（官方 `participant-guide.zh.md:494`）；若包络全在遮挡区内，任何 scorer 积分样本都只能为0，因此严格正 hit 构成反例。

L4 检查48条旧 positive，未发现整段被遮挡反例；这是必要条件检查，不能当作完整 posterior likelihood 证书。L3 检查3671条旧 positive，发现 **3条反例**，全部来自已收到的 observe77，`2026-11-16T06:33:38Z` 至 `06:39:28Z`，350秒。

| 公开 target | 已收到分数 | 全轨迹 altitude 上界 | 距扇区 az 边界最小裕量 |
|---|---:|---:|---:|
| V4T007002 | 0.137236 | 49.636271度 | 0.808172度 |
| V4T008659 | 0.177407 | 49.584893度 | 1.570352度 |
| V4T006545 | 0.239972 | 49.573149度 | 1.933970度 |

三者整个连续轨迹均被 L3 high world（高度49.798201度）覆盖。该世界不属于合法公开后验支持，**L3 数值不能作为有效 posterior 信息价值实验**。按固定场景、禁止救参数的要求，不换 height/center/probe，不展开其它状态。所有细分包络保存在 `PUBLIC_WORLD_SUPPORT_AUDIT.json`，最终资格覆盖在 `MODEL_SUPPORT_REJECTION.json` 和 MANIFEST。

## 原冻结模型的数值与最终准入

| 固定状态 | 同probe信息价值 | 两反馈组的后续完整动作 | 减native首动作机会成本后的微域差 | 准入 |
|---|---:|---|---:|---|
| L4 rank4 | **0** | 完全相同 | +40.390039 | **停止：无决策信息价值** |
| L3 rank255 | +0.059924（拒绝模型诊断） | 一个fiber目标切换（模型内） | −0.893932（拒绝模型诊断） | **停止：固定high世界违背已收到反馈** |

L4 首probe来自 parent_order63；两个反馈组后续都选择 parent_order22、525秒、同一pointing和13个targets。+40.390的有限微域差来自 first field/commitment 变动，移除反馈适应后完全保留，不能计信息价值或真实卡提分。完整首动作、fibers、公共窗口与比较路径保存在 `L4_FIRST_FIELD_COMMITMENT_RECORD.json`：

| 路径 | 当前首动作 | 一次续局 | wait | 同一终点 |
|---|---|---|---:|---|
| 首field/commitment候选 | 01:03:52–01:04:52；60秒 DARK；(alt61.1192054,az62.7427743)，15目标 | 01:04:52–01:13:37；525秒 DARK；(37.3216872,144.3880146)，13目标；反馈两组及冻结都相同 | 83秒 | 01:15:00 |
| 精确强native首动作比较 | 01:03:52–01:07:42；230秒 DARK；(59.6483839,62.0998717)，14目标，字面匹配自然原动作 | 01:07:42–01:15:00；438秒 DARK；(36.7505911,141.3528868)，16目标；反馈两组及冻结都相同 | 0秒 | 01:15:00 |

两条路径都是668秒、两个observe。模型候选/强native路径期望 score 增量为166.861619/126.471580；两个世界增量分别为167.196679/166.526558和178.690801/74.252358。比较中的 native **首动作**是实际精确重现，第二动作是原公开 field/action 池中 surrogate 最优的一次续局；没有实际执行未来 native 重规划。因此 +40.390 只保留为未来独立两步承诺路线的未验证候选。本轮未执行两条路径的官方分数 rollout；不据此救信息路线。

L3 原首probe来自 parent_order135。原拒绝模型的两反馈组后续均470秒，同 pointing `(49.7951999,92.3535704)`；fiber2分别为 `V4T007297` 与 `V4T000657`。动作本身通过几何合法性，但 posterior 支持已失败；+0.059924 和 −0.893932 只作原计算诊断保留，不能称为因果合法的策略收益或有效负收益估计。

候选和条件续局均先写 `candidate_frozen.json` 并记hash，之后独立 evaluator 才读实际隐藏偏差、核对官方动作语法、全曝光高度和纤维命中。L4 probe/两分支实际hit为15/13/13，L3为10/14/14，所有已指派目标全命中、最低高度全部满足。隐藏geometry未回传 actor 或用于选择。没有官方实际微续局评分、完整season replan、GPU、远端任务或网站提交。

当前评分器对全天空投影时，对背面非有限offset有 `invalid value encountered in cast` RuntimeWarning；输出动作只用有效 hit pool，候选预测及官方实际geometry全部通过。没有因该警告修改 native 源。

## 停止结论与边界

两点最终分别因“后验不改变完整行动，信息价值为0”和“固定地形场景不受完整公开历史支持”停止。L3 原模型内机会成本也负，但不将这个无资格数值作为最终证据。这里只否定本次固定两点、固定场景、原field池、首个probe、当前slot两曝光准入；不否定所有主动信息策略。

先前13/13真实blocked证书与合成+6.107668存在性仍成立，但不替代本轮准入，也不能替代完整公开卡策略收益。全部旧 positive 的必要支持审查已实际执行；两动作官方分数 rollout、未来 native 重规划、整季比较仅属未执行项目。研究结束，不启动整季，不改选点、probe排序或参数。

最终完整运行约14.61秒。一次初版条件decoder未明确共享动作族，之后仅做必要的公共动作族修正，结果数值不变；初版与修正区别见 `INITIAL_RUN_NOTES.json`。最终harness SHA256为 `5417c9000acb370f43a15239f73e9eca237f1c8fa6a36d428d2a52752e54ae06`，`MANIFEST.json` 保存完整结果与冻结native源哈希。
