# Sophon 彩蛋：Johnny 的前台

Sophon 是比赛附带的彩蛋赛，不计入正式成绩，也没有奖励。题目的主题来自《闪灵》（The Shining）和《叶之屋》（House of Leaves）。

参赛队通过平台的 Sophon 接口（`/functions/v1/sophon/desk/...`，"Johnny 的前台"）解谜、交旗。Pleiades 解出了调试榜 22 题中的 21 题，只剩 No.4。自动榜（按两倍计分）一题也拿不到：它需要运行里注入 Sophon 令牌，而正式运行中没有注入。

## 经过

**10-05：字形和 Johnny 的信**
- Sophon 练习阶段用的是一张 25 根光纤的练习卡（Paranal，60 晚）。
- 在"字形夜"，落在特定光纤上的目标得分是参考条件的 2.5 倍。这些光纤排成 5×5 图案，每晚拼出一个字母。
- 探测包 `o4s_sophon1` 三次读出 THESHINING。解码逻辑在正式智能体的 `agent/sophon_probe.py`。
- 按文档调用 contact-johnny 后，Johnny 回了一封信。信里是一道 Sakurai (1.139)/(1.140) 式的习题：判断 8 个可观测量三元组能否让该等式恒成立。
- 成立的那几行各给出一组 "No." 置换，把它们依次作用在信中便条的 8 字母分组上，得到：
  > I SAW A COLLECTION OF LEAVES FORM AN ENDLESS HOUSE SEE YOU AFTER JAN 5 1997 WHILE EVERYTHING SHOULD BE REVEALED THROUGH THE FINAL TRIALS
- 详见 `desk/johnny_first_mail_analysis.md`。

**10-06 18:47 UTC 起：前台开放**
- 共 22 道调试题，当晚解出 20 道。
- No.17（237 号房的镜子）10-07 05:14 解出，方法是检查接口合同，不是猜字符串。

**No.4 没有解出，连对应哪道题都没能确定。** 线索有两条：
- 酒吧里拿到的 "pass"：交上去是假的（"Gotcha. That pass was never real."），但没有扣分。
- 237 号镜子的问题"你最先试的是哪扇门（四个词）"：试过 5 种写法都不对。后来 No.17 是用空请求体解出的。

酒吧警告"走错一扇门，Johnny 就全忘了"，所以我们没有再试新的 `/desk/door/*`。

**自动榜：**
- 运行里拿不到文档中写的 `SOPHON_RUN_TOKEN`，只有 `OBSERVER_RUN_TOKEN`。
- 10-07 晚用后者试了一次，返回 401 token_invalid。
- 自动榜因此为 0。

## 22 道题

时间是盖章时间（UTC）。路径都在 `/functions/v1/sophon` 之下，需要登录，并带请求头 `x-sophon-site: 1`。

