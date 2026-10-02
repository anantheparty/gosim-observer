# 正确 Model GPU 版本的免费公开测试

本目录保存 `gosim_model_gpu_public_test.zip` 的7个规范输出，只将 CRLF 替换成 LF；其他字节保持原样。`download_manifest.json` 记录原始/规范化SHA256、ZIP SHA256和验证结果。

## 版本与范围

- 正确上传包：`observer_model_gpu.zip`。
- 上传包SHA256：`2409c64e4c1435139d659f211dce2523fd478ee5d4216a36b320a4528c6d2ff8`。
- 平台source fingerprint：`24dd46d6dd3c7dfc19538f3347d4413e4ffd674c4bdec502c6a154f62e6fe97a`。
- 下载ZIP SHA256：`5108cb57abcb360a2037d571c4c8e610b18bd08b4631738dabb9e3349b5477be`。

这是官方免费 `v4-public-test`，时限300秒，未消耗正式四卡评测额度。正式四卡时限900秒。本次不代表正式比赛成绩。

之前第一个“Observer API GPU”项目误选旧ZIP的prepared_download不纳入本次结果，也不计为真正GPU试验。这里的版本识别以本次实际上传包、平台fingerprint和完成输出为准。

## 实际结果与耗时

| 项目 | 官方/日志记录 |
|---|---:|
| 总分 | 248.067256 |
| 基础科学分 | 1135.261887 |
| required罚分 | −850.000000 |
| uniformity罚分 | −37.194632 |
| 结束状态 | survey_complete |
| accounted wallclock | 91.151秒 |
| agent wallclock | 90.427秒 |
| remote check | ok，4.643秒 |
| 实际remote规划调用 | 4次，合计26.129秒 |
| 兼容API chat调用 | 7次，合计30.759470秒 |

`agent.log` 记录 transport=`official-compatible-api`、model=`traditional-cuda-planner`、gpu_available/backend_ready均为true。这次证明确实由正式兼容接口完成GPU远端规划调用，随后按预算使用CPU规划；不是仅做本机连通性检测。

公开测试没有发布REQ（issued=0），因此不能验证新期限DP的收益。总分及计分分项与已归档CPU phase公开测试相同，但decisions/observations哈希不同、观测记录数2914对2916，不能将相同总分写成完全相同轨迹，也不能据此宣称GPU增加分数或更快。

## 校验

官方报告的decisions、messages、observations三个SHA256全部与规范化文件相符；workflow内嵌score_report与单独报告完全一致。

7个原始及规范化输出经实际本地runtime token字节匹配扫描，matches=0；通用凭据模式扫描也为0。未保存或打印token。归档过程未启动UI或新评测，未进行Git commit或改动共享index。
