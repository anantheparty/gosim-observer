# 四词门：已完成事项与审批材料

截至 2026-10-06 19:30 UTC 左右，未请求任何四词门，也未回答 237 镜子。

## 新增真实 flag

房表缺 217，且小说房号为 217、电影改为 237，因此通过已公开房间接口访问 217。
原响应明确给出 `flag`：

```text
GET /desk/room/217
Room 217. In the book, this is the room. Nobody told the film.
SOPHON{4CK58FXE6A4ZLKJBP5UC}
```

已通过授权 hand_in.sh 提交，原样回复：

```text
2026-10-06T19:02:38Z SOPHON{4CK58FXE6A4ZLKJBP5UC} -> 200 {"ok":true,"johnny":"The desk stamps it.","no":18,"name":"Room 217","solved":true,"message":"The desk stamps it."}
```

当前已确认 No.1、2、18、19。土星 final receipt 已存在，但提交需先完成主线。
原土星 agent_finished 的回执证明 Sophon 地面站检查独立于通用 score 复核。
因此已停止仍在等待全队空闲的 Saturn full 评测脚本及本地监视器，没有新建该真卡评测。
本轮没有新的上传。

## 最新一轮：78 次采样，空房与冷房担保都出现反例

每小时限额上调后又采样 33 次。现在有四槽声明，但没有四槽一致、可审批的答案：

- 冷房第二词互相矛盾：第 77 行 PANTRY 押 216；第 102 行 CARPET 押 230。
  两间已分别实时 GET 核实为 `Cold. The radiator is off.`。
- 同一空房、同一词位也互相矛盾：238 号房先在第 93 行押第三词 ATTIC，
  后在第 113 行押第三词 TRICYCLE；实时 GET 为 `An empty room. The bed is made.`。
- 冷房另有第三词 ULLMAN 押 215、第四词 TRICYCLE 押 216；都只是候选，未得到独立印证。
- 新增 33 次 bar 全文仍只有原六种句式，没有新增 flag。约 19:50 UTC 的 hint 仍为空。

因此撤销“空房或冷房担保即可采信”的筛选假设，不能把最初的 PANTRY 视作已证实答案。
已把反例发回主线；四词门、镜子答案和锁住的 hall 均未尝试。
证词原文、时间、房号、实时核查来源和独立计数见
`validation/bar_verified_candidates.md` 与同名 JSON。217 仍单列。

## 上一轮：45 次酒吧采样，首次找到冷房担保

截至 2026-10-06 19:33 UTC，共 45 次 bar 请求。第 44 次首次出现押空房或冷房的 B 类证词：

```text
The second word? PANTRY. I'd bet room 216 on it.
```

原始位置为 `desk_calls.jsonl` 第 77 行；216 在已保存房表中为 `Cold. The radiator is off.`。
因此新增候选为 **第二词 PANTRY，担保房间 216**，但只有单条，尚不足以确认。
该次输入为 `A glass of water, please.`，目前不能判断输入语义与新证词是否有关。

| B 类担保房间类型 | 声明数 | 当前判断 |
|---|---:|---|
| 马蜂窝 | 14 | 含同房、同词位互相矛盾的声明 |
| 未拆行李箱 | 2 | 暂不采信 |
| 冷房 | 1 | 216：第二词 PANTRY，待交叉确认 |
| 空房 | 0 | 尚未采到 |
| 缺号 217 | 1 | 第 31 次声称第四词 ULLMAN；217 支线只给 flag，未独立证实词位 |

第 34、35、37、38、42 次还出现走廊双胞胎提示：
`Two little girls keep standing at the end of the hall. Don't play with them.`
据此只探查了 `/desk/twins`（404）和 `/desk/hall`（403，`That door is locked. Not yet.`）。
后者可记作后续入口，但当前未解锁，不继续猜相近路由。

第 38 次采样后 GET `/desk/hint` 仍为空。第 45 次后再次查询被本地脚本以
`rate limit: 60 desk calls in the last hour` 拒绝，未发到平台，已停止请求且不绕过限额。
本轮没有新 flag，未尝试四词门或镜子答案；主线尚未批准开门。

完整 18 条 B 类声明及房间映射见 `validation/bar_checkable_45.json`。
后续优先核对 216 并寻找其他空房/冷房担保；单条 PANTRY 不足以组成四词答案。

## 早期快照：237 担保的稳定组合，未证明可信

```text
MIRROR-TOPIARY-ELEVATOR-BASEMENT
```

这是候选，不是已经确认的答案。按主线要求，已将以下推理和局限发回，只有主线批准并自行执行才会测试。

| 槽位 | 所有提及 237 的证言 | 声明次数（53 行日志快照） |
|---:|---|---:|
| 1 | MIRROR | 7 |
| 2 | TOPIARY | 8 |
| 3 | ELEVATOR | 6 |
| 4 | BASEMENT | 6 |

