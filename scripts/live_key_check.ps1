# Live key check (Master Script M6.10, step 3).
# Reads the smoke key from $env:DOCMIND_SMOKE_KEY and prints only PASS/FAIL lines.
# Usage: $env:DOCMIND_SMOKE_KEY="dm_..."; powershell -File scripts\live_key_check.ps1 -Base http://127.0.0.1:8000
param(
    [string]$Base = "http://127.0.0.1:8000",
    [int]$TimeoutSec = 30
)

$ErrorActionPreference = "Continue"
$script:failures = 0

function Check($Name, $Passed, $Reason = "") {
    if ($Passed) { Write-Output "PASS $Name" }
    else {
        Write-Output "FAIL $Name : $Reason"
        $script:failures++
    }
}

function Send-Request {
    param($Method, $Path, $Headers, $BodyBytes, $ContentType)
    $url = $Base + $Path
    $req = [System.Net.WebRequest]::Create($url)
    $req.Method = $Method
    $req.Timeout = $TimeoutSec * 1000
    if ($Headers) { foreach ($k in $Headers.Keys) { $req.Headers[$k] = $Headers[$k] } }
    if ($ContentType) { $req.ContentType = $ContentType }
    if ($BodyBytes -and $BodyBytes.Length -gt 0) {
        $req.ContentLength = $BodyBytes.Length
        $stream = $req.GetRequestStream()
        $stream.Write($BodyBytes, 0, $BodyBytes.Length)
        $stream.Close()
    }
    try {
        $resp = $req.GetResponse()
        $status = [int]$resp.StatusCode
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $content = $reader.ReadToEnd()
        $resp.Close()
        return [pscustomobject]@{ Status = $status; Content = $content; Headers = $resp.Headers }
    }
    catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($null -ne $resp) {
            $status = [int]$resp.StatusCode
            $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
            $content = $reader.ReadToEnd()
            $resp.Close()
            return [pscustomobject]@{ Status = $status; Content = $content; Headers = $resp.Headers }
        }
        throw
    }
}

function Get-Json($Method, $Path, $Headers, $BodyBytes, $ContentType) {
    $resp = Send-Request $Method $Path $Headers $BodyBytes $ContentType
    $parsed = $null
    if ($resp.Content) { $parsed = $resp.Content | ConvertFrom-Json -ErrorAction SilentlyContinue }
    return [pscustomobject]@{ Status = $resp.Status; Headers = $resp.Headers; Json = $parsed; Content = $resp.Content }
}

