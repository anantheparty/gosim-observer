# Desk / 房间结构离线分析

只读 `rooms.json`、`desk_calls.jsonl`、`endpoint_probe.json`；没有发起 HTTP、猜门、提交 flag 或回答镜子。以下区分直接证据与待验证推断。

## 已证明的流程

| 来源 | 可直接读出的事实 | 含义 |
|---|---|---|
| `endpoint_probe.json` 根说明 | 旧流程有 `POST /answer {sentence, token}` 与 `GET /status?token=...`，不只有 contact-johnny | Johnny 首封邮件的明文原本有专门的答案入口；此前把它包进 flag 并不能检验该旧流程是否解对。文档仍要求运行 token，不能因此绕过 token。 |
| `/desk` | 独立返回 `board=debug`、doors/next、found/pending、receipts/hints | 新流程是有状态场景图；应跟随服务器暴露的门，flag 是各阶段生成的产物。 |
| receipts | 提前 finish 的四个行星运行都有 ground-station 记录；土星明确给 final code | 私有检查与通用 score 复核独立；`survey_complete` 不是真正的 Sophon 回执前置条件。 |
| final code 提交 | 403 `locked`，必须 walked the whole way | 拿到 final receipt 还需完成前置链；继续改行星/总分/终止方式不能代替这条链。 |
| bar 回复 | 指定四词连字符 GET；错门会清空记忆 | 不能靠错门反馈试词，也不能自动遍历 door 路径。 |
| room 237 | 问 “Which door did you try first? (the four words)” | 它考察本队首次四词尝试的历史，不是给出四词答案的神谕。现有记录没有四词门尝试，不能给镜子编答案。 |

## 房间的可核验结构

200–240 共 41 个整数，列表恰好缺 **217**，实际 40 间。237 是唯一返回 question/answer 的房间，其他 39 间分为四种固定描述：

| 描述 | 次数 | 房号 |
|---|---:|---|
| wasps' nest | 15 | 200,202,203,205,207,210,211,220,229,231,234,235,236,239,240 |
| empty room / bed made | 10 | 201,204,209,212,218,221,224,226,232,238 |
| suitcase | 9 | 206,213,214,219,223,225,227,228,233 |
| cold / radiator off | 5 | 208,215,216,222,230 |

按房号升序，以 W/E/S/C 表示这四种，`?` 为缺号，`M` 为镜子：

`WEWWEWSWCEWWESSCC?ESWECSESESSWCWESWWWMEWW`

- 234 的马蜂窝描述并不独有；它与另 14 房完全一样。不过 bar **明确点名 234**，因此读取该房获取 WASPS/NEST 是有出处的推断，不能因重复就完全忽略。
- 237 的特殊性在结构和文字上都明确；217 的缺失也明确。小说/电影的 217/237 差异可解释这组设计，但这三份文件没有说明四词应怎样排列。
- bar 同时声称第三词是 TRICYCLE 和 TONY，二者互相矛盾；不应直接相信其中一句。WASPS 是指向房间后的候选语义，尚未证明它就是第三词。
- 进行了有限的常规编码排查：去掉缺号和镜子后的 39 符号，穷举 24 种二比特映射、正反顺序及 8 种位偏移，共 384 种 ASCII 解码；没有全可打印字符串或可读词组，最佳也只有 8/9 字节可打印。没有出现支持某个四词门的结果。
- 四种分布无短周期或明显按房号取模规则。不能完全排除其他编码，但当前证据更像背景房间描述，重点位置由缺号/专门路标指定。继续无限叠加替换规则会过拟合。

## 建议主线执行的非破坏性 GET

按优先级，仅由主线在共享限额内操作：

1. **`GET /desk/room/217`**：不是猜新路由，使用已明示 `/desk/room/<number>` 模板检查唯一缺号。它最可能区分“季节列表故意漏房”与普通不存在；不要跟进任何未批准 POST。
2. 在有新 flag 或新场景进展后重读 **`GET /desk`**，以 `next/doors/pending` 为准；必要时再读已知 **`GET /desk/hint`**。没有状态变化时重复 hint 的价值低。
3. 镜子 GET 已得到完整问题，不必重读；POST 必须按主线要求审批，并且应先确认服务器所谓 first tried door 的真实历史。
4. 暂不建议四词门试探。当前文件能支持 TOPIARY（厨房已通过）、缺失 217、234 的 WASPS 语义，但不足以唯一确定四词和顺序。

## auto 榜与无 token

这三份文件仅能证明当前 authenticated desk 会话属于 debug；没有请求认证头记录，也没有 auto 入口提示，**不能证明 auto 可以不用 token**。根目录旧文档只展示 token 方式。

公开前端另外已知会发送 `x-sophon-site: 1`，这可以解释“网页入口”和运行环境需要区分，但尚无证据它就是分榜开关；不应自行添加/删除认证字段或搬运用户凭证到智能体。若主线已有获准的无凭证根/desk GET 工具，可在同一已知端点观察 board/说明差异；否则先取得范围明确的授权，不猜路由。

本分析没有发现新的未提交 flag，未把现有随机 receipt code 当作需再提交的候选。

## 主线后续反馈（本代理未请求）

- 主线已 GET 217，取得并提交 No.18：这确认了缺号是有效的隐藏支线，上述 GET 建议已完成，不应重复消耗限额。
- `say="Hi, Lloyd"` 又给出第三词 BOILER，以及以“room 237 is locked”为担保的第四词 BASEMENT。237 已实际可 GET 进入镜子，担保与观测不一致；BASEMENT 应暂标为可疑而不是接受。仅凭 "Everyone knows" 也不能确认 BOILER。
- 这些新增话语进一步支持“酒吧话语中有互斥/不可信证言”，尚未建立通用真假语法。建议证言表保持：输入 say、候选词、词序、引用房号、具体房间断言、已查房事实、判据。不要把主题上眼熟的词当成真话。

