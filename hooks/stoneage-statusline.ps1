$flagPath = "$env:USERPROFILE\.claude\.stoneage-active"
if (Test-Path $flagPath) {
    $level = (Get-Content $flagPath -Raw).Trim().ToUpper()
    Write-Output "[STONEAGE:$level]"
} else {
    Write-Output ""
}
