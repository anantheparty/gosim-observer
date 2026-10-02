# Phase GPU 版本的免费公开测试

本目录保存 `gosim_phase_gpu_public_test.zip` 的7个规范输出，仅将 CRLF 替换为 LF；其它字节不变。原始及规范化SHA-256、校验与来源位于 `download_manifest.json`。

## 版本与范围

- 实际上传包：`observer_phase_gpu.zip`，SHA-256 `a6fca473886bc1ea5d763f6a358eb5006163b072b807abc8946d141ccfcfee42`。
- 平台源码指纹：`7f00671b877ee119c466e2dc234192d4ab580bbc6f4a1a18cc8379218d67fcda`。
- 下载ZIP SHA-256：`4ae17b4f2d97617a3c463a63c0b3f9c3b7164e8e190a5d02d12476c432e3c5ab`。
- 指纹由父任务只读核对当次UI，并与 `results/model_gpu_phase_submission_20261003.json` 中官方 `project_digest` 本地结果一致；另核对上传包全部文件字节与可执行标志。下载输出本身未提供指纹，未从输出推造。

这是官方免费 `v4-public-test`，时限300秒，未消耗正式四卡额度。正式四卡时限900秒；本结果不代表正式四卡成绩。

## 实测结果

| 项目 | 官方报告 / 日志 |
|---|---:|
| 总分 | 236.561912 |
| 基础科学分 | 1124.283776 |
| required罚分 | −850.000000 |
| uniformity罚分 | −37.721864 |
| 结束状态 | survey_complete |
| accounted wallclock | 145.672秒 / 300秒 |
| agent wallclock | 144.729秒 |
| health | ok，11.133秒 |
| 远端规划 | 5次成功，合计42.117秒；另1次TimeoutError后使用本地回退 |
| 初始化实耗 | 14.812秒 |
| 重复决策p90 | 5.789秒 |
| 总远端尝试实耗 | 52.122秒，包含超时尝试 |
| 兼容API chat | 8次，合计53.235633秒 |
| REQ发布数 | 0 |

预算已将一次初始化耗时与重复决策预测分开；超时实耗仍计入总成本。成功5次与接受6次的差额对应日志中一次TimeoutError。

对照已归档 CPU Phase 免费公开测试248.067256分，本次低11.505344分；基础科学分低10.978111，uniformity罚分增加0.527232。此结果不支持分数增益。公开测试没有REQ，不能验证请求规划收益；不同观测轨迹与300秒公开场景也不能替代正式四卡评测。

## 校验与归档

官方decisions、messages、observations三个SHA-256均与规范化文件一致；workflow内嵌score report与单独报告完全一致。7个原始及规范化文件经实际runtime token字节匹配扫描，matches=0；通用凭据模式匹配也为0。

归档未操作UI、部署、性能调用、上传源码或Git index；未保存或打印token。
