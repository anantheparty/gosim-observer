# 正式计分独立重建与共享曝光利润控制

2026-10-04，Asia/Tokyo。先独立读官方 `v4_runner.py`、`v4_scorer.py`、fiber 几何及公开卡/协议；形成 best-only、共享曝光和跨夜机会假设后才读 portfolio、science trace/model/runtime audits。全部新源码和结果只位于 `results/cold_strategy_rebuild_20261004/`，29 文件强 RequestCache ZIP 原成员保持逐字相同。没有修改生产源、提交或把未来 truth 送入 actor。

## 问题与应纠正的因果说法

官方单目标单次曝光为 `g=min(flux·duration·quality/450,1)`，终局科学分只取有效曝光 `weight·g·program_mult` 最大值。factor 不累计，历史 science best 与 required/REQ 的最大 raw factor 是不同账本。一个 16fiber 曝光具有共同 duration/program/pointing，每个 fiber 只能给一个目标。目标在开始判定 hit，此后固定在相对 fiber 位置，但气团、月光和天气仍积分。无 slew 或固定曝光开销。required 每缺一个−50，请求是窗口内完整单次 witness 的 quota gate，report 与 data loss 必须完整结算。

第一猜想是“gain/duration 天然偏短并惩罚已有 best”。单目标推导纠正了这个说法：在线性正收益段，`u(d)/d=A·k−B/d`，其导数 `B/d²≥0`。已有 best 本身使 rate 倾向更长时长。**不能把 ratio 本身总偏短当作结论。** 多目标共同曝光、有限 field proposal、未来更好的共享时间窗、quality 变化和所选目标互斥才可能造成相对于终局目标的偏差。

当前真实 strong baseline 的 seed priority 为 `science_potential × min(1,k·900)`，science_potential 已含一次 flux 所决定的 reachable factor。低 flux 因而受到第二次短曝光偏好。这个因子可以有 resource 成本理由，却不是已证明的终局 continuation value。它可能把长曝可产生较高加权终分的区域从有限 anchor family 排除。删掉它仍须真实重新规划验证，不能凭本地当前收益宣布成功。

线上 aggregate 证据已由独立 trace 审计证明：δ 覆盖8917/9400、加权覆盖93.45%，covered 加权 best factor .69054；榜首科学差739.44。QSO/LRG 是主要不饱和缺口，但本队实际长曝≥1200秒已经占60.21%时间。program 天花板缺口不到100，最后有效loss科学差约6.86，不能独自解释739。25个四卡 required 缺失全部 QSO，14个在本队已选择历史最大 quality 下3600秒也不到0.5，说明需要更好的机会或目标组合，不证明原题不可行。没有对手逐目标行为证据。

## 新原型的决策对象

保留 RequestCache 的完整 public-feedback ledger、pointing/terrain belief、report、active REQ exact scheduling 及缓存，只替换其 ordinary science baseline。候选仍为合法共同 field/assignments/program/duration，保留原 strong 的实际 field 再按新目标重估其全部 fiber，不将每个 target 独立放到免费未来最优日期。

新 objective 为 `shared_exposure_utility−λ·duration`，包含已有 science best 的真实正部门槛和原 required/REQ/Jain代理项。不同 duration 的共同时间成本明确进入同一比较。λ 不等于当前候选 max(gain/duration)，也不通过 Dinkelbach 重解原局部 quotient。

λ 的 prior 来自当前 public state 出发至多4小时的**单一时间 path**：至多四个3600秒物理曝光，每次真实重新生成 field、fiber 指派、program，按完整公共月光/气团积分和公开 terrain 模型计算条件 score；同一目标的 imagined best 在路径内立即更新，整条路径只能顺序花一次 telescope 时间。天气 C/E 在这条 nominal path 内冻结，是明确的条件模型。price = 该有限 path 的净 science / 实际占用 telescope 秒。随后把当天 actor 真正收到的 science best 增量及曝光时间并入该累计服务率；新夜重新建立 nominal prior。

