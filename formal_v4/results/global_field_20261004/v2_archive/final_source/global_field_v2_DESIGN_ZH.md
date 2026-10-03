# 全域球面搜索 v2：可执行 native 动作与安全空间剪枝

v1已冻结并拒绝，见 `results/global_field_20261004/v1_archive_manifest.json`。
本轮保留同源完整 CPUPhase 控制器、24原锚点、全域256展开预算；不缩小节点数。
参赛推理只读取公开 initialize、已发布消息与已揭示反馈，没有GPU或网络依赖。

## 机械修复与动作族

- 所有固定时长点均clip到当晚seconds_left，包含60/66/3599秒短夜尾测试。
- 科学饱和的floor/ceil；required/Jain/REQ阈值实际最早命中整数秒及前后各一秒；
  up丢失、deadline失效两侧均覆盖。负Jain梯度的向下跳不能省略阈值前一秒。
- focus surrogate在quota可完成时比较base/full，否则才给fractional progress；
  某个eligible目标落下时策略值可能上跳，故包含floor(up)+1。
- rate平局按更大总预测utility选动作，避免best-only ledger的重复短曝光。
- C++返回具体duration、program、每个fiber的目标，不再经过Python72时长截断。
  先四舍五入到7位合法command，再按相同actual center重分类、完整优化与返回。
  Python发送前检查duration、up、target唯一及实际fiber/物理玻璃余量。

只有这样得到的完整可执行动作率才提升incumbent；队列弹出时及子盒建立时再次
比较乐观界。当前的界仍只针对冻结公开预测模型，不能称作真实赛季得分上界。

## 不遗漏目标的根盒前筛

光纤方形field内任意命中目标与中心的球面距离不超过

    R = atan(side * pitch / sqrt(2) * DEG).

因此盒[a_l,a_h]中的目标必须满足target_alt∈[a_l−R,a_h+R]。先按目标alt排序，
每个4°根高度段二分取pool，再进入所有8°az根盒。保留原catalog顺序处理效用平局。

盒中心(a_0,z_0)到盒内任意(a,z)，先走经线再沿目标纬圈，其球面距离至多

    rho = (a_h−a_l)/2 + cos(a_l)*(z_h−z_l)/2, a_l>=0.

三角不等式给出命中目标必须落在盒中心半径R+rho的球冠。预缓存目标水平unit
vector，用dot乘加筛掉球冠外目标，然后才调用较贵的wave区间与16行匹配。
跨az0/360与天顶仍由unit-vector dot处理，rho>=pi时不作球冠排除。

## 独立核验

独立子代理只拥有自己的verify源码与结果，不修改C++。验证不是与同样有限的
旧Python断点族互相比较：随机小场景逐整数duration求解；focus通过独立计数DP
和小例子完整指派穷举；实际目标使用官方geometry和整个曝光最低高度。

- 100随机tmax 60–3600逐秒对照；100全域search返回动作逐条重算。
- 126小例子指派穷举/DP相同；5真实prefix，最长758个完整时长断点。
- 8000官方geometry点、3544缩边命中零遗漏；480独立box bound零违规。
- 1988实际目标曝光整段高度检查零违规。
- 定例：负Jain阈值500前499秒最优；plateau选150秒；focus up100→101时最优101；
  epsilon阈值100秒；az rounding360→0；三种program各有独立胜例；非法command、
  actual altitude与up<60均拒绝。
- L2 rank87旧native误用非法300秒产生0.19078182；v2同中心精确恢复合法率
  0.0329775341，全域返回另一63秒合法动作。该fixture只用于离线验证。

验证器 `global_field_v2_verify.py`，结果 `results/global_field_20261004/v2_verify_actions.json`。

## 成本与锁源实验

Mac第一帧L1 native0.0625秒，L2 native0.1304秒。L1根pool由原全扫描3198240
缩至377910（筛掉88.2%），目标全域和256预算相同；不能把局部率当季节收益。
受限Linux真实公共协议第一帧native0.1281秒，整体0.693秒，返回合法103秒动作。

L1完整配对PID554406，容器 `global-field-v2-control-l1`（cores0–1）与
`global-field-v2-search-l1`（cores2–3），各2CPU/2GiB/900秒，无网络，participant
和NumPy依赖只读挂载；truth只由官方宿主runner评分。
开始2026-10-03 16:45:00.744 UTC / 10-04 01:45:00.744 JST。

CPP SHA `dafa96942e68fc8377bee84fc54ae88c2a2ff8d16beef7e6ac1055b3516c5aa5`；
source lock SHA `7f29415256f2c461284236e1d429d7e6c21380b4a2423852fa5477b3656b3c54`。
文件与账本独立放在 `results/global_field_20261004/v2/`。

## 完整 L1 结果：拒绝

控制和搜索均完成官方完整赛季，零 invalidated observation、无 Traceback。
搜索结束账本mtime为2026-10-03 16:55:17.871 UTC / 10-04 01:55:17.871 JST。

| 方案 | 总分 | 科学分 | REQ | required_missing | accounted秒 |
|---|---:|---:|---:|---:|---:|
| 同源CPUPhase | 6289.992617 | 6190.187868 | 1/2 | 2 | 530.093 |
| 全域v2 | 6246.329317 | 6146.727930 | 1/2 | 2 | 588.452 |
| READY native | 6362.021539 | 6162.333410 | 2/2 | 2 | 438.485 |

全域v2比控制低43.663300（science−43.459938、Jain−0.203362），比READY native
低115.692222。READY是同镜像、同依赖、相同2CPU/2GiB/900秒的已有正式完整账本；
本轮control的actions.jsonl与其Phase control逐byte相同。旧READY gate中historical
expected score的flag为false，本比较明确采用它实际输出的完整官方分数。

997次全域搜索实际改变255次动作，native计算共56.319秒；同256预算下，相比
v1截断时915次搜索累计402.607秒，成本问题已解决。根pool剔除87.7896%，
所有997个observe均valid，13552个assignments产生13551hit；控制亦只丢1hit。

首个同历史分叉发生2026-11-02 00:36:50Z，前两动作相同。控制中心
(64.8789237,93.840085)，全域返回(65.0054199,94.9954163)，都是64秒DARK、15hit。
真实CSV best增量由1.875132升至1.938168。该合法新动作局部收益不能解释为赛季
提分，完整season结果相反。

按预声明，L1未提分，停止L2和额外调参。v2也拒绝用于生产，现有ZIP不变。
完整组件、请求缺失、源锁、首个动作分叉及账本见`v2/full_result_summary.json`。