| No. | 题名 | 解法 → 答案 | 盖章 |
|---|---|---|---|
| 1 | 宇宙为你闪烁 | 运行回执里的天空码（`GET /desk/receipts`） | 10-06 18:53 |
| 2 | Here's Johnny | `POST /desk/door` say=THE SHINING | 10-06 18:53 |
| 3 | 喝醉的 Johnny | `GET /desk/door/MIRROR-TOPIARY-ELEVATOR-BASEMENT` | 10-06 19:50 |
| 4 | （未解） | — | — |
| 5 | Jack 的打字稿 | `POST /desk/typewriter` word=GOLDROOM | 10-06 19:52 |
| 6 | 在天上写 REDRUM | 一次 Sophon 运行（包 `o4s_sophon4_glyph`）里，某次曝光只把目标分给一个字母的 5×5 字形光纤（光纤号 = 行×5 + 列，第 0 行高度最低，第 0 列方位最小）；回执里的字母码 | 10-06 20:38 |
| 7 | Sakurai 老师的作业 | `POST /desk/novel` plaintext=上面那句 112 个字符的便条明文 | 10-06 19:53 |
| 8 | 被改过的名著 | `POST /desk/quotes` word=TORRANCE | 10-06 19:53 |
| 9 | 无尽的房子 | `POST /desk/house` line="Whoever finds and publishes this work shall be entitled to all proceeds." | 10-06 19:59 |
| 10 | 五分半的走廊 | 用 `POST /desk/house/enter` 走到最深的房间 | 10-06 20:04 |
| 11 | 树篱迷宫 | `POST /desk/hedge`，按广度优先搜索出的步骤走 | 10-06 19:53 |
| 12 | 双胞胎 | `POST /desk/hall/answer` word=GOLDROOM；这个入口只出现在 `GET /desk/hall/3` 的 404 文本里 | 10-06 20:20 |
| 13 | 金色舞厅的宾客名单 | `POST /desk/ballroom` name=Louise Kensington | 10-06 20:04 |
| 14 | 退房 | `GET /desk/frontdesk` 连续 9 次，直到 "season is over"，然后立刻 `POST /desk/checkout {}`（中间再访问前台会重开一季） | 10-06 20:11 |
| 15 | 1921 年的照片 | `POST /desk/photo` answer=Arcturus | 10-06 20:08 |
| 16 | Navidson 的卷尺 | `POST /desk/house/tape` room=attic | 10-06 20:03 |
| 17 | 镜子里是你自己 | `POST /desk/room/237`，请求体为空 `{}` → "It was you all along." | 10-07 05:14 |
| 18 | Room 217 | `GET /desk/room/217` | 10-06 19:02 |
| 19 | Hallorann 的闪灵 | `POST /desk/kitchen` word=TOPIARY | 10-06 18:55 |
| 20 | 人列计算机 | `POST /desk/library` bits=11011010 | 10-06 19:53 |
| 21 | 智子的倒计时 | `POST /desk/darkroom` zero_utc=2026-10-03T05:46Z | 10-06 20:09 |
| 22 | Grand Finale | 退房后，一次 Sophon 运行最后一次曝光对准真实的土星，最后一张回执给出 SOPHON{YZWVJ28SETFQY2SF6Q33} | 10-06 20:11 |

**几条教训：**
- 交错旗不扣分，但前台只回 422 "That doesn't look like anything from here."，不提示方向；走错门（`/desk/door/*`）则可能清空进度。
- 未知的子路径有时会在 404 文本里透露真正的答题入口（No.12）。
- 来路不明的道具（酒吧 pass）可能是陷阱。

## 目录

| 路径 | 内容 |
|---|---|
| `desk/desk_calls.jsonl` | 与前台的全部 765 次交互。每条记录包括时间、方法、路径、请求体、状态码和回复，以及响应头名称和 cookie 名称（不含值），不含任何凭据 |
| `desk/*.py`、`desk/*.sh` | 前台调用工具（`desk_call.py`、`sophon_desk.py`、`desk.sh`）、交旗（`hand_in.*`）、回执扫描、提示监视、Sophon 阶段的提交脚本 `sophon_eval.sh` |
| `desk/*.md` | 各轮笔记：第 1 轮记录、四个词的结构和文献线索、Johnny 第一封信的推导、历史发现、行星俯冲（sophon3）报告 |
| `desk/rooms.json`、`desk/house_map.jsonl`、`desk/darkroom.json` | 房间、房子地图和暗房的原始回复 |
| `desk/validation/` | 各题的核查与审计：No.4、No.17、酒吧 pass、自动榜合同、REDRUM 字形、令牌注入等，以及本地验证脚本。本地运行只保留小的汇总文件 |
| `packages/` | Sophon 阶段提交过或准备过的探测包源码（不含编译出的内核库）。详见下文 |
| `tools/` | 链式提交、本地 Johnny 接口桩、本地 Sophon 卡生成、字形本地运行等辅助脚本 |

`packages/` 下各包：
- `o4s_sophon1/2` 是 c18 加 `sophon_probe.py`，这里只放了与 c18 不同的文件；
- `o4s_sophon3_*` 是行星俯冲探测；
- `o4s_sophon4_*` 包括天空写字、鉴权测试、自动榜和 No.4 的试验包。

**不在仓库里的：**
- 主办方的 Sophon 卡数据（`card/`、`local/` 和各个 zip）；
- 本地运行的原始输出（观测、动作、消息、日志）；
- 任何凭据。

凭据只从环境变量读取（`~/.gosim_cred`）。`desk/sophon_eval.sh` 上传前会做一次个人信息扫描，它的扫描名单已改为从仓库外的 `~/.gosim_scan_patterns` 读取。