这是**反馈式 continuation cost heuristic**，不是已经求对的全季 dual 或天气概率模型。它允许 field/assignment/duration 联合改变，但没有声称保住原 science 率或保证 required 不降。science seed 同时去掉额外 `min(1,k·900)`，在原24 anchors×16 placements和 refinement 的物理域寻找不同字段；不加 beam 或小搜索宽度。

`SERVICE_MODE=control` 完全走原 baseline，`debias` 只改变 seed 偏好并保留 gain/duration，`surplus` 使用上述价格与利润目标。源码 `package/surplus_planner.py` / `surplus_entry.py`，原29文件 parity见 `source_lock_v1.json`。

## 第一批真实短续局

预声明用 L1/L2 公共日历的第8夜、该夜第一个历史 observe rank。只将此前真实 strong control 的 **past actions** 给 actor；官方 host 从初始化执行这些动作并重新生成每条当前公开 score/messages，再由当前 actor 拟合 C/E、ledger、terrain 和 pointing。pending prediction 的 alt/az 从公开目录/时刻精算，因原 feedback fit 只使用这些方位和重新计算的公共积分，未读取 observations.csv 的私有 factor/quality/prog_mult。

前缀 planner 被旁路，snapshot wallclock 是本次新预算；这明确是重建 public state，**不是保存过的 historical exact snapshot 或历史墙钟复现**。切点之后 control/candidate 都用官方现场新反馈重新规划到当夜末，不能把 candidate 喂给旧 control 后续结果。actor 不读未来 truth；truth 只由未修改官方 runner host 访问评分。两分支同一 host/source/budget，官方短终局包含相同早期 prefix，晚季尚未做，不把这个短结算当完整卡实分。

L1 cut rank376，stop `2026-11-09T08:15:00Z`；L2 rank252，stop `2026-11-16T08:15:00Z`。六条实际短续局已完成，均 `agent_finished` 到当晚终点，无 traceback。每卡三分支此前 past actions、官方前缀观察记录 SHA 和 actor science sums 完全一致；见 `analysis_summary.json`。

## 五类假设当前判断

| 假设 | 本次可证事实 | 尚未解决 |
|---|---|---|
| best-only 质量门槛 | 原模型公式与账本语义基本正确；已有 best 不使单目标 rate 偏短 | 多目标共同 field 与未来重付成本是否影响终分 |
| 短曝/长曝容量 | 共同 duration 不能按独立 target 无限并行；原长曝时间占比已高 | 利润 objective 是否将有效长曝放到更合适组合 |
| 跨夜质量 | 低 flux 缺失需要更好 realized quality | nominal C/E冻结与日历质量尾部仍只是近似 |
| 反馈自适应 | fit、report、terrain和resync必须保留完整所有者 | 准确天气 RMSE不等于长期调度价值 |
| field/target互斥 | 每 glass cell 一目标，anchor有额外短曝因子 | seed去偏好或共同时间利润是否真正提高科学饱和度 |

短续局结果见下节；surplus 已停止，debias 经 root 授权进入一次 L1/L2 完整受限验证。浅模型目标或首帧候选收益不能替代实际终分。


## 实际短续局结果与取舍

| 卡/分支 | 官方短终局总分 | 对同 public-prefix 强control差 | 科学分差 | required差 | 本夜曝光数 | 首曝秒 |
|---|---:|---:|---:|---:|---:|---:|
| L1 control | 3110.195514 | 0 | 0 | 0 | 58 | 150 |
| L1 surplus | 3033.253085 | −76.942429 | −26.691654 | −50 | 25 | 1210 |
| L1 debias | 3132.251001 | +22.055487 | +21.793800 | 0 | 62 | 327 |
| L2 control | 1633.807533 | 0 | 0 | 0 | 23 | 1872 |
| L2 surplus | 1573.024885 | −60.782648 | −10.201892 | −50 | 13 | 2497 |
| L2 debias | 1627.711940 | −6.095593 | −5.842259 | 0 | 19 | 1872 |

