# 请求规划候选完整评测：gamma

下载SHA-256 `774ceb67cbb276487dc906e80e9920463334aecc8186ebe2f84d836c26a4a57d`。7份输出仅CRLF→LF；官方三个输出SHA、内嵌评分一致性通过，实际token与通用凭据模式均0命中。来源由root UI确认是08:38 JST同一bfcc/75fa四卡批次；输出本身未含源码指纹。

总分 **6668.777631**，科学分6569.393638、REQ 200、报告100、required -200、uniformity -0.616007。required缺失4，REQ完成2/2（只计本次终止前已发布的请求），无效观测309。

health TimeoutError 60.047秒，GPU规划0。survey_complete，accounted 826.132/900秒，agent wall 813.144秒，ignored_in_flight=False。

CPU baseline 503.454531秒；REQ pool build 216.738870秒、mask DP solve 1.234067秒；planning 721.469秒。build 12次、solve 81次、request override 2次。

相比旧Phase总分差-364.302568；程序、轨迹与计时范围均有变化，不能归为GPU或REQ DP单项因果效果。准确分项、预算账本及未知项见download_manifest.json和四卡batch记录。未进行UI、服务、性能调用或Git index操作。
