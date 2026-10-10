# Sophon 文学线索复查（2026-10-06）

本轮只读既有推导、公开卡和公开资料；没有读取凭证、调用平台、提交候选、改包或运行仿真。
收到主代理补充：`house-of-leaves` 与 `the-shining` 两个规范化候选也已 422，不再建议重复提交。
18:48:50 UTC 主代理又验证 `43728561` 为 422；不再延伸数字置换猜测。

## 结论

第一层数学解密仍然完整自洽。没有发现能唯一导出新 flag 的二次密码。
比继续换大小写或添加 `-ok` 更有依据的是下面两条线索；它们都属于**待验证的流程/书内定位解释**。

| 线索 | 新发现与证据 | 推论及边界 |
|---|---|---|
| THESHINING → Johnny | 本轮补强：CLI 称 Johnny 为 **night caretaker**；《闪灵》的 Jack 是旅馆冬季看守，电影又有 “Here's Johnny!” 台词。作者官网说明看守身份，ACMI 电影博物馆说明台词关联。 | 天空书名可能首先引导联系 Johnny，邮件再引导读《叶之屋》；因此 THESHINING 不必本身就是 flag。它也说明 Johnny 不一定只能解释为 Johnny Truant。不能由此断言关卡依赖顺序。 |
| JAN 5 1997 → 导言 xix 页 | 此前只有读者年表；本轮找到 Ohio University 学位论文直接讨论该日期的 Zampanò 注记，并标注原书 xix 页。注记谈到出版手稿、姓名归属及文档经受时间检验。 | “after JAN 5 1997” 可以是定位这段注记，`final trials` 与其中“时间检验”存在语义呼应。注记里 **“my name take its rightful place”** 是比随意猜作者名更具体的下一层提示，但把它解释成提交 `zampano` 仍属假设。 |
| THESHINING → Kubrick → 2001 | 本轮核验：Penguin 的《2001》小说简介明确写到土星环；BFI 的同名电影介绍明确写木星任务和导演 Kubrick。 | 如果题目希望跨同一导演的电影联想，那么“小说土星 / 电影木星”可支持两个收尾方向；不证明私有 checker 的目标。相比改分数或发明指令，这是适合单变量实测的假设。 |

出处：

- [Stephen King 官网：《The Shining》剧情与创作说明](https://stephenking.com/works/novel/shining.html)。
- [ACMI：《The Shining》文化影响及 Johnny 台词](https://www.acmi.net.au/stories-and-ideas/the-shining-play-with/)。
- [Ohio University 学位论文：The Divine and Miss Johanna](https://etd.ohiolink.edu/acprod/odb_etd/ws/send_file/send?accession=ohiou1145555978&disposition=inline)，搜索 `January 5, 1997`；这是直接引述原书的研究资料，不是比赛提示或官方答案。
- [作者网站读者年表](https://forums.markzdanielewski.com/forum/house-of-leaves/house-of-leaves-aa/3912-key-to-all-mythologies-the-introduction)，仅作日期交叉核对。
- [Penguin：《2001》小说简介，土星环](https://www.penguinrandomhouse.com/books/538851/2001-a-space-odyssey-by-arthur-c-clarke/)。
- [BFI：太空旅行电影，《2001》木星任务及导演](https://www.bfi.org.uk/lists/10-great-films-about-space-travel)。

Mary 未得到唯一解释。能搜到 Mary Shelley 的章首引用和虚构评论者 Mary Widmunt，但没有题面索引把 Mary 锁定到其中一人，因此都不建议新增为 flag 候选。没有查到 `final trials` 是这本书的特定专名。书籍/电影的迷宫、恐怖建筑等共同主题也不足以成为提取规则。

## 建议的下一步（按价值）

1. **先检验旧流程是否已经完成到“发信”这一关。** 已有 CLI 文本明确公开 caretaker Johnny 的入口；天空标题和影视典故解释了为何会去联系他。用本地 sophon1 的既有响应/运行元数据以及仓库历史比对旧 `sophon_solves.key` 的写入阶段：它到底代表“拿到邮件”还是“回答邮件”。若写入发生在发信时，再猜邮件标题的收益会很低。这项检查不需要新平台调用。
2. **把日期当作书内定位，核对合法预览/已有书本导言 xix–xx 页的排版和紧接段落。** 日期已精确定位，值得核查是否存在明确的姓名/索引指令；目前只见姓名归属与检验的语义，没有明确 flag 格式。若主线确实要在两个剩余的人名候选中选一次有依据的探索，`zampano` 比 `johnny-truant` 更直接承接日期，但还不构成推荐立即提交的充分证据。后续新产物可有目标地检索 `Johnny / caretaker / Zampanò / Zampano / Navidson / xix / rightful / trial / receipt`；本轮已下载真卡公开配置、公告、预报和目标中未找到这组文学词。不要据人物名直接猜 `desk/files/<name>` 路由。
3. **土星 + survey_complete 是一个有文学旁证的单变量运行。** 原土星运行没有完成复核，不能和已 verified 的木星作等价排除；主代理已经准备此实验。保存末次曝光坐标、地平高度、终止状态和 score 步骤，再比较回执。此前仅高度 2° 左右的土星曝光满足练习器，但不能证明真实规则也接受同一高度；先保持其余逻辑一致，避免同时引入多处解释不清的变化。

这些建议不构成“又有三个答案”。本轮新增的是可验证的关联与日期段落的具体语义，不是一个已经解出的 flag。