首曝 λ 为 L1 .00677413166678、L2 .00662016909310 science points/telescope second；不是当前最大 ratio 的重命名。L1 与 L2 首曝时长、field/assignment、后续曝光数均真实改变，完整后续 score 来自官方现场新反馈。L1 strong 的本夜实际增量/曝光秒为 .0128200，surplus 为 .0112545；其 nominal long-only prior price 明显低于后来 strong 的短曝吞吐。这个误差是失败线索，不证明调高一个 scalar λ 就会成功。

L1 surplus 本夜多产生18个饱和目标（146对128），QSO+LRG 科学增量比control多22.909797，ELG多15.952238；BGS+Star损失65.553684，净science反而−26.691649（逐CSV舍入）。L2 QSO只多1.167606，LRG少1.363382，BGS+Star少13.204724。两卡还各少完成一个 required。**提高饱和数量、延长曝时、或减少覆盖并不能自动得到榜首式更高science。** 当前候选没有把失去的不同目标、共享field和required机会成本估对。

surplus 两卡都科学下降且丢 required，按预声明停止；不调 λ、不扩 beam、不启动它的完整卡。debias 两卡平均短局总分约+7.979947，required均同。单世界负结果不能自动排除其期望收益；root明确授权一次 L1/L2 完整受限判断，而非要求所有 micro world 同符号或将短均值称稳定提升。

## 纯 debias 完整正常入口

已生成31file `observer_science_seed_debias_20261004.zip`，SHA256 `cb5e8c423d40c85394ac2ab6e50b65005bc26a95cb3a4014b141d2a82884aee1`。

- `debias_entry.py` SHA256 `c945c70b7bb8ccea34001c00221a81f29458642f748dff4c5e1b15b83a25aed6`。
- `debias_planner.py` SHA256 `6641a998abd5153e836e946d4e5a6863aab94cdb2559888e0799c64af11e1329`。

27个原 source/config 成员逐字保持；仅 `observer.project.json` run entry 和 `build_manifest.json` 更新，增加两文件。默认正常 enabled，run为 `python3 -u debias_entry.py`；没有 forcedprefix、cut、STOP、price 或 episode切点。REQ仍由原owner真实重新规划，crop时同步child tmax，完整反馈、terrain/calibration/report/loss不换。最终正常入口把原field/newfield重估限制为 inherited choose 的同一 visible pool，这是恢复原高度约束的机械修正；短原型在这一步使用all-catalog pool，因此完整入口不能声称与全部旧micro动作逐字相同。

`DEBIAS_ENABLED=0` 实际官方L1初始三次完整public请求（除各自wallclock）及responses，均与原29file原入口逐项一致；enabled初始三次也同原动作。该自然初始门检不代替末季、活动REQ、stress或Linux全季验证；真正第8夜改变行为已经由上述短重规划给出。见 `debias_parity_result.json`、`DEBIAS_PACKAGE_RECEIPT.json`。root将用现有同源strong控制6267.103017/6723.359693，对新正常入口各做一次2CPU/2GiB/900秒完整评分。当前尚无该正常入口的完整季节实分。

## 首次 harness 失败（保留）

初版误将 `SERVICE_*` 只放入host环境；官方 `run_local.py` 默认清空caller环境，所以两次所谓control/surplus都实际从初始化运行默认surplus至survey_complete，总分同为6172.484006，不能算 paired 或短局证据。两份完整原输出保存 `failed_env_scrub/`，原因和修复见 `FAILED_ENV_SCRUB.json`。修复仅将participant命令改为显式 `env SERVICE_KEY=value` 参数，不继承整个环境，没有改算法。之后上述六条run的真实mode、cut与stop全部通过actorcapture核对。首次错误耗时274–282秒，未当作候选提升或正式卡分数。
