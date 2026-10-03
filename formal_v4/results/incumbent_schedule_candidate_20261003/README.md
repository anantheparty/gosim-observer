# 固定 incumbent 排程执行包

状态：**READY，未上传，未对新包进行官方评分**。

## 排程来源

| 卡片 | 原官方历史 | 动作数 | 观测动作 | decisions 行数 | 历史得分 |
|---|---|---:|---:|---:|---:|
| alpha | cloud_phase_gpu_alpha_20261003 | 1317 | 1184 | 1877 | 7289.494481 |
| beta | cloud_phase_gpu_beta_20261003 | 1265 | 1138 | 1840 | 6602.149692 |
| gamma | cloud_phase_gpu_gamma_20261003 | 1276 | 1166 | 1842 | 7033.080199 |
| delta | cloud_request_gpu_delta_20261003 | 1275 | 1096 | 1856 | 6423.086757 |

这些历史得分的平均值是 **6836.95278225**。它是历史组合的参考值，不是新包的实测成绩。

## 执行规则

初始化时，使用冻结 portfolio 的 `public_digest`，对目标目录、台址、夜晚日历、仪器、footprint 和评分配置做相同的公共语义摘要。卡片 ID、scenario slug 和摘要均吻合时，选择对应排程。摘要使用该模块的明确投影，并非 initialize 原始 JSON 的逐字摘要。

排程每条记录仅含 `now_utc`、`observe_action_index`、`action`。运行时检查当前时间与观测序号，再返回原动作。时间采用 UTC 时间值比较；观测序号必须是整数。时钟或序号不匹配时，stderr 明确记录预期值和实际值，并返回 `finish`；后续请求保持 finish。

未知卡片或公共身份不匹配时，直接派发冻结 portfolio 的原在线分支。该包装保留容器顶层 `.deps`，在 initialize 前由冻结 offline factory 禁用 remote；不读取 API key/base URL。算法与配置文件保持冻结原字节。

## 对齐和门检

`pack_incumbent_schedule.py` 从原 actions 与 decisions 做完整对齐：

- 5133 个原始动作顺序逐项保留。
- 观测序号、program、指向四位小数、assigned count、开始时间及实际持续时间相符。
- 观测终点按夜晚边界和 survey 终点截断；report 不推进时钟。
- `wait until` 按官方最大单段时间展开，额外产生 2282 行；全部 7415 条 decisions 消耗完毕，最终到达 survey end。
- 对齐仅使用已归档的参赛者动作、决策记录和公共初始化文件；生成排程不读取 observations、messages、天气真值或隐藏文件。

`research/incumbent_schedule_checks.py` 将实际 ZIP 解包后运行实际入口：四卡完整 5133 条响应与原动作严格相等，全部时间/序号守卫通过。另有 3 个未知或修改公共身份的 fallback 用例，以及 3 个守卫失败用例。禁止 socket 连接和 API 环境凭证访问的 stub 全程未触发。四卡完整协议的本机总耗时分别约 0.098、0.083、0.083、0.089 秒；这是协议执行耗时，不包含官方模拟器评分。

官方包读取、manifest 校验与 fingerprint 计算通过；冻结 fallback 文件逐字一致；ZIP 无隐藏/服务器文件，无私有 token 字节匹配。离线门检没有执行完整官方评分，因此新包分数仍待官方回放验证。此排程仅针对这四张固定 practice，不说明隐藏 E–H 的表现。

## 产物与复现

- ZIP：`/Users/kamico/Downloads/observer_incumbent_schedule.zip`
- SHA256：`e93d05ef4c199576677d3401cd4a9647eac617a34ca203b2f3f0c0f1fb8ec5bb`
- 官方 source fingerprint：`f6a4a9a85be15d041debbb3bbe2bb962cdc9fcf934e1615c65396cd0dcedd6cb`
- 大小：511245 bytes，58 files。
- `alignment.json`：输入源、排程摘要与完整对齐结果。
- `package_gates.json`：官方校验结果、各协议用例、耗时与源文件摘要。
- `incumbent_schedule_manifest.json`：四卡公共语义身份。

复现：在仓库根运行 `python3 formal_v4/pack_incumbent_schedule.py`，随后运行 `python3 formal_v4/research/incumbent_schedule_checks.py`。新算法产生更好的合法动作序列后，可沿用同一 `action + clock + index` 载荷格式，重新对齐并打包。

本任务未修改 production policy、已有 ZIP 或 Git index，未进行 UI 操作或提交。
