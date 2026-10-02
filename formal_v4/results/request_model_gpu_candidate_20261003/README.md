# 请求规划 + 兼容API GPU 候选包

状态：已完成离线包门检，尚未上传、部署或验证网络整卡。

- 文件：`/Users/kamico/Downloads/observer_request_phase_gpu.zip`，67,312字节、26文件。
- ZIP SHA-256：`bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec`。
- 官方 `project_digest` 指纹：`75fa4058539fbe28fafd0e56d4fab0cc8af0108d7cbb6ec87ee1f268a126c0d5`。
- 入口：`research.agent_request_distributed`，全传递依赖在明确白名单。
- 使用 `results/gpu_request_future_pair_20261003/agents/deadline/policy_config.json` 原字节，SHA-256 `590da7144349854de6a5d19a233e1d68bd14ff638a41d851e31921d064ea2890`。
- runtime为health60 / initialize75 / choose10秒，无端点或凭据。

## 离线门检

缺少OPENAI环境变量时，解包入口在socket联网被显式禁止的进程中完成initialize、一次choose、summary和finish，返回CPU Phase observe；没有远端session需要清理。build_manifest逐文件SHA、actualtoken0、hidden/server0通过；算法源码与前次候选完全相同，因此前次全部imports及Facade close stub门检仍适用。

默认 `model-gpu` 重打包的所有文件内容和可执行标志仍与原a6fc上传包一致；2409与a6fc两个已上传ZIP均未改。主Policy、entry、transport源码未改。仅打包器新增model入口专用 `--model-health-timeout-seconds`，默认12；非model入口使用该参数会被拒绝。

## 60秒的依据与证据边界

官方页面每15秒发现新run topic，旧12秒health比单个发现周期短；60秒允许数个刷新周期。额外等待消耗真实900秒预算。该风险由源码确认，但尚无匹配浏览器/网关轨迹证明本轮四卡超时原因。不是prepared快照绑定了旧页面relay A；重新连接的正常页面可订阅本队active run。

旧health12候选ZIP为 `9189060a…`，指纹 `074ab795…`；其源码与逐项哈希已保留在Git及 `results/request_model_gpu_package_gates_20261003.json`。新包只改变remote_runtime与build_manifest两项。

新门检：`results/request_model_gpu_health60_package_gates_20261003.json`；relay审计：`research/MODEL_RELAY_LIFECYCLE_AUDIT_ZH.md`。下一步由root按授权验证真实distributed网络路径，不能从离线门检宣称网络整卡有效。
