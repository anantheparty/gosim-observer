# Phase GPU 版本：官方完整四卡归档

上传包SHA-256 `a6fca473886bc1ea5d763f6a358eb5006163b072b807abc8946d141ccfcfee42`；平台源码指纹 `7f00671b877ee119c466e2dc234192d4ab580bbc6f4a1a18cc8379218d67fcda`（父任务确认当次评测版本，并匹配本地部署来源记录；输出ZIP本身没有该字段）。四卡原始输出与规范化哈希见各卡 `download_manifest.json`；汇总见 `results/cloud_phase_gpu_batch_20261003.json`。

| 卡 | 得分 | accounted秒 / 900 | 启动health超时秒 | GPU规划调用 |
|---|---:|---:|---:|---:|
| alpha | 7289.494481 | 596.021 | 12.020 | 0 |
| beta | 6602.149692 | 647.299 | 12.013 | 0 |
| gamma | 7033.080199 | 688.393 | 12.013 | 0 |
| delta | 5206.005545 | 365.121 | 12.009 | 0 |
| 均分 | 6532.68247925 | | | 0 |

四卡均survey_complete、启动health在12秒超时、随后使用CPU Phase回退，实际GPU规划调用合计0。均分较早先CD2版本6198.39046425增加334.29201500；程序及轨迹不同，此差值不是GPU收益证据。每卡REQ完成1/发布2；required缺失分别3/9/3/19。

四卡官方decisions/messages/observations哈希全通过，workflow内嵌评分与独立评分报告一致，实际runtime token字节匹配均为0。仅CRLF→LF，无其它输出改写。归档未操作网页、服务、性能回放、上传源码或Git index。
