# Phase GPU 完整评测：alpha 输出

归档 `gosim_phase_gpu_alpha_result.zip` 的7个规范输出，仅CRLF→LF。下载SHA-256：`dff9ca97624628059f11e646cd7912c5b0e6ee68eeb8a40df201b7e92532aaec`。官方三个输出SHA、内嵌评分一致性及实际runtime token匹配0均通过；细节见 `download_manifest.json`。

实际上传包a6fca473… / 平台指纹7f00671b…由父任务确认，对应 `results/model_gpu_phase_submission_20261003.json`；输出ZIP本身没有源码指纹。

| 项目 | 官方报告 / 日志 |
|---|---:|
| 得分 | 7289.494481 |
| 基础科学分 | 7239.830435 |
| required缺失 | 3 |
| REQ完成 / 发布 | 1 / 2 |
| 数据失效观测 | 0 |
| accounted wallclock | 596.021秒 / 900秒 |
| 完成状态 | survey_complete |
| health | TimeoutError，12.02秒 |
| GPU规划调用 | 0 |
| CPU Phase调用 | 1184 |

该卡启动health失败后使用CPU Phase回退，不能称为GPU搜索成绩。相对早先CD2同卡7094.664204高194.830277分；程序及轨迹不同，不构成GPU增益证明。

归档未操作UI、服务、性能调用、上传源码或Git index；未保存或输出凭据。
