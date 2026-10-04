$ErrorActionPreference = 'Stop'
$taskRoot = 'C:/Users/hedge/gosim-physics-quotient-20261004'
$pythonRuntime = 'C:/Users/hedge/gosim-structured-nn-20261004/Scripts/python.exe'
$fitOutput = "$taskRoot/fit"
if ((Test-Path $fitOutput) -and (Get-ChildItem $fitOutput | Select-Object -First 1)) { throw 'Refuse overwrite existing fit outputs' }
New-Item -ItemType Directory -Force -Path $fitOutput | Out-Null
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:CUBLAS_WORKSPACE_CONFIG = ':4096:8'
$child = Start-Process -FilePath $pythonRuntime -ArgumentList @("$taskRoot/source/stage2b/fit_driver.py", '--data', "$taskRoot/data", '--output', $fitOutput) -PassThru -RedirectStandardOutput "$fitOutput/fit_stdout.log" -RedirectStandardError "$fitOutput/fit_stderr.log"
@{ launcher_pid = $PID; cuda_child_pid = $child.Id; python_runtime = $pythonRuntime; task_root = $taskRoot; started_utc = [DateTime]::UtcNow.ToString('o'); no_foreign_process_killed = $true } | ConvertTo-Json | Set-Content "$fitOutput/POWERSHELL_LAUNCH_RECEIPT.json"
while (-not $child.HasExited) {
    $stamp = [DateTime]::UtcNow.ToString('o')
    $gpu = & 'C:/Windows/System32/nvidia-smi.exe' --query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu,power.draw,power.limit --format=csv,noheader,nounits
    $processes = & 'C:/Windows/System32/nvidia-smi.exe' --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits
    @{ utc = $stamp; cuda_child_pid = $child.Id; gpu = $gpu; compute_processes = $processes } | ConvertTo-Json -Compress | Add-Content "$fitOutput/GPU_TELEMETRY.jsonl"
    Start-Sleep -Seconds 2
    $child.Refresh()
}
$child.WaitForExit()
@{ launcher_pid = $PID; cuda_child_pid = $child.Id; exit_code = $child.ExitCode; finished_utc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content "$fitOutput/POWERSHELL_EXIT_RECEIPT.json"
exit $child.ExitCode
