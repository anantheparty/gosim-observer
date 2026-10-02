# Phase GPU 完整评测：δ 输出

本目录归档 `gosim_phase_gpu_delta_result.zip` 的7个输出，仅 CRLF→LF。下载SHA-256为 `4a0855d69339f4eee8b3e32d98489db637476c6590d56184c7d0e14c5fc08576`；官方decisions/messages/observations三个SHA-256全部通过，workflow内嵌评分一致。实际runtime token扫描matches=0，通用凭据模式匹配为0。

父任务确认该完整四卡评测使用 `observer_phase_gpu.zip`（a6fca473…），平台源码指纹7f00671b…；来源对应 `results/model_gpu_phase_submission_20261003.json`。输出ZIP本身没有源码指纹。

## 实际结果

| 项目 | 官方报告 / 日志 |
|---|---:|
| δ得分 | 5206.005545 |
| 基础科学分 | 5965.730600 |
| REQ奖励 / 报告奖励 | 100 / 100 |
| required缺失 / 罚分 | 19 / −950 |
| uniformity罚分 | −9.725055 |
| REQ完成 / 发布 | 1 / 2 |
| 数据失效观测 | 252 |
| 完成状态 | survey_complete |
| accounted wallclock | 365.121秒 / 900秒 |
| 启动health | TimeoutError，12.009秒 |
| GPU规划调用 | 0 |
| CPU Phase调用 | 1000 |

启动health失败后，当前入口立即停用该卡远端。这是CPU Phase回退成绩，不能称为GPU远端搜索收益。早先 `cloud_cd2_delta_20261003` 得分4818.222318，本次高387.783227分；两次程序和轨迹不同，比较不构成GPU增益证明。

## 启动时限分析

单次health错误就使远端停用；“两次失败停用”仅适用于成功health之后的choose。公开测试health为11.133秒，已接近12秒配置；δ本次12.009秒超时。四卡官方网关、临时页面relay的排队或启动调度可能造成延迟，但尚无对应链路日志，不能确认原因。

仅增加health时限可以容纳更慢的启动；不能保证initialize/choose随后成功，也不能改变两次choose失败停用。额外等待仍消耗真实900秒预算。owned HTTPS四并发3.519秒门检没有包含官方代理与页面relay开销。等待另外三卡日志后再决定是否提高health；下一候选仍保留12/75/10，无部署或上传变更。
