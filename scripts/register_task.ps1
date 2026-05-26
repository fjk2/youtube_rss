param(
    [string]$ProjectDir = "D:\projects\youtube_rss",
    [int]$IntervalMinutes = 180,
    [string]$Python = "python",
    [string]$ApiKey = "",
    [string]$TaskName = "youtube_rss"
)

$ErrorActionPreference = "Stop"

if ($ApiKey) {
    [Environment]::SetEnvironmentVariable("YOUTUBE_API_KEY", $ApiKey, "User")
}

$scriptPath = Join-Path $ProjectDir "youtube_rss.py"
$queryFile = Join-Path $ProjectDir "youtube_query.txt"
$outputFile = Join-Path $ProjectDir "public\rss.xml"
$jsonFile = Join-Path $ProjectDir "public\results.json"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Script not found: $scriptPath"
}
if (-not (Test-Path -LiteralPath $queryFile)) {
    throw "Query file not found: $queryFile"
}

$arguments = @(
    "`"$scriptPath`"",
    "--query-file", "`"$queryFile`"",
    "--output", "`"$outputFile`"",
    "--json-output", "`"$jsonFile`""
) -join " "

$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel LeastPrivilege

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Description "Generate YouTube search RSS feed." `
    -Force | Out-Null

Write-Host "Registered task '$TaskName'."
Write-Host "Output: $outputFile"
