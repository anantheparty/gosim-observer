# 请求规划候选完整评测：alpha

下载SHA-256 `cab58e9e89d0b740537c2e855b46279e0092c737f9d8a3158cdb8034234c37aa`。7份输出仅CRLF→LF；官方三个输出SHA、内嵌评分一致性通过，实际token与通用凭据模式均0命中。来源由root UI确认是08:38 JST同一bfcc/75fa四卡批次；输出本身未含源码指纹。

总分 **5891.789130**，科学分5942.269118、REQ 100、报告100、required -250、uniformity -0.479988。required缺失5，REQ完成1/1（只计本次终止前已发布的请求），无效观测0。

health TimeoutError 60.023秒，GPU规划0。global_wallclock_expired，accounted 900.000/900秒，agent wall 888.268秒，ignored_in_flight=True。

未正常执行finish，agent.log没有CPU baseline、terrain或REQ DP计时/次数。actions和messages也没有墙钟计时，不能还原各项开销。

相比旧Phase总分差-1397.705351；程序、轨迹与计时范围均有变化，不能归为GPU或REQ DP单项因果效果。准确分项、预算账本及未知项见download_manifest.json和四卡batch记录。未进行UI、服务、性能调用或Git index操作。
