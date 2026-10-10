# 房子覆盖审计与少量 GET 候选

仅读取 `house_map.jsonl`、`desk_calls.jsonl`，未请求平台。共享调用记录核对至第253行。

## 房图已经闭合，但124条记录不是124个房间

| 检查 | 结果 |
|---|---:|
| 房间响应记录 | 124，全部 HTTP 200 |
| 唯一房间 | **123** |
| 重复记录 | `c5fe27xe2`，第122、123行，门表相同 |
| 去重后的有向出口 | **278** |
| 出口指向尚未读取的房间 | **0** |
| 从入口 `c5fe27d` 可达 | **123/123** |
| 非互通出口 | **0**（每条边的终点均有某扇门返回起点） |
| 重复读取时门表变化 | **0** |
| 门类型 | **14**，全部存在于通往已读房间的出口中 |

因此，这份实例中**没有公布过但尚未读取的门后房间**。不能据此证明服务没有未公开的条件房间；也不能把按房号 GET 的记录当作每条门边均实际走过的轨迹。124条响应中119个相邻响应对不是相邻房间，明显不是连续步行记录。

门类型统计如下。右栏只是从入口重建的一棵 BFS 树的发现边计数，不声称它就是当时实际走法。

| 门标签 | 全图出口数 | BFS 发现边数 |
|---|---:|---:|
| a crack in the wall | 20 | 9 |
| a low arch | 20 | 11 |
| a spiral staircase | 18 | 6 |
| ahead | 22 | 8 |
| back | 26 | 10 |
| left | 17 | 5 |
| right | 13 | 7 |
| service corridor | 17 | 7 |
| stairs down | 19 | 7 |
| stairs up | 14 | 8 |
| the closet | 25 | 10 |
| the far door | 17 | 5 |
| the long hallway | 24 | 14 |
| the red door | 26 | 15 |

没有“某类门从没通往探索区域”的缺口。唯一额外 `note` 在 `c5fe27jip6`，指向已解的 `/desk/house/tape`（No.16）；唯一 `flag` 在最深房 `c5fe27xe3`，是已交的 No.10。文字中的“楼梯永远向下”没有对应的新 doors 出口，不能据此断言存在下一层路由。

入口至最深房的最短已知路径有10条边：

`c5fe27d` → ahead → `c5fe2764c` → the long hallway → `c5fe27c8b` → right → `c5fe2710o7` → ahead → `c5fe271v82` → ahead → `c5fe273e7t` → right → `c5fe274evn` → ahead → `c5fe279i6t` → a crack in the wall → `c5fe27xe1` → the red door → `c5fe27xe2` → left → `c5fe27xe3`。

**实例边界：** 调用日志第245行再次 `POST /desk/house/enter` 返回了新入口 `43fb6cd`。旧地图的结论只适用于 `c5fe27…` 实例；没有离线证据证明新实例与旧实例同构或已遍历。也不需要为此自动重走旧图。

复现：

```sh
python3 -B work/sophon_desk/validation/audit_house_map.py work/sophon_desk/house_map.jsonl
```

机器可读结果含原文件 SHA-256、全部计数和特殊房间路径：`house_map_audit.json`。

## 新 GET 候选：仅三个低成本结构探测，尚未调用

没有新题面直接发布剩余两旗的隐藏路由。以下是基于已存在处理器的候选，不是推断出的答案，优先级低于已有题目线索。

| 优先级 | 候选 | 依据与预期 | 限制 |
|---|---|---|---|
| 1 | `GET /desk/rooms/x` | `/desk/rooms` 是已确认的房间索引；尚未试其普通子路由。仿照 hall 的未知子路由，可能给索引处理器的默认提示。 | 也可能原样返回房间表；不进一步排列猜词。`?floor=3` 已试，不重复。 |
| 2 | `GET /desk/room` | 已发布合同为 `/desk/room/<number>`。省略号码可检查入口默认提示，比再猜房号更有依据。 | `/room/237/mirror`、`/room/208/radiator` 已显示未识别后缀；不要再尝试镜子子路径。 |
| 3 | `GET /desk/house/room` | 已发布合同为 `/desk/house/room/<id>`；省略 id 是最后一种尚未检查的结构分支。 | `/house/map`、`/house/x`、`/house/answer` 均仅返回 `not_inside`，即使刚重新 enter 也如此；不能因此判断当前会话真的没进屋。房图已闭合，此项预期收益很低。 |

这三个都只建议至多一次 GET，由主线决定是否执行。没有强证据支持继续增加新地点名。

## 已有探测说明了什么

- hall 的第215/216行 404 确实暴露了 `POST /desk/hall/answer`，但该成功经验不能推广为所有路由都有隐藏提交口。
- kitchen、novel、hedge、library、ballroom、photo、darkroom 的 `/x`，以及 typewriter/lipstick、bar/pass，均回父路由内容；这些处理器忽略或统一处理多余路径的可能性较大，继续换后缀收益低。
- `/desk/receipts/x` 与 basement、elevator、topiary、mirror、boiler、snowcat 返回通用 `no_such_place`，没有新入口提示。
- `/desk/quotes/x` 的 GET 返回 `wrong_answer`；`/desk/frontdesk/x` 的 GET 返回值班任务。因此这里不能把 GET 当作普遍无副作用的保证，不建议对 door、checkout、flag、已停用的镜子解题入口做结构探测。
- 共享日志第251/252行已确认 No.6 盖章，现在是 **20/22，仅缺4、17**。REDRUM 已解决，故 lipstick 或其别名不再列为候选。

本轮没有调用上述候选、没有重复提交旗标，也没有启动任何评测。
