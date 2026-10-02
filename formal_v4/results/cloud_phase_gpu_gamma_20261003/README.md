# Phase GPU 完整评测：gamma 输出

归档 `gosim_phase_gpu_gamma_result.zip` 的7个规范输出，仅CRLF→LF。下载SHA-256：`d3be28ef86ef41f0506eee66f85322d43f01a2d788205bc43994835e9a3482c1`。官方三个输出SHA、内嵌评分一致性及实际runtime token匹配0均通过；细节见 `download_manifest.json`。

实际上传包a6fca473… / 平台指纹7f00671b…由父任务确认，对应 `results/model_gpu_phase_submission_20261003.json`；输出ZIP本身没有源码指纹。

| 项目 | 官方报告 / 日志 |
|---|---:|
| 得分 | 7033.080199 |
| 基础科学分 | 6984.890301 |
| required缺失 | 3 |
| REQ完成 / 发布 | 1 / 2 |
| 数据失效观测 | 313 |
| accounted wallclock | 688.393秒 / 900秒 |
| 完成状态 | survey_complete |
| health | TimeoutError，12.013秒 |
| GPU规划调用 | 0 |
| CPU Phase调用 | 1166 |

该卡启动health失败后使用CPU Phase回退，不能称为GPU搜索成绩。相对早先CD2同卡6547.568316高485.511883分；程序及轨迹不同，不构成GPU增益证明。

归档未操作UI、服务、性能调用、上传源码或Git index；未保存或输出凭据。
