# 请求规划 + GPU 候选：官方免费公开测试

本目录保存 `gosim_request_gpu_public_test.zip` 的7个规范输出，仅CRLF→LF。官方decisions/messages/observations三个SHA-256及workflow内嵌评分校验全部通过，actual runtime token字节匹配0、通用凭据模式匹配0。原始/规范化SHA位于 `download_manifest.json`。

## 来源

- 上传包：`observer_request_phase_gpu.zip`，SHA-256 `bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec`。
- 平台源码指纹：`75fa4058539fbe28fafd0e56d4fab0cc8af0108d7cbb6ec87ee1f268a126c0d5`。
- 下载ZIP SHA-256：`335f82c349f9292f009cd6407a8e5478e71459888185fc58dd826bedb3559a88`。

root在UI核对项目Observer Request GPU及该完整指纹，并确认上传filename；另与本地官方project_digest结果匹配。下载输出本身没有指纹。此为免费300秒公开测试，未消耗正式四卡额度，不能替代900秒完整评测。

## 实测结果

| 项目 | 官方报告 / 日志 |
|---|---:|
| 总分 | 430.598521 |
| 基础科学分 | 1164.694613 |
| required缺失 / 罚分 | 14 / −700 |
| uniformity罚分 | −34.096092 |
| REQ发布 / 完成 / 奖励 | 0 / 0 / 0 |
| 完成状态 | survey_complete |
| accounted / agent wallclock | 125.814 / 124.872秒 |
| health配置 / 实耗 | 60 / 4.841秒，ok |
| GPU baseline成功 / 失败 | 6 / 0 |
| 远端规划实耗 | 37.735秒，含初始化10.025秒 |
| 重复决策p90 | 5.7891秒 |
| 兼容API chat | 9次，日志合计42.555660秒 |
| CPU baseline | 287次，76.264791秒 |
| 请求DP build / solve / override | 0 / 0 / 0 |
| CPU裁剪 / 请求边界等待 | 0 / 0 |

正常finish summary存在，workflow没有忽略in-flight响应，输出无Traceback。后端close ACK未单独记录，不能从这些输出声称已核验该ACK。

本公开场景证实distributed入口通过正常兼容API完成GPU baseline，同时使用CPU路径，且没有传输失败。未发布REQ，所以没有执行请求池构建、DP求解或请求观测覆盖，不能验证REQ逻辑。

对照旧CPU Phase公开测试248.067256分，本次高182.531265；对照前次Phase GPU公开测试236.561912分，高194.036609。程序与轨迹不同，不是隔离变量的消融，不能将差值归因于GPU或REQ。health本次4.841秒也不证明此前四卡12秒超时的原因。

归档未操作UI、部署、性能调用、上传源码或Git index；未保存或打印凭据。
