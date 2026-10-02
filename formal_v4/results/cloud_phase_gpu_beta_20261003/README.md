# Phase GPU 完整评测：beta 输出

归档 `gosim_phase_gpu_beta_result.zip` 的7个规范输出，仅CRLF→LF。下载SHA-256：`2b63f5b53b8aafd7a184d29f537fef3e7dbe7cd4ed9753ce9c874844849ee072`。官方三个输出SHA、内嵌评分一致性及实际runtime token匹配0均通过；细节见 `download_manifest.json`。

实际上传包a6fca473… / 平台指纹7f00671b…由父任务确认，对应 `results/model_gpu_phase_submission_20261003.json`；输出ZIP本身没有源码指纹。

| 项目 | 官方报告 / 日志 |
|---|---:|
| 得分 | 6602.149692 |
| 基础科学分 | 6853.011236 |
| required缺失 | 9 |
| REQ完成 / 发布 | 1 / 2 |
| 数据失效观测 | 0 |
| accounted wallclock | 647.299秒 / 900秒 |
| 完成状态 | survey_complete |
| health | TimeoutError，12.013秒 |
| GPU规划调用 | 0 |
| CPU Phase调用 | 1138 |

该卡启动health失败后使用CPU Phase回退，不能称为GPU搜索成绩。相对早先CD2同卡6333.107019高269.042673分；程序及轨迹不同，不构成GPU增益证明。

归档未操作UI、服务、性能调用、上传源码或Git index；未保存或输出凭据。
