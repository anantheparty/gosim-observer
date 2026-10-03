# 请求规划 + GPU候选完整评测：δ

归档 `gosim_request_gpu_delta_result.zip`，SHA-256 `b5d201c587316b405b18c6a927c376b98c6260a689333a026d393becf543fc7e`。7份输出仅CRLF→LF；官方三个输出SHA与内嵌评分校验通过，实际runtime token匹配0，通用凭据模式匹配0。

root确认来自08:38 JST完整四卡批次，上传bfcc8ed7…、源码指纹75fa4058…，匹配本地候选记录。下载输出本身未提供源码指纹。详细来源和分项见 `download_manifest.json`。

## 分数与计时

`6523.825782 科学分 + 100 REQ + 100 报告 − 300 required − 0.739024 uniformity ≈ 6423.086757`。报告分项已舍入，与总分算术末位有1e-6差异。

| 项目 | 本次 | 前次Phase δ |
|---|---:|---:|
| 总分 | 6423.086757 | 5206.005545 |
| 科学分 | 6523.825782 | 5965.730600 |
| required缺失 | 6 | 19 |
| REQ完成 / 发布 | 1 / 2 | 1 / 2 |
| uniformity罚分 | −0.739024 | −9.725055 |
| 失效观测 | 280 | 252 |
| accounted wallclock | 475.229 / 900秒 | 365.121 / 900秒 |
| 启动health | TimeoutError60.037秒 | TimeoutError12.009秒 |
| GPU规划调用 | 0 | 0 |

总分增加1217.081212：科学分增加558.095182，required罚分减少650，uniformity罚分减少8.986031；REQ和报告奖励各仍100。两次程序和轨迹不同，不能将差值归因于GPU或请求DP单个组件。

## 实际算法执行

health60秒失败后，程序停用远端；GPU choose成功/失败均0，transport choose失败计数0。health本身失败1次，不能把0个choose失败称为网络成功。

CPU baseline1101次，耗时300.910315秒。REQ DP构建8次耗时84.262577秒，求解116次耗时0.756549秒；实际请求观测覆盖2次、边界等待1次、基线裁剪4次（均转CPU），forecast失败0。总planning385.965秒。

请求DP在真实δ场景执行了，但奖励仍只完成1/2：V4RQ0001完成4/8、要求6，因此无奖励；V4RQ0002完成6/8获100。一次正确报告获100。不能从DP的infeasible0或forecast_failures0认定其预测一定正确。

survey_complete、finish summary存在、ignored_in_flight=false，475.229秒完成。启动等候真实计入时耗。60秒仍超时，15秒发现周期本身已不足以解释本次失败；实际relay/网关原因尚未知。后端close ACK无单独日志。

另外三卡尚待下载，不报告四卡均分。归档未操作UI、服务、性能回放或Git index。
