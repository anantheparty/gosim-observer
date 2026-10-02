# 公开 REQ 单步分布式门检

日期：2026-10-03。真实 owned compatible API，冻结算法源与 `distributed_request_fallback_20261003` 相同；未修改或重启生产服务。

| 快照 | 真实 GPU 基线含网络 | 本地请求建池 | 总单步 | 分配纤数 | 条件有限列 |
|---|---:|---:|---:|---:|---:|
| L1 V4RQ0001 刚发布 | 1.3678 s（初始化 0.3927 s） | 13.3147 s | 14.7039 s | 16 | 335 |
| L1 V4RQ0002 刚发布 | 1.1162 s | 11.8872 s | 13.0218 s | 15 | 334 |

两次真实 GPU choose，PRO6000 双精度固定工作量，服务 gate defaults SHA `9fdde225b2926106a208f6c6a8458a10bda5a1fd1ed75af9411bedc52b0e9f30`。官方 FiberGrid 检查基线和最终动作均落到对应 glass/fiber；预测 ID/index/fiber 一致，factor 有界且数值有限；曝光和公开夜窗合法。两次 REQ 精解均可行，计划的首个请求观测在未来，因此该快照仍采用 GPU 基线，没有声称已通过本步完成 REQ。真实裁剪分支在之前公开 stub 门检验证，完整 CPU future L1 已验证两请求完成。

随后用本地 TimeoutError 注入测试同一异常边界，CPU 回退动作再次通过几何检查；不产生第三次网络 choose。close 已执行，session/connection 清空。

## 限定

- 这是单步接口门检，**不是整卡回放，也没有新的得分**。两个独立冷账本快照 scores/factors 均为 0，没有装入历史科学分；质量尺度条件固定 .55，静态地形使用公开 coarse 信息的显式参考先验。
- 每个单步将 budget.credit 预置 1，确保门检确实走网络；此 fixture 不模拟完整赛季的配额预算。生产预算代码未改变。
- 初始化只读公开目录和 config；REQ 从自己的已完成回放所发公开 messages.jsonl 取得，天气/通知严格过滤 issued_at <= 当前快照，只提取已发布字段，不读 truth、score_report 或未来天气。凭据不写入结果、不哈希、不输出。
- 返回 stats 字典被本地 REQ overlay 共用，因此其中 planning_seconds/request_dp_* 是本地总规划统计，不是纯 GPU 时间。应读取 distributed.remote_baseline_seconds 的差值作为真实网络耗时，或具体 GPU phase 子计时。
- 初版门检脚本先导入 NumPy、后载入线程上限，CPU 建池 dot 产品发出六行 floating-point warning；所有输出预测有限值断言均通过。生产冻结 entry 已在 NumPy 之前固定线程。保留 `executed_helper.py` 与其原 SHA，使本次执行源可回溯；当前通用 helper 会提前设置线程。

结果：`checks.json`，执行源：`executed_helper.py`。没有上传平台，没有消耗正式评测次数。