## 酒吧对照更新（desk_calls 共 33 条时）

主线新追加的同输入对照已给出决定性结果。两次完全相同的 `say="Hair of the dog that bit me"`：

| 时刻 | 响应里的候选 |
|---|---|
| 18:55:35 UTC | 第三词 TRICYCLE（trust me）；第三词 TONY（押 234） |
| 19:09:23 UTC | 第二词 TOPIARY（237 never lies）；第三词 SKYLIGHT（押 239）；第二词 TOPIARY（237 locked） |

因此可以排除 **只按 say 文本确定响应**。至少还依赖调用状态、计数、随机数、时间或其他隐藏输入；现有记录无法区分这些因素。不要继续以为换一句更精准的自然语言问题就会得到针对性的答案。12 次 POST、11 种 say 中，问题语义与回复词序不一致，表现为固定模板抽样，而不是正常问答。

31 条候选声明可分为两组：

| 模板组 | 声明数 | 每个位置的取词 |
|---|---:|---|
| 237 locked / swear on 237 / 237 never lies | 15 | 始终 1=MIRROR、2=TOPIARY、3=ELEVATOR、4=BASEMENT |
| trust me / everyone knows / room bet | 16 | 同位置多种冲突候选 |

“237 担保”有明显独立的固定向量；**稳定并不能单独证明它是真门或诱饵**。已有文案还同时说 237 locked 和 237 open，说明这些担保不适合当形式逻辑中的严格真假条件。不应把“担保句假”机械地推为“所附词假”，也不应把重复次数最多当验收证据。

房号押注共 9 次：234→TONY、203→CHAPEL、236→GRADY、231→BOILER、214→TONY、229→SKYLIGHT、200→ATTIC、223→TRICYCLE、239→SKYLIGHT。可见关系：

- 7 次指马蜂窝，2 次指行李箱；暂未押 empty/cold 房。样本仍小，不能据此发明真假筛选规则。
- 同一种马蜂窝描述对应多个位置和多个词，因此“描述类别 → 候选词”不是单值函数。
- TONY 同时押马蜂窝 234 与行李箱 214；因此“词 → 描述类别”也不是单值函数。
- 203 与 223 同个位且同词序，词却 CHAPEL/TRICYCLE 不同；排除简单房号个位查词。
- 相同房号尚未收到两条不同词的押注，故还不能检验完整房号是否对应固定词，但当前没有明确编码提示。

酒吧 shortcut 值虽然外形像 flag，实际字段叫 `pass`，伴随“skip the rest of the house”催促。紧接的 `GET /desk` 仍 `pending=[]`，与正式已取得 flag 的状态不同。保持不提交、不把它当有效凭据；当前数据只支持“可疑捷径”，尚不能断言提交后会怎样。

下一步离线分析不需要更多房间或编码穷举。若主线决定再做实验，应只做可回答一个问题的对照；同 say 控制已完成，无需重复花额度。四词门和镜子 POST 继续遵守主线审批边界。

## 全量词频更新（48 行快照）

已新增可重复运行的只读提取脚本 `work/sophon_desk/extract_clues.py`。它仅解析 POST bar 中明确的候选句，输出原日志行号、时间、模板、词序、候选、押注房号和原话；不导出请求体、pass/flag 或其他回复字段，不联网。运行：

`python3 work/sophon_desk/extract_clues.py`

证据产物：`work/sophon_desk/validation/bar_clues.json`、`.csv`、`.md`。JSON 带输入 SHA-256，避免日志继续追加后把统计混在一起。48 行快照包含 22 次 bar、54 条声明，无未识别的 bar 回复；普通模板 29 条，237 模板 25 条。

| 槽位 | 去掉237后的候选及次数 | 已有跨模板复现 |
|---|---|---|
| 1 | ATTIC 2；CARPET/CHAPEL/PANTRY/TRICYCLE/ULLMAN 各1 | ATTIC：押房号 + everyone knows |
| 2 | CHAPEL/GRADY/TONY 各1 | 无 |
| 3 | TONY 4；SKYLIGHT 3；TRICYCLE 2；BOILER/CARETAKER/PANTRY 各1 | TONY：押房号 + trust me；SKYLIGHT：押房号 + everyone knows；TRICYCLE：trust me + everyone knows |
| 4 | BOILER 3；CARETAKER/CARPET/CHAPEL/ROOM 各1 | BOILER：押房号 + trust me |

237 类始终分别为 MIRROR 6 次、TOPIARY 7 次、ELEVATOR 6 次、BASEMENT 6 次。**这四词在所有普通模板、所有槽位中均未出现，交集为空。** 普通词库目前 12 词，且 CHAPEL 等可以跨槽位出现；这支持至少有两个分离的候选来源，但不能凭统计判断哪一组是真实门、哪一组是诱饵。

新反证：同一房号 **200**、同一词序 **1**，第29行押 ATTIC，第40行押 CARPET。因此“完整房号→固定候选词”也已被排除。第40行发送的是空对象 `{}`，没有 say 字段，仍正常返回两条 gossip；自然语言问题并不是触发候选的必要条件。

原话证据全部保留在 bar_clues.md/CSV；没有提出开门请求。重复次数及跨模板复现只是样本特征，绝不等于确认答案。
