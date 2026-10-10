# Sophon CTF 第 1 轮（2026-10-06，18:47 UTC 起）

## 已完成

- 两路研究：公开仓库全部本地历史、邮件的文学线索；另核查所有既有公开下载包。
- 本轮累计提交两次有对应证据的候选，输出如下，已由授权脚本写入 `work/online/sophon_flags.log`：

```text
2026-10-06T18:48:50Z SOPHON{43728561} -> ERR HTTP 422 /functions/v1/sophon/desk/flag: That doesn't look like anything from here.
2026-10-06T18:59:47Z SOPHON{zampano} -> ERR HTTP 422 /functions/v1/sophon/desk/flag: That doesn't look like anything from here.
```

- 已发现主线此前也试过 `house-of-leaves`、`the-shining`，两者均拒绝；不再重复或变换数字置换方向。
- 未读取凭证文件、未自行写平台调用、未改授权脚本、未触碰正式赛或 c3* 包。

第二次选择 Zampanò，是因为日期已定位到他的注记，且其中有姓名归属的语义；仍被拒绝。
这只否定该候选字符串，不否定小说线索本身。`johnny-truant` 暂不提交：Johnny 也有更直接的
《闪灵》看守/台词解释，邮件未要求人物全名；没有新增证据前，不继续换人名或拼写。

19:00 UTC 更新：已读取主线保存的 `visibility_check.json`。同一登录身份的 current_competition
含 Sophon 的 extra_phase_id，四个新旧榜 RPC 都返回空；成功状态采用主线的查询记录。
因此已排除本次查询因缺 extra_phase_id 被过滤的解释。准确结论是新旧表均无可见记录，
仍不能排除隐藏队或未结算/未写入的解题。

## 唯一线上实验：土星 + 季末等待

| 项 | 记录 |
|---|---|
| 包目录 | `work/packages/o4s_sophon3_saturn_full/` |
| ZIP | `work/packages/o4s_sophon3_saturn_full.zip`，11220 字节 |
| SHA-256 | `7fddcea0b6727fbe13508497ca0123d250664b236e8c4cbcf37eaca3047cbf26` |
| 与 jfull 差异 | 9 文件中仅 probe_config.json 的 dive_object 改 saturn |
| 与旧土星版差异 | 保留原末曝光，之后 wait 到季末 |
| 本地验收 | 两个练习码；6480 异常观测行；survey_complete |
| 本地一致性 | 原土星版所有先前 decisions 相同、observations.csv 字节相同 |
| 末曝光 | 2026-11-30T06:28:00Z，距土星 0.000° |
| revision | `8493a03a-c298-4c73-9f42-9c3153e51929` |
| 预检 | passed，run `b8a5dc3d-ac70-498e-9964-edeed1a7ed6c`；accepted=true |
| 当前状态 | 授权 sophon_eval.sh 等待全队评测空闲；尚无本次真卡结果 |

此轮补上旧土星提前结束、未进入复核的覆盖空隙。木星 full 无回执仍是对照。
文学旁证是《2001》原著旅程终点土星、Kubrick 电影为木星，与《闪灵》共享导演；这只是选星动机，不是验收规则。

## 新发现

1. **THESHINING 未必是要交的 flag**：caretaker / “Here's Johnny!” 可能先指向联系 Johnny，再由邮件指向《叶之屋》。
2. **日期已定位**：JAN 5 1997 是《叶之屋》导言 xix 页的 Zampanò 注记。未发现唯一二次密码或提交格式；一次 `zampano` 候选已被拒，停止继续换人名猜测。
3. **公开历史有限**：59 个浅克隆提交，无 token 注入、私有验收或回执实现。10-06 文档删除 Johnny 邮箱但保留 API，旧新流程确有演进，具体兼容性未知。
4. **公开包无藏匿线索**：未发现异常成员、ZIP 注释、附加数据、自由文本题面或真实 flag。
5. **放弃“给行星末曝光分配有效目标”的额外上传**：真实公开目录赤纬全部为负；最后木星位置距最近目录目标 21.11°。60 个夜末采样的最小距离分别为木星 21.11°、土星 54.09°、火星 20.93°、金星 36.02°，远超视场。采样不是连续时间证明，但已排除当前末曝光简单加合法目标的方案，空分配很可能是有意设计。

## 等待期间与下一步

- 原授权评测脚本继续运行。`watch_saturn_full.py` 仅监视本地下载目录，每 30 秒检查一次，不请求平台；下载稳定后自动扫描并 ping 主线，请其唤醒本子会话继续分析。最多等待 4 小时，避免无人跟进或重复上传。
- 已按主线“其他端点先问”的规则，申请最多 3 个只读 GET（函数根、desk 根、desk/receipt）；**尚未获准，也未调用**。它们只是有界的 CTF 路由假设，非已知接口。
- 土星结果落地后，先核验末曝光、survey_complete、score 步骤、token 存在性及回执，再决定是否值得其他行星 full 实验。发现真实 flag 才按授权提交并转发原样响应。

详细证据：

- `history_findings.md`、`puzzle_followup.md`
- `validation/public_archive_audit.json`
- `validation/planet_catalog_separation.json`
- `validation/sophon3_saturn_full_package.json`
- `validation/sophon3_saturn_full_validation.json`
- `validation/saturn_full_watch.json`
