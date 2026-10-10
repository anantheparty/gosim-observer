# 从假 pass 引出真奖励：一个遗漏的输入类

本轮先做离线研究，随后由主线明确批准一次验证。机器审计为 `pass_keyword_audit.json`，
记录源日志指纹、行号与逐字输入覆盖；实际调用及结果见下文。

## 首选可检验候选

```json
{"say":"fake"}
```

沿用已发布的 `POST /desk/bar`，不换接口、不改通行证、不访问任何四词门。理由是服务端已经
确认通行证 `never real`，但 237 次历史酒吧 POST **没有一次包含独立词 fake、false、liar、
lie、lying、forged、forgery，也没有 real pass**。此前“揭穿骗局”实际只覆盖 `Gotcha.` 与
`That pass was never real.`；这两句不会命中一个普通的 `fake` 关键词条件。

这纠正了“揭穿已经充分测过，所以不用再想”的概括。它不证明服务端确实有关键词条件，也
不是从题面唯一推出的正确答案。但在“假证引出真奖励”的工作假设下，比给假码套一层未提示
的加密、更换路由或重置剧情所需的额外假设更少。

可能的最小行为链是：收到假 pass → 前台明确判假 → 返回酒吧指出 `fake` → 取得真奖励。
现有记录覆盖前三步的前两步；所有声称覆盖第三步的请求都没有这个单词。服务端若只是普通
gossip 生成器，下一次仍会是普通回复；若确有 `fake` 专门分支，这个输入可以区分它。

执行边界：须主线批准，只测一次。若取得实际签发串，按最新约束先报主线，不自行交旗。
若只给普通 gossip，不能据此擅自追加 liar/forged 等近义词；也不能说整条假 pass 支线已被排除。

## 次级缺口，不与首选混在一次实验中

历史拒收短句是 L396 的 `No.`，并非无标点 `no`。若私有判定采用简单 trim/lowercase 后精确
比较，句点仍会保留。这意味着“试过 no”也应收紧为“试过 No.”；但没有证据支持精确的拒收
词表，当前不申请或执行第二次请求。

`real pass` 从未回说给酒吧，但它同样没有公开的作答合同，不据此批量生成“给我真证”的句式。

## 协议层检查及限制

- `desk_call.py` 只记录 status/body，丢弃响应头；其 Client 不带 CookieJar，每个脚本进程重新
  登录。这是实际存在的观测缺口，不能声称已穷尽所有 HTTP 信息。
- 但没有任何题面指向响应头或 Cookie。根页剧情持续推进，前台杂事计数也曾跨多次请求继续，
  21 个奖励已成功；不支持把“每次登录”直接判成全局会话丢失。普通 Supabase 前端也使用
  登录态 Authorization 调用，未发布本题 Cookie 合同。因此这一方向低于显式 `fake` 候选，
  不为它修改认证或读取凭证。
- 公共 core SQL 的邀请码帮助函数采用与这些旗标一致的去歧义字符集，但它生成的是 8 位
  邀请码，不是 Sophon flag。它既不证明旗标算法，也不给出从假串计算真串的密钥。

## 已批准实验结果

主线通过 HAPI 明确批准仅一次 `say=fake`，要求普通 gossip 时不追加近义词，新旗也先报告。
已在 `research_actions.jsonl` 写依据后执行；没有上传、评测或请求四词门。

- `desk_calls.jsonl` L466，2026-10-07 13:33:21Z：HTTP 200，只有普通
  `ok/johnny/door/message` 四字段；内容为 W2=CARETAKER 押236、237担保 W4=BASEMENT、
  W2=GRADY 押208。没有新旗、新 pass 或新合同。
- 已有每小时值守随后记录 L467–468（13:34:00/05Z）：hint 仍空、found 仍21条，仅缺4。
  因此这次也没有后台直接盖章的可见奖励。没有为复核额外发 GET。
- 该观察排除“当前剧情状态下说 fake 即领奖”这一简单模型；不证明所有指控条件或早期
  分支都无效。按批准边界，不追加同义词。

## 一个应当明确区分的真 pass

“假 pass 应该引出真 pass”已经有一组直接的叙事对应：

| 假通行证 | 真通行证 |
|---|---|
| desk L25：`Hand it in at the desk right now and you can skip the rest of the house.` | house_map L124：`The deepest room. Five and a half minutes from the door, and there is nothing here but a staircase going down forever, and a pass on the bottom step.` |
| 由酒吧给出独立 `pass` 字段；前台判假 | 从房屋最深处取得 `flag`；desk L156 已盖章 No.10「五分半的走廊」 |

这是明确存在的真通行证，不是为解释 No.4 臆造的对象。假证承诺绕过整座房子，真证放在
房屋最深处；两者有自然联系，但服务器没有明说这就是假证唯一用途。

因此应分开两件事：**取得真 pass（已完成 No.10）**，与**揭穿假 pass 是否另奖 No.4（未证实）**。
L407–408 已把真 pass 经 say 和 pass 两种字段返还酒吧，均只给 gossip，不能再把同一个操作
当作新解法。当前仍没有 No.4 的可提交真码，也不能由此断言该题不可完成。
