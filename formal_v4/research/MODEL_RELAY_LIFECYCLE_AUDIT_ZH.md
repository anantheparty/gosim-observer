# 官方临时relay生命周期审计

只读核验官方仓库固定commit `e01939d060f304c2a7cf04d9b3e46009b564fc23`。记录及逐源SHA：`results/model_relay_lifecycle_audit_20261003.json`。未读取浏览器secret、live relay topic、改变网页/服务或进行网络性能调用；官方部署版本本身未被本审计确认。

## 没有发现“准备时绑定旧页面relay A”的机制

`usePersonalModel.connect()`只设置本页connected并请求 `model_routes`，没有向平台提交或创建页面relay session ID。准备阶段固定源码、manifest、镜像和模型API capability；每次完整评测另建四个run，并为每run生成新的模型API capability。模型API请求即时执行 `observer_model_route`，topic绑定run_id；当前重新连接的页会订阅本队所有active run topic，并按请求使用本页当前endpoint/model/key。

因此，按所核验官方实现，旧prepared项目不会因曾使用页面A而固定调用A。页面重新连接B可以处理旧项目新评测的run；保留同页可减少断线风险，但不是修复一个源码中的A/B快照。

依据：[页面relay](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/web/src/composables/usePersonalModel.ts)、[每run模型路由](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/supabase/migrations/20260926000200_stored_model_keys.sql#L175)、[评测新run及capability](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/supabase/functions/_shared/observer-orchestrate.ts#L59)、[准备产物](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/project_platform/preparation.py#L59)。

## 源码支持的启动时序风险

ProjectWorkflow每15秒reload，且只有页面可见、未busy时才周期刷新；reload再调用personal.refresh以发现新run topic。connected标志在refresh/订阅确认之前就设为true。所以connected显示不保证所有新run已订阅。

原12秒health小于15秒发现周期。若错过一个refresh，新run的首次health可先超时；页面隐藏或busy时还可能更久。官方网关Broadcast每2秒重发请求、最长等待125秒，但参与程序12秒先放弃后即停用远端，可能永远进入CPU回退。

依据：[15秒且可见/未busy的刷新](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/web/src/components/competition/ProjectWorkflow.vue#L315)、[Broadcast重发](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/supabase/functions/_shared/observer-model-broadcast.ts#L25)。这是时序风险，尚无本轮对应浏览器/网关轨迹，不能确认四卡实际超时原因。owned HTTPS健康/并发门检不包含这一段路径。

## 最小正常修正

保持参与页面挂载且可见；按正常项目刷新请求当前routes；下一候选将启动health设60秒以容纳数个15秒周期，init75/choose10保持。真实启动耗时仍计入900秒预算。以官方remote_check成功、非零GPU规划调用验证连接，再比较完整分数。无需改平台、重新解释prepared产物或改变隔离。

当前四卡均分6532.68247925来自GPUcalls0后的CPU Phase回退；相对旧版本高334.292015不能归因为GPU。
