# REDRUM：用曝光指向画 M

## 实验

题面要求把 REDRUM 中一个字母写到天空。选择 M，因为东西镜像仍是 M，且四段连续折线不需要抬笔。
在公共夜历的首个可用窗口，固定赤经/赤纬中心，17 个点依次走过左下、左上、中下、右上、右下。
每段均匀取样，宽高均为 20°；每点使用仪器公开的最短曝光时长。每次实时转换到地平坐标发送 observe。
完成后只有 wait 至季末，没有其他扫描或行星曝光；空光纤分配沿用已验证的合法指向曝光形式。

包目录：`work/packages/o4s_sophon4_redrum_m/`。
ZIP：`work/packages/o4s_sophon4_redrum_m.zip`，3286 字节。
SHA256：`b5e69aa83ad514001cf491a6fe289d5a7320bc6d08498595f2eab24b8faba6b3`。
包仅用 Python 标准库，没有网络请求或凭证读取。

## 本地结果

| 项目 | 结果 |
|---|---|
| 卡 | 官方 sophon-local |
| 有效曝光 | 17 / 17，每次 60 秒 |
| 观测区间 | 2026-10-02 00:00–00:17 UTC |
| 高度范围 | 53.8855°–74.9995° |
| 独立反算坐标最大偏差 | 0.00004960° |
| 终止 | survey_complete |
| 本地实际耗时 | 约 0.15 秒 |

输出位于 `validation/sophon4_redrum_m/`；`trajectory.png` 是从实际 decisions.csv 反算的天球坐标。
这只验证轨迹与协议正确，不证明私有地面站会识别出字母或发旗。

## 线上排期

**更新：已完成，未触发新旗。** 真卡批次 `5f254665-cbd9-49f5-9abd-df31c78164e8`，
run `dbe89770-5cc8-4def-a22a-860250a5283b`，产物在
`work/online/o4s_sophon4_redrum_m_5f25/`。
线上 17/17 次曝光有效，逐点与本地轨迹一致，之后 `survey_complete`。
地面站于 2026-10-06 20:30:02 UTC 已检查该运行，回执为 `Nothing unusual in the returns.`，
`waiting=[]`。这是已完成检查但未发新旗，不是等待回执。没有提交任何旗标。
原始回复与分析分别见 `redrum_m_5f25_desk_receipts.txt` 和 `redrum_m_5f25_analysis.json`。

`queue_redrum_eval.py` 已启动，等待本会话 envdiag 的授权包装脚本退出后，再调用原有 `sophon_eval.sh`。
目的是避免两个自有任务同时争抢全队空档；没有修改平台脚本或创建新平台客户端。
状态：`validation/redrum_eval_queue.jsonl`；包装脚本日志：`validation/redrum_eval_wrapper.log`。
完成后检查下载产物，并由主线或授权 desk.sh 的 GET `/desk/receipts` 核对新回执。

## 其他支线小试

| 请求 | 理由 | 结果 |
|---|---|---|
| POST /desk/hall，word=GOLDROOM | 同名 GET/POST 解题惯例 | 200，但只重复题面 |
| GET /desk/goldroom | 双胞胎错字直接给出该词 | 404 |
| POST /desk/bar，say=GOLDROOM | 用户提出的已知酒吧入口 | 200，普通噪声 |
| POST /desk/twins，word=GOLDROOM | 排除只存在 POST 的双胞胎解题入口 | 404 |

没有新 flag。没有进一步枚举路由。镜子只向主线提议先用空格分隔原四词，未自行提交。
house 的原书日期定位报告见 `house_line_sources.md`；最新 desk 菜单已显示主线取得 No.9。
