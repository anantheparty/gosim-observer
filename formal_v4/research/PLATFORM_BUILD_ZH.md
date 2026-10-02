# 云端构建记录

2026-10-03，第一个 CD2 项目成功上传，但准备阶段失败，未使用每日5次评测配额。

## 失败原因

平台日志显示依赖安装时发生：

```text
Defaulting to user installation because normal site-packages is not writeable
ERROR: Could not install packages due to an OSError: [Errno 30] Read-only file system: '/.local'
```

此时程序尚未启动，不能据此判断 GPU 网络不可达或算法接口错误。

## 最小修复与依据

`observer.project.json` 的 build 指定 `pip --target .deps numpy==2.2.6`，environment 指定 `PYTHONPATH=.deps`。源码和决策参数未改变。

[官方 DockerWorkspace](https://github.com/gosimfoundation/hackathon-survey26/blob/main/project_platform/docker_runtime.py#L66)使用项目目录 owner 的 UID/GID，根文件系统只读，但项目绑定到可写 `/workspace`。build/run共用持久项目树。`/tmp`是每次容器运行独立的tmpfs，不适合存放需要保留的构建依赖。

[官方安装集成测试](https://github.com/gosimfoundation/hackathon-survey26/blob/main/tests/test_project_docker.py#L130)采用 `.deps` 和 `PYTHONPATH=.deps`，验证非root只读容器中的依赖安装及运行。

修正包 `observer_cd2_buildfix.zip` 的 SHA256：

```text
9b78bd946e11c364be5c0967b98b97926f79417d3ec2c3d3481943f83a65c82e
```

与首包逐项比较，只有 `observer.project.json` 和它在 `build_manifest.json` 中的哈希变化。修正包已由原生电脑控制选取并上传，平台公开场景测试通过。

## 免费接口检查结果

下载平台准备后的项目，逐项比较，所有原始算法、配置和服务凭据均保持原字节；平台只规范化 `observer.project.json`，固定镜像digest，并把manifest协议字段规范化为 `jsonl-v2`。实际工作流仍为 `participant-agent-protocol-v4`，公开测试正常完成，没有新增适配文件。

平台原始代码指纹：`25100d1f94fc6f8d929dff3052cd45f2d481e41f242a7bfbf55b390d24d4c93b`。

准备后项目ZIP SHA256：`db48d90af13b502e0c01a000936076e32cc4184322df79969484302458dfdb61`。

公开测试为 `v4-public-test`，预算300s，实际记账25.961s，363次请求，303次观测动作，全季完成。测试分314.782434不是云端α–δ成绩，也不是此前L1–L4同一数据集。

该环境 `remote_check` 返回 `gaierror`（0.015s），`remote_calls=0`；无法解析CD2域名，程序自动用CPU完成。目前未证明云端可使用外部GPU，后续线上版本应具备独立CPU求解能力。原始下载输出保存于 `results/cloud_cd2_public_test_20261003/`。

## 首次完整平台评测

通过原生 Chrome 电脑控制完成选择修正ZIP、上传、免费接口检查、确认准备版本及启动评测。没有填备注或设计材料。2026-10-03 JST 06:06启动，四卡均正常结束，综合分 **6198.39046425**，UI显示6198.39，今日剩4次。

| 卡 | 总分 | 基础科学 | 请求 | 报告 | required罚分 | 均匀度罚分 | 秒数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| α | 7094.664204 | 7045.172638 | 100 | 100 | -150 | -.508434 | 230.894 |
| β | 6333.107019 | 6584.004137 | 100 | 100 | -450 | -.897119 | 254.541 |
| γ | 6547.568316 | 6500.031700 | 100 | 100 | -150 | -2.463384 | 317.276 |
| δ | 4818.222318 | 5581.029080 | 100 | 100 | -950 | -12.806762 | 276.141 |

四卡均为CPU实际成绩，`remote_check`分别在.012/.013/.018/.017秒返回DNS `gaierror`，`remote_calls=0`。全部第一次请求失败、第二次成功；δ的required缺失19个是明确的改进空间。γ/δ分别有274/213条观测记录回溯失效，不能把失效行数当作非法动作数。

所有私有结果已通过页面下载并归档于 `results/cloud_cd2_{alpha,beta,gamma,delta}_20261003/`。归档只把CRLF规范为LF，manifest同时保存下载ZIP、原始逐文件和归档逐文件SHA256；官方报告的决策/观测/消息哈希均已匹配。未把私有源码URL放入公开GitHub提交入口。
