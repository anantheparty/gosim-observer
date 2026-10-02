# 完整四卡任务启动生命周期

只读官方源码commit `e01939d060f304c2a7cf04d9b3e46009b564fc23`，加已有公开/完整测试归档；没有访问UI、hidden request、live session/key、创建连接或改服务。逐源SHA与依据：`results/model_full_run_lifecycle_audit_20261003.json`。

## “engine claimed claimed”是什么

页面把一条diagnostics记录渲染为 `kind · status · code`。当没有错误/diagnostic code时，数据库把code填为job status。因此engine任务已被runner领取、尚无结果时，正常显示 `engine · claimed · claimed`，不是两次领取事件。[页面渲染](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/web/src/components/competition/ProjectWorkflow.vue#L511)、[code默认值](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/supabase/migrations/20260925001100_private_project_diagnostics.sql#L15)。同一GitHub run/attempt的claim确实幂等，但这三个词本身没有表明claim被调用两次。

## 从点击到900秒计时的顺序

1. evaluate在数据库一次创建batch和全部四个queued run。
2. schedule为每卡打开session并排队一个colocated engine job。session此时无deadline；batch可已显示running，而run处于starting。
3. GitHub runner领取任务；随后下载、校验、解包场景和冻结程序，pull镜像，build安装NumPy，启动受限forwarder。
4. 程序在JSONL transport首次send时启动。engine发送initialize publication，登记ready，再begin固定服务端900秒deadline。
5. 本地workflow启动900秒钟、发送第一次decision；子程序自己的health、GPU初始化和选择仍按真实时耗计入这个阶段。
6. 全季结束、finish grace、runtime.close后，engine才将build log及agent stderr写入结果包的agent.log。

步骤3的镜像pull默认上限300秒、build默认上限600秒，发生在比赛900秒计时之前。claimed后的几分钟不能直接解读成health60正在阻塞。[engine启动和日志写入](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/project_platform/job_runner.py#L151)、[build/pull](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/project_platform/docker_runtime.py#L90)、[ready/begin](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/project_platform/trusted_engine.py#L124)、[计时开始](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_workflow.py#L243)。

initialize只是写入JSONL输入；协议不等待参与程序的initialize ACK。子程序可仍在Policy构造中的health等待，而engine已经begin，额外health60并没有获得免费的60秒。[transport发送](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/project_platform/transport.py#L151)。

## 所有queued run是否进入relay发现范围

是：四个run在evaluate事务中已经创建；model_routes包含本队queued/starting/ready/running run，不必等待engine领取或比赛begin。正常页面15秒刷新就能请求这些topic；connect只代表本页开始刷新，不能证明四个topic都已SUBSCRIBED。[四run插入](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/supabase/migrations/20260927000200_project_eval_ux.sql#L99)、[queued routes](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/supabase/migrations/20260926000200_stored_model_keys.sql#L197)。

以前的A/B页面连接不会被prepared源码快照绑定；详见 `MODEL_RELAY_LIFECYCLE_AUDIT_ZH.md`。健康超时变为60只是容纳若干发现周期的正常保护，不保证网络正常。

## 当前能判断到哪里

本次公开测试health4.841秒、GPU baseline6次成功、0失败，证实一个公开run的实际正常通路。当前完整四卡仅有claimed diagnostics，agent.log未实时上传，所以尚不能证明四卡已经health成功，也不能证明正在失败。须等完成输出的remote_check、remote_baselines/failures及真实时耗。没有证据支持据此修改程序或服务。
