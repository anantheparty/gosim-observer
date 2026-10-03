# Observer Request GPU 四卡正式机制评测归档

同一08:38 JST批次，上传ZIP `bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec`，源码指纹 `75fa4058539fbe28fafd0e56d4fab0cc8af0108d7cbb6ec87ee1f268a126c0d5`。来源由root在UI核对；输出本身未含指纹。全部7份输出/卡已归档，官方三个SHA、内嵌评分和实际凭据零命中校验通过。完整来源、每项SHA和预算在 `../cloud_request_gpu_batch_20261003.json`。

## 得分

四卡均分 **6280.45111625**；旧Phase均分6532.68247925，差 **-252.23136300**；更早CD2均分6198.39046425，差82.06065200。四卡GPU规划调用均0：γ/δ摘要直接报告0，α/β启动health失败后源码不保留transport，故不存在后续远端choose路径。不能称为GPU提分。

|卡|总分|对旧Phase差|accounted秒|health秒|缺required|已完成/已发布REQ|终止|
|---|---:|---:|---:|---:|---:|---:|---|
|alpha|5891.789130|-1397.705351|900.000|60.023|5|1/1|global_wallclock_expired|
|beta|6138.150947|-463.998745|900.000|60.079|11|1/1|global_wallclock_expired|
|gamma|6668.777631|-364.302568|826.132|60.047|4|2/2|survey_complete|
|delta|6423.086757|+1217.081212|475.229|60.037|6|1/2|survey_complete|

α/β只发布1个REQ就墙钟到期；1/1不表示完整场景全部请求完成。γ2/2，δ1/2。四卡本轮合计5个奖励，旧Phase4个；平均REQ奖励增加25分，但总分下降。

## 真实预算账本

所有health等待真实消耗900秒总预算，比旧12秒失败各多约48秒。下列timer仅在正常finish输出；α/β被截断，分项未知。actions/messages使用模拟时间，不记录计算墙钟，不能据此补出计时。

|卡|CPU baseline秒|REQ列构建秒|mask DP秒|planning秒|agent减health/planning剩余秒|accounted减agent秒|
|---|---:|---:|---:|---:|---:|---:|
|alpha|未知|未知|未知|未知|未知|11.732|
|beta|未知|未知|未知|未知|未知|14.365|
|gamma|503.455|216.739|1.234|721.469|31.628|12.988|
|delta|300.910|84.263|0.757|385.965|18.405|10.822|

γ：列构建12次、216.739秒，mask DP81次、1.234秒，override2次，crop3次；δ：列构建8次、84.263秒，mask DP116次、0.757秒，override2次，crop4次。列构建是额外请求规划计算；DP状态求解本身只约1秒。crop会在同一状态先做基线再做缩短后的基线，重复计算已经计入CPU baseline，无法从汇总再拆出准确crop秒数。

CPU baseline计时排除REQ pool/DP。planning基本覆盖baseline+pool+DP，其余差γ约0.0415秒、δ约0.0356秒。terrain正反馈学习与全目标质量预测没有独立timer；其成本分别混在policy剩余时间和列构建中，不能把agent剩余全部标成terrain。

α/β agent减health后分别828.245、825.556秒，包含CPU搜索、REQ列构建/DP、terrain、I/O、末次未完成计算等，没有精确分项。γ/δ实际完成，α/β墙钟截断直接解释其未走完整调查；谁贡献了多少额外成本或损失分数，现有日志不能独占归因。旧Phase四卡均完整完成，源码、轨迹、请求决策与CPU耗时也同时改变。

## 源码可证明的计算结构

`RequestDeadlineMixin.choose`每次先计算完整baseline，然后处理请求。`_build_pool`遍历整个请求截止前夜晚/900秒起点、请求anchor、16fiber及两种填充分支，并在校准quality变化时重建。构建前只检查snapshot的remaining是否小于30秒；该snapshot预算未减本次baseline实耗，构建内部没有墙钟早停。故存在单次大构建挤掉剩余预算的机制风险，但没有α/β最后一次计时证据，不能断言本轮唯一原因。

`agent.py`仅收到finish才输出完整摘要。超时被终止并ignored_in_flight=true时没有周期计时checkpoint，因此此归档如实保留unknown，不构造精确账本。

## 对连接问题的结论

本轮health60仍全部TimeoutError；公开free同源码health4.841秒、6次GPU基线成功，owned四并发也成功。这些证据只能确定失败发生在完整平台调用链，不能确认页面订阅、平台gateway或endpoint哪一段。15秒route刷新周期本身不足以解释60秒失败。未改变凭据保存方式，也不将encrypted模式推为已证修复。

本归档没有UI、部署、性能调用、源码修改或Git index操作。保留δ先前已归档manifest原字节。
