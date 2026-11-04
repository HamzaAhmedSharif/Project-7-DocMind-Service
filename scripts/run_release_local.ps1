param(
    [string]$Image = "docmind-service:local",
    [int]$Port = 8000,
    [string]$ExpectCommit = "",
    [string[]]$EnvFiles = @("deploy/release.env", ".env.neon", ".env"),
    [int]$IpPerMin = 0,
    [string]$Conditions = "local Docker, 512 MB container limit, Neon free plan",
    [switch]$Build
)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not $ExpectCommit) {
    $ExpectCommit = (git rev-parse HEAD).Trim()
}
if (-not (Test-Path "deploy/release.env")) {
    throw "deploy/release.env is missing"
}

$existing = @()
foreach ($file in $EnvFiles) {
    if (Test-Path $file) {
        $existing += $file
    }
}
if (-not ($existing -contains "deploy/release.env")) {
    throw "deploy/release.env must be one of the env files"
}

if ($Build) {
    docker build --build-arg "GIT_SHA=$ExpectCommit" --label "org.opencontainers.image.revision=$ExpectCommit" -t $Image .
    if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
}

docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) {
    throw "image $Image not found; pass -Build to build it from the current tree"
}
$labels = docker inspect --format "{{json .Config.Labels}}" $Image | ConvertFrom-Json
$rev = $labels.'org.opencontainers.image.revision'
if (-not $rev -or $rev -eq "<no value>") {
    throw "image $Image has no org.opencontainers.image.revision label"
}

if ($IpPerMin -le 0) {
    $line = Get-Content "deploy/release.env" |
        Where-Object { $_ -match '^DOCMIND_DEMO_IP_PER_MIN=' } |
        Select-Object -First 1
    $IpPerMin = if ($line) { [int](($line -split '=', 2)[1]) } else { 5 }
}

$py = if ($env:DOCMIND_PYTHON) { $env:DOCMIND_PYTHON } else { "python" }
$container = "docmind-release-local"
$memFile = Join-Path (Get-Location) "mem.txt"
Remove-Item $memFile -ErrorAction SilentlyContinue
docker rm -f $container 2>$null | Out-Null

$envArgs = @()
foreach ($file in $existing) {
    $envArgs += @("--env-file", $file)
}
$runArgs = @(
    "run", "-d", "--name", $container, "--memory", "512m",
    "-p", "127.0.0.1:${Port}:8000"
) + $envArgs + @($Image)
& docker @runArgs | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$smokeExit = 1
$sampler = Start-Job -ScriptBlock {
    param($name, $path)
    while ($true) {
        docker stats --no-stream --format '{{.MemUsage}}' $name 2>$null |
            Out-File -Append -Encoding ascii $path
        Start-Sleep -Seconds 2
    }
} -ArgumentList $container, $memFile

try {
    & $py scripts\smoke_http.py --base "http://127.0.0.1:${Port}" --mode ephemeral `
        --expect-commit $ExpectCommit --expect-image-revision $rev --check-limits `
        --ip-per-min $IpPerMin --json-out smoke.json --mem-file $memFile `
        --runner-type local --container-limit 512m --conditions $Conditions
    $smokeExit = $LASTEXITCODE
}
finally {
    Stop-Job $sampler -ErrorAction SilentlyContinue
    Remove-Job $sampler -Force -ErrorAction SilentlyContinue
    docker logs --tail 40 $container 2>&1 |
        ForEach-Object { $_ -replace 'postgres(ql)?://\S+', '[redacted]' }
    docker rm -f $container 2>$null | Out-Null
}
exit $smokeExit
