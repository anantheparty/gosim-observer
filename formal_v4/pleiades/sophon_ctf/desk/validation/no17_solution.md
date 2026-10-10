# No.17「镜子里是你自己」

2026-10-07T05:14Z 解出并盖章。没有调用任何四词 `/desk/door/*` 路径。

此前五次均按公开合同提交非空 `answer` 字符串，全部得到相同 `wrong_answer`。离线审计未发现另一扇四词门、隐藏历史字段或日志格式问题，因此把唯一未覆盖的输入分支缩到缺少 `answer` 字段。动作前已记录到 `validation/research_actions.jsonl`：这是合同诊断，不是第六个字符串猜测。

请求与平台原文：

```text
POST /functions/v1/sophon/desk/room/237 {}
→ 200 {"ok":true,"johnny":"It was you all along.","flag":"SOPHON{RPY29USNAHHMAZ4ZUCHR}","message":"It was you all along."}
```

`hand_in.sh` 原样回复：

```text
2026-10-07T05:14:27Z SOPHON{RPY29USNAHHMAZ4ZUCHR} -> 200 {"ok":true,"johnny":"The desk stamps it.","no":17,"name":"镜子里是你自己","solved":true,"message":"The desk stamps it."}
```

题意的“it only asks about you”最终不是要求复述历史门名；正确动作是不给答案，镜中只剩请求者自己。

此后根 desk 已核对为21条 found，仅缺 No.4。空基础门 POST 返回 `That's not what the sky said.`，无状态变化；假 pass 的空 flag、退回 bar、214 空 POST、服务端原话及三句电影酒吧台词均未触发新分支。60次固定 `listen` 采样全部只有普通 `ok/johnny/door/message` schema，且文本均属于既有九类模板。