function New-MultipartForm {
    param($FilePath, $FieldName = "file", $FileName = "upload.pdf")
    $boundary = "----DocMind" + [guid]::NewGuid().ToString("N")
    $enc = New-Object System.Text.UTF8Encoding $false  # no BOM; a leading BOM breaks multipart parsing
    $ms = New-Object System.IO.MemoryStream
    $writer = New-Object System.IO.StreamWriter($ms, $enc)
    $writer.Write("--$boundary`r`n")
    $writer.Write("Content-Disposition: form-data; name=`"$FieldName`"; filename=`"$FileName`"`r`n")
    $writer.Write("Content-Type: application/pdf`r`n`r`n")
    $writer.Flush()
    $file = [System.IO.File]::ReadAllBytes($FilePath)
    $ms.Write($file, 0, $file.Length)
    $writer.Write("`r`n--$boundary--`r`n")
    $writer.Flush()
    $bytes = $ms.ToArray()
    $ms.Dispose()
    return [pscustomobject]@{ Bytes = $bytes; ContentType = "multipart/form-data; boundary=$boundary" }
}

# --- setup ---
$key = $env:DOCMIND_SMOKE_KEY
if ([string]::IsNullOrEmpty($key)) {
    Check "setup" $false "DOCMIND_SMOKE_KEY is not set"
    exit 1
}
$keyHeaders = @{ "X-API-Key" = $key }
$badKeyHeaders = @{ "X-API-Key" = "bad" }

# Generate a tiny one-page PDF for the upload checks.
$pdfPath = [System.IO.Path]::GetTempFileName() + ".pdf"
try {
    & python -c "import sys; sys.path.insert(0, '.'); from scripts.make_tiny_pdf import make_pdf; open(r'$pdfPath', 'wb').write(make_pdf(['Self-attention lets each token weigh every other token. Positional encodings give order information.']))" 2>$null | Out-Null
    if (-not (Test-Path $pdfPath)) { throw "pdf not generated" }
}
catch {
    Check "setup" $false "could not generate test PDF"
    exit 1
}
$pdfBytes = [System.IO.File]::ReadAllBytes($pdfPath)
# NOTE: the pdf file itself is not sent inline; New-MultipartForm re-reads it from disk.

$documentId = $null

# 1. bad key -> 401
$r = Get-Json "GET" "/v1/documents" $badKeyHeaders $null $null
Check "bad key 401" ($r.Status -eq 401) "status=$($r.Status)"

# 2. list with key -> 200
$r = Get-Json "GET" "/v1/documents" $keyHeaders $null $null
Check "list with key 200" ($r.Status -eq 200) "status=$($r.Status)"

# 3. upload tiny PDF -> 201
$mf = New-MultipartForm $pdfPath
$r = Get-Json "POST" "/v1/documents" $keyHeaders $mf.Bytes $mf.ContentType
$doc = $r.Json
$documentId = if ($doc) { $doc.document_id } else { $null }
Check "upload tiny PDF 201" (($r.Status -eq 201) -and $documentId) "status=$($r.Status) doc=$doc"

# 4. same upload again -> 200 duplicate (same document_id)
$r = Get-Json "POST" "/v1/documents" $keyHeaders $mf.Bytes $mf.ContentType
$dup = $r.Json
$dupId = if ($dup) { $dup.document_id } else { $null }
Check "same upload again 200 duplicate" (($r.Status -eq 200) -and $dupId -and $dupId -eq $documentId) "status=$($r.Status) doc=$dup"

# 5. query that document 200 with a citation
$qbody = [System.Text.Encoding]::UTF8.GetBytes(([pscustomobject]@{ question = "What does self-attention do?"; document_ids = @($documentId) } | ConvertTo-Json))
$r = Get-Json "POST" "/v1/query" $keyHeaders $qbody "application/json"
$ans = $r.Json
$cited = if ($ans -and $documentId) { @($ans.citations.document_id) -contains $documentId } else { $false }
Check "query that document 200 with a citation" (($r.Status -eq 200) -and $ans -and ($ans.refused -eq $false) -and $cited) "status=$($r.Status) documentId=$documentId ans=$ans"

# 6. same query again -> cache == "hit"
$r = Get-Json "POST" "/v1/query" $keyHeaders $qbody "application/json"
$ans2 = $r.Json
$cacheHit = if ($ans2) { $ans2.usage -and $ans2.usage.cache -eq "hit" } else { $false }
Check "same query again cache hit" (($r.Status -eq 200) -and $cacheHit) "status=$($r.Status) usage=$($ans2.usage)"

# 7. delete 204
$r = Send-Request "DELETE" "/v1/documents/$documentId" $keyHeaders $null $null
Check "delete 204" ($r.Status -eq 204) "status=$($r.Status)"

# 8. list again, document gone
$r = Get-Json "GET" "/v1/documents" $keyHeaders $null $null
$items = if ($r.Json) { $r.Json.items } else { @() }
$gone = ($items | Where-Object { $_.document_id -eq $documentId }).Count -eq 0
Check "list again document gone" (($r.Status -eq 200) -and $gone) "status=$($r.Status) items=$items"

# 9. anonymous upload 403
$mf2 = New-MultipartForm $pdfPath
$r = Get-Json "POST" "/v1/documents" $null $mf2.Bytes $mf2.ContentType
Check "anonymous upload 403" ($r.Status -eq 403) "status=$($r.Status)"

try { Remove-Item $pdfPath -ErrorAction SilentlyContinue } catch {}

if ($script:failures -gt 0) { exit 1 }
exit 0
