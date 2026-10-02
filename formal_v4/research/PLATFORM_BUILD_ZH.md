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

与首包逐项比较，只有 `observer.project.json` 和它在 `build_manifest.json` 中的哈希变化。修正包已由原生电脑控制选取并上传；云端构建结果待确认。
