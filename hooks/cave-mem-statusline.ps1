$flagPath = "$env:USERPROFILE\.claude\.cave-mem-active"
if (Test-Path $flagPath) {
    $level = (Get-Content $flagPath -Raw).Trim().ToUpper()
    Write-Output "[CAVE-MEM:$level]"
} else {
    Write-Output ""
}
