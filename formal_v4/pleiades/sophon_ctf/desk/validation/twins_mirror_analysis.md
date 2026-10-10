# 双胞胎与 237 镜子：离线入口建议

依据：`desk_calls.jsonl` 第 1–141 行。只分析已有记录，未调用平台；以下请求由主线统一执行，状态与结果必须再看实际返回。

## 双胞胎

第 137、138 行分别为 GET `/desk/hall/1`、`/desk/hall/2`。两段正文均为 385 字符，没有增删，只在以下八处替换字符；按第二段中的新字符顺序严格得到 `goldroom`。

| 0 起始字符位置 | 第一段 | 第二段 |
|---:|---|---|
| 10 | n | g |
| 57 | s | o |
| 107 | n | l |
| 162 | e | d |
| 226 | e | r |
| 247 | c | o |
| 316 | d | o |
| 347 | t | m |

第一段对应原字符为 `nsneecdt`，不构成同样清晰的词。每段 JSON 只有 `ok`、`johnny`、`message`，且正文在后两字段重复；无答案入口、method 或参数元数据。

最少请求按返回自适应选择，不要一次执行整份候选表：

| 优先级 | 下一条请求 | 依据 |
|---:|---|---|
| 1 | POST `/desk/hall`，`{"word":"GOLDROOM"}` | 已有 kitchen、typewriter 都在原 GET 入口以 POST word 作答；hall 是当前谜题入口。类比最直接，但未由 hall 正文明确承诺。 |
| 2 | GET `/desk/goldroom` | 两女孩直接提到走廊尽头的门；解出的词也可能是地点名。仅在第一条未给出成功或明确作答格式时考虑。 |
| 后置 | GET `/desk/hall/goldroom` | 若大厅采用子路径结构，这比任意猜新字段合理；但证据弱于前两条，不建议无反馈展开。 |

`GOLDROOM` 已作为 typewriter 答案在第 126 行成功；它与双胞胎独立解出的结果相同是事实，不能由此推断双胞胎奖励已领取。不要把双胞胎答案提交到 `/desk/door/...`：四词门已经完成，重试无此谜题依据。

## 237 镜子

全 141 行中 `/desk/door` 请求只有两次：

| 行 | UTC | 请求 | 结果 |
|---:|---|---|---|
| 7 | 18:53:34 | POST `/desk/door`，say=`THE SHINING` | 200；前门，不是四词门 |
| 119 | 19:50:46 | GET `/desk/door/MIRROR-TOPIARY-ELEVATOR-BASEMENT` | 200；日志中首次且唯一四词门尝试 |
| 121 | 19:50:56 | POST `/desk/room/237`，answer=`MIRROR-TOPIARY-ELEVATOR-BASEMENT` | 422，`wrong_answer` |
| 122 | 19:51:09 | GET `/desk/room/237` | 问题及作答格式未变 |

题面是 `It only asks about you.` 与 `Which door did you try first? (the four words)`，明确偏向参与者历史问题；并没有要求“反过来写”。因此应先排除答案分词格式，再考虑镜像推断。此结论仅覆盖该日志；不能证明队伍其他途径没有更早请求。

| 优先级 | `answer` 候选 | 说明 |
|---:|---|---|
| 1 | `MIRROR TOPIARY ELEVATOR BASEMENT` | 只把 URL 连字符改为空格，保留已核实的首次四词及顺序；最大程度遵循题面。 |
| 2（推测） | `TNEMESAB-ROTAVELE-YRAIPOT-RORRIM` | 整串字符倒序，最直接的文字镜像。只有空格版也被拒后才考虑；镜像题意本身尚未确认。 |
| 3（更弱推测） | `BASEMENT-ELEVATOR-TOPIARY-MIRROR` | 只倒词序；保留正写单词，比整个字符倒序多一层未经说明的约定。 |

逐词字符倒序会得到 `RORRIM-YRAIPOT-ROTAVELE-TNEMESAB`，但它既不是整串镜像，也不是文字历史复述，优先级更低。不要把四类反转与空格/连字符/大小写做笛卡尔积穷试。正确入口和 `answer` 字段已由 GET 明示，当前 422 属于答案不匹配，不是入口未找到；不应优先更换字段名。

如果空格版仍拒绝，下一步首先保留返回原文并核对是否另有未记入此日志的历史尝试。隐藏服务如何存储首次门、是否只记录错误尝试均未知；不能用这些猜测解释成确定事实。
