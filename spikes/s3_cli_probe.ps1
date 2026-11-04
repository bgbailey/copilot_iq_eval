<#
.SYNOPSIS
    Spike S3 on Windows: can the Agent Evaluations CLI run headless as each persona, and what does
    its JSON report contain? (ADR-003; config/contracts.yaml agent_evaluations_cli)

.DESCRIPTION
    Same probe as s3_cli_probe.sh: writes a two-prompt dataset (REV-001, JNT-001), runs
    `npx -y @microsoft/m365-copilot-eval runevals` once (Microsoft's package on npm; it signs in
    interactively the first time - sign in as the persona) and records the report, output, exit
    code, duration and the files the CLI created under your profile (token cache candidates)
    in spikes/out/s3/<persona>-<time>/.

.EXAMPLE
    $env:TENANT_ID = '<tenant-id>'; $env:AZURE_AI_PROJECT_ENDPOINT = '<project endpoint>'
    ./spikes/s3_cli_probe.ps1 -Persona exec -AgentId <M365_AGENT_ID>
#>
param(
    [string] $Persona = 'exec',
    [string] $AgentId = $env:M365_AGENT_ID
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

foreach ($name in 'TENANT_ID', 'AZURE_AI_PROJECT_ENDPOINT') {
    if (-not [Environment]::GetEnvironmentVariable($name)) { throw "Set the $name environment variable." }
}
if (-not $env:AZURE_AI_MODEL_NAME) { $env:AZURE_AI_MODEL_NAME = 'gpt-5-mini' }
if (-not $AgentId) { throw 'Pass -AgentId or set M365_AGENT_ID (the declarative agent, P4.1).' }
$env:M365_AGENT_ID = $AgentId

$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "spikes/out/s3/$Persona-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
New-Item -ItemType Directory -Force -Path $out | Out-Null

# Dataset schema 1.6.0 (S12). The top-level shape is part of what this spike confirms.
@{
    schemaVersion = '1.6.0'
    items         = @(
        @{ testId = 'REV-001'; category = 'single-model'; prompt = 'What was gross revenue in FY2025?'
            expected_response = 'FY2025 gross revenue from the certified Sales Analytics model.'
            evaluators = @('Citations'); evaluators_mode = 'extend' }
        @{ testId = 'JNT-001'; category = 'joint'; prompt = 'Did we hit our FY2025 gross revenue target?'
            expected_response = 'Actual from Sales Analytics compared with the approved target in FY2025 Revenue Targets - APPROVED.'
            evaluators = @('Citations'); evaluators_mode = 'extend' }
    )
} | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $out 'dataset.json') -Encoding utf8

$since = Get-Date
$timer = [Diagnostics.Stopwatch]::StartNew()
npx -y '@microsoft/m365-copilot-eval' runevals --prompts-file (Join-Path $out 'dataset.json') --output (Join-Path $out 'report.json') `
    1> (Join-Path $out 'stdout.txt') 2> (Join-Path $out 'stderr.txt')
$exitCode = $LASTEXITCODE
$timer.Stop()
Get-ChildItem $HOME -Recurse -Depth 3 -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt $since -and $_.FullName -notmatch 'node_modules|npm-cache' } |
    Select-Object -ExpandProperty FullName | Set-Content (Join-Path $out 'new-files.txt')

Write-Host "S3 ${Persona}: exit $exitCode after $([int]$timer.Elapsed.TotalSeconds) s"
Write-Host "Report: $(Join-Path $out 'report.json')"
Write-Host 'Files the CLI created under your profile (token cache candidates):'
Get-Content (Join-Path $out 'new-files.txt') | ForEach-Object { "  $_" }
Write-Host 'For ADR-003: does report.json hold the answer text, citations (Power BI URLs?) and timestamps?'
