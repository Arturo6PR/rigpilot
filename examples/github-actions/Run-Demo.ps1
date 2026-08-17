param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$exampleRoot = $PSScriptRoot
$tempRoot = (New-Item -ItemType Directory -Path ([IO.Path]::GetTempPath()) -Name (
    "rigpilot-demo-" + [guid]::NewGuid().ToString("N")
)).FullName

function Invoke-RigPilot {
    param([string[]]$Arguments)

    $stderrPath = Join-Path $tempRoot ("stderr-" + [guid]::NewGuid().ToString("N") + ".txt")
    $stdout = @(& $Python -m rigpilot @Arguments 2> $stderrPath)
    $processExitCode = $LASTEXITCODE
    $stderr = [IO.File]::ReadAllText($stderrPath, [Text.Encoding]::UTF8)
    $result = [pscustomobject]@{
        ExitCode = $processExitCode
        Stdout = $stdout
        Stderr = $stderr
    }
    Remove-Item -LiteralPath $stderrPath -Force
    return $result
}

try {
    $snapshot = Join-Path $exampleRoot "current.json"
    $failingSnapshot = Join-Path $exampleRoot "failing-current.json"
    $policy = Join-Path $exampleRoot "rigpilot-policy.json"
    $expected = Join-Path $exampleRoot "expected-report.json"
    $passOnePath = Join-Path $tempRoot "pass-one.json"
    $passTwoPath = Join-Path $tempRoot "pass-two.json"
    $failurePath = Join-Path $tempRoot "failure.json"

    $version = Invoke-RigPilot -Arguments @("--version")
    if ($version.ExitCode -ne 0 -or $version.Stderr -ne "") {
        throw "version command failed"
    }

    $passOne = Invoke-RigPilot -Arguments @(
        "assess", $snapshot, "--policy-file", $policy,
        "--format", "json", "--output", $passOnePath
    )
    $passTwo = Invoke-RigPilot -Arguments @(
        "assess", $snapshot, "--policy-file", $policy,
        "--format", "json", "--output", $passTwoPath
    )
    if ($passOne.ExitCode -ne 0 -or $passTwo.ExitCode -ne 0) {
        throw "passing policy did not return zero"
    }
    if ($passOne.Stdout.Count -ne 0 -or $passTwo.Stdout.Count -ne 0) {
        throw "output-file mode wrote to stdout"
    }
    if ($passOne.Stderr -ne "" -or $passTwo.Stderr -ne "") {
        throw "passing policy wrote to stderr"
    }

    $passOneText = Get-Content -Raw -Encoding UTF8 $passOnePath
    $passTwoText = Get-Content -Raw -Encoding UTF8 $passTwoPath
    if ($passOneText -cne $passTwoText) {
        throw "JSON report was not deterministic"
    }
    $passPayload = $passOneText | ConvertFrom-Json
    $expectedPayload = Get-Content -Raw -Encoding UTF8 $expected | ConvertFrom-Json
    $passCanonical = $passPayload | ConvertTo-Json -Depth 100 -Compress
    $expectedCanonical = $expectedPayload | ConvertTo-Json -Depth 100 -Compress
    if ($passCanonical -cne $expectedCanonical) {
        throw "passing report did not match the checked-in expected report"
    }

    $failure = Invoke-RigPilot -Arguments @(
        "assess", $failingSnapshot, "--policy-file", $policy,
        "--format", "json", "--output", $failurePath
    )
    $failurePayload = Get-Content -Raw -Encoding UTF8 $failurePath | ConvertFrom-Json
    if ($failure.ExitCode -ne 3 -or -not $failurePayload.decision.triggered) {
        throw "failing policy did not emit a triggered report and return three"
    }
    if ($failure.Stdout.Count -ne 0 -or $failure.Stderr -ne "") {
        throw "failing policy contaminated stdout or stderr"
    }

    $matching = @($failurePayload.decision.matching_finding_indices).Count
    Write-Output "RigPilot deterministic CI demo: PASS"
    Write-Output "Version: $($version.Stdout -join '')"
    Write-Output "Passing policy: exit 0, policy schema $($passPayload.policy_schema_version)"
    Write-Output "Failing policy: exit 3, $matching triggering findings, report emitted"
    Write-Output "Repeated JSON report: byte-for-byte identical"
    Write-Output "Live collection: not performed"
}
finally {
    $resolvedTemp = [IO.Path]::GetFullPath($tempRoot)
    $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (
        $resolvedTemp.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -and
        $resolvedTemp -ne $tempBase
    ) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
}
