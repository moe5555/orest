<#
.SYNOPSIS
    Embeds new rehearsal recordings into a WISE project without supervision.

.DESCRIPTION
    Runs `apollon-search extract` (src/smartsearch/wise_cli.py, extract_folder)
    and keeps Windows from sleeping until it exits. Extraction saves each
    finished recording as it completes (WISE patch 0007,
    knowledge/source_of_truth/versions.md), so a run that fails is started
    again and continues where it stopped, up to -Retries times.

    The display may still turn off; only idle sleep is suppressed, and only
    while this script runs. Each WISE command logs to data/logs/.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File src\scripts\extract_unattended.ps1
#>
param(
    [string]$Project = "hitl_database",
    [string]$Media = "$env:USERPROFILE\Desktop\HITL_Database",
    [int]$Retries = 2
)

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$wiseEnv = if ($env:APOLLON_WISE_ENV) { $env:APOLLON_WISE_ENV } else { "wise" }
$installed = Join-Path $env:USERPROFILE "miniconda3\envs\$wiseEnv\Lib\site-packages\wise\_main\extract_features.py"

# Without patch 0007, add-media registers every listed file again and runs all
# extractors in one pass, which fails on mixed frame- and segment-level models.
if (-not (Select-String -Path $installed -Pattern "get_registered_media" -Quiet)) {
    Write-Error ("WISE patch 0007 is not installed in the '$wiseEnv' environment. " +
                 "Run 'pip install --no-deps --force-reinstall .' in external\wise first.")
    exit 1
}

Add-Type -Namespace Apollon -Name Power -MemberDefinition @'
[DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
$ES_CONTINUOUS = [uint32]"0x80000000"
$ES_SYSTEM_REQUIRED = [uint32]"0x00000001"
[void][Apollon.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)

Set-Location $repo
$code = 1
try {
    for ($attempt = 1; $attempt -le $Retries + 1; $attempt++) {
        Write-Host "$(Get-Date -Format s)  attempt $attempt  extract --project $Project --media $Media"
        uv run apollon-search extract --project $Project --media $Media
        $code = $LASTEXITCODE
        Write-Host "$(Get-Date -Format s)  exit code $code"
        if ($code -eq 0) { break }
    }
}
finally {
    [void][Apollon.Power]::SetThreadExecutionState($ES_CONTINUOUS)
}
exit $code