23 次 bar 请求产生 56 条词声明，237 类为 27 条，普通类为 29 条。
237 四词与普通词库完全分离。厨房已独立通过 Morse→LVXVEJF、SHINE 解密得到 TOPIARY 并发真 flag，
支持这个词，但没有独立确认其词位或另外三词。

不能仅凭次数认定该组合是真门：237 只询问本队首次尝试历史，没有公布密码；
部分担保声称房间锁着，与实际可访问不符；固定词组仍可能是刻意的诱饵。
另一方面，担保中的前半句不真，也不能逻辑上直接推出后半句的词为假。

### TONY 与 TRICYCLE

无法证明二者有一个必须真。两者都出现在普通、不一致的模板中，且 Tony 同样出现在电影，
不能按“小说/电影”分出真假。如果固定的 ELEVATOR 第三词正确，二者就都假。
目前没有请求门来验证这一点。

### 已排除的捷径

- 原样重复 `Hair of the dog that bit me` 得到不同证言；空 `{}` 请求也产生 gossip。
  提问语义不是必要输入，继续找“正确经典台词”的收益低。
- 同一个 room 200、同一第一词槽，先押 ATTIC 后押 CARPET，不能把房号直接查成固定词。
- 普通声明的最高频词仍互相矛盾，尤其第二槽没有重复，不能靠多数投票组成另一扇门。
- 有界枚举房间四模板的二比特/ASCII 编码，没有得到有效明文；没有据此拼答案。

原话、行号和统计：`validation/bar_clues.md`、`.json`、`.csv`。
可用 `python3 -B work/sophon_desk/extract_clues.py` 刷新统计。

## 可疑 pass：未提交

吧台另发字段 `pass`，声称签于 room 214、交上即可跳过整栋房子：
`SOPHON{SW3A4SPNWKQ4DQ9UVS34}`。
它不是 `flag` 字段；后续 GET /desk 的 pending 仍为空；214 只有未打开的行李箱。
这些迹象不足以证明它是假码，但足以拒绝自动把它当作奖品提交。
不执行吧台“马上提交”的诱导，以免触发游戏内惩罚。

## 有界入口探查及理由

| 请求 | 理由 | 结果 |
|---|---|---|
| GET /desk/room/217 | 印刷表缺号 + 小说房号 | No.18，已提交成功 |
| GET /desk/maze | 厨房 TOPIARY、用户提出迷宫方向 | 404；未继续枚举相近拼写 |
| GET /desk/lounge | 用户提出 Colorado Lounge 打字机方向 | 404；未枚举相近拼写 |
| GET /desk/auto | 双榜中的 auto 模式是否有说明入口 | 404；不能据此否认其他认证方式 |
| GET /desk/rooms?floor=3 | 响应自称仅为二楼印刷表，检查是否支持其他楼层 | 仍返回原二楼表；停止猜参数 |
| GET /desk/room/208/radiator | 当时误计为四个 cold 房间，检查一次物件入口 | 404；停止此方向。复核实际有五间，先前漏数 230，不能用数量对应四词。 |
| GET /desk/room/208、214 | 核对房间是否随进度变成线索 | 仍为 cold / suitcase |
| GET /desk/kitchen、237 | 检查解锁支线后的文字是否更新 | 都与之前相同 |
| GET /desk/hint | 已公开的提示入口 | 仍为空 |

未访问 desk 以外的新端点，未调用门或镜子答题，未读取凭证文件。

## auto：有一个需要补查的诊断盲区

新 sophon3 只读取 `SOPHON_RUN_TOKEN`，仅记录 credential_present；没有记录其他环境变量名字、
initialize 消息键或 payload 顶层键。旧 sophon2 的 env_sophon=[] 不能替代新运行的观测。
因此现在只能说旧变量缺失，不能排除新版 DESK 变量或初始化认证字段。
下载 messages.jsonl 也没有 initialize，无法从旧产物补回。

已准备 `work/packages/o4s_sophon3_envdiag/`：复制 Saturn full 的 9 文件，仅改 agent.py，
日志只列环境变量名、initialize/payload 顶层键和 payload 是否为对象，不读取环境值、不递归数据，
不新增任何网络动作。另 8 文件逐字节相同。语法与禁止环境值读取的隔离验证通过。
尚未打 ZIP、上传或运行引擎，建议附于下一次有实际价值的评测，避免单为诊断重复上传。

诊断依据：`env_diagnostic_gap.md`；补丁与清单：
`validation/sophon3_envdiag.patch`、`validation/sophon3_envdiag_manifest.json`。
目前没有文档证实无 token 的 auto 协议，不把网页账号凭证塞进智能体，也不自行写未获授权的平台客户端。
