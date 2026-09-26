# RTX PRO 6000 的旧 250 W 限制

2026-09-26，公开实例 K20 全扫结束后，Windows 驱动显示 RTX PRO 6000 Blackwell Workstation Edition 的默认/最高功率上限均为 **600 W**，但当前/请求上限为 **250 W**，并报告 `SW Power Cap: Active`；无热降速、无硬件供电刹车。显存仅用约 4.6/97.9 GB，不是显存限制。直接执行 `nvidia-smi.exe -pl 600` 虽成功，随后又被改回 250 W；Windows 从 9 月 18 日起未重启。

只读审计找到两个启用的 Windows 计划任务：

| 任务 | 原动作 | 触发 |
| --- | --- | --- |
| `NvidiaGpuPowerLimit250W` | `nvidia-smi.exe -pl 250` | 开机、登录及每 5 分钟重复；最近执行成功 |
| `ElevatiaGpuPowerLimit250` | `windows_set_gpu_power_limit.ps1 -TargetWatts 250 -Retries 24 -SleepSeconds 5` | 开机、登录 |

用户解释：250 W 是更换电源前设的旧保护，现在允许关闭。两任务均以 `SYSTEM`、最高权限运行。按此授权，执行 [可复查的 PowerShell 脚本](set_gpu_power_default_after_k20.ps1)，先把原任务 XML 备份到 `C:\Users\hedge\gpu-power-task-backup-20260926-155056`，再**禁用**两个任务而不删除定义，最后将 GPU 软件上限设为默认 600 W。命令返回成功；紧随其后的独立查询显示两任务 `Disabled`、当前/默认/最高功率上限均为 `600.00 W`。

另有 `C:\ProgramData\ElevatiaGpu\windows_gpu_power_guard.ps1` 含 250 W 默认值，但审计时没有发现它作为进程、计划任务或服务运行，因此未修改。若将来上限再次回到 250 W，应先查是否有其他管理程序启动了该脚本。需要回退旧保护时可重新启用两个任务；备份 XML 保留了完整原始配置。

复核：在原定的 15:55 定时触发点之后，周期任务的上次运行时间仍为 15:50:01；两任务保持 `Disabled`，GPU 上限仍为 `600.00 W`。
