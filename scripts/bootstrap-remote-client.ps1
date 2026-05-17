<#
.SYNOPSIS
    Bootstrap a Windows client to run opencode locally against a BaluHost remote Ollama.

.DESCRIPTION
    Idempotent Windows equivalent of scripts/bootstrap-remote-client.sh.
    1. Downloads pinned opencode.exe to %LOCALAPPDATA%\balu-code-client, verifies SHA-256.
    2. Writes %APPDATA%\opencode\opencode.json from the in-repo template.
    3. Prompts once for the BaluHost API key, saves it to %APPDATA%\balu-code\api_key.
    4. Prints the PATH snippet (per-session and permanent) the user needs.

    Re-running picks up new -BaseUrl / -Model / -NumCtx values, keeps the saved
    API key unless -NewKey is passed.

.PARAMETER NewKey
    Re-prompt for the API key even if one is already saved.

.PARAMETER BaseUrl
    BaluHost base URL without trailing slash. Skips prompt when provided.

.PARAMETER Model
    Default model (e.g. qwen3-coder:30b). Skips prompt when provided.

.PARAMETER NumCtx
    Context window size (e.g. 32768). Skips prompt when provided.

.EXAMPLE
    .\scripts\bootstrap-remote-client.ps1 `
        -BaseUrl https://baluhost.duckdns.org `
        -Model qwen3-coder:30b `
        -NumCtx 32768
#>
[CmdletBinding()]
param(
    [switch]$NewKey,
    [string]$BaseUrl,
    [string]$Model,
    [string]$NumCtx
)

$ErrorActionPreference = 'Stop'

$OpencodeVersion = '1.14.50'
$OpencodeTriple  = 'windows-x64'
$OpencodeSha256  = 'ece81eb143a3a124a2b6f6b4312d244109917b9e7afbf2e8f31d8894ccd42f44'
$OpencodeUrl     = "https://github.com/sst/opencode/releases/download/v$OpencodeVersion/opencode-$OpencodeTriple.zip"

$InstallDir = Join-Path $env:LOCALAPPDATA 'balu-code-client'
$BinaryPath = Join-Path $InstallDir 'opencode.exe'
$ConfigDir  = Join-Path $env:APPDATA 'opencode'
$ConfigFile = Join-Path $ConfigDir 'opencode.json'
$KeyDir     = Join-Path $env:APPDATA 'balu-code'
$KeyFile    = Join-Path $KeyDir 'api_key'

$RepoRoot     = Split-Path -Parent $PSScriptRoot
$TemplatePath = Join-Path $RepoRoot 'docs\remote-client\opencode.json.tmpl'

if (-not (Test-Path $TemplatePath)) {
    throw "Template not found at $TemplatePath. Run from a clone of the Balu_Code repo."
}

# --- 1. Binary ---
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$needDownload = $true
if (Test-Path $BinaryPath) {
    $actual = (Get-FileHash -Path $BinaryPath -Algorithm SHA256).Hash.ToLower()
    if ($actual -eq $OpencodeSha256) {
        Write-Host "opencode.exe already present and verified."
        $needDownload = $false
    } else {
        Write-Host "opencode.exe checksum mismatch; will re-download."
    }
}
if ($needDownload) {
    Write-Host "Downloading opencode $OpencodeVersion ($OpencodeTriple)..."
    $tmpDir = Join-Path $env:TEMP "balu-bootstrap-$(Get-Random)"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    try {
        $zipPath = Join-Path $tmpDir 'opencode.zip'
        # ProgressPreference SilentlyContinue speeds Invoke-WebRequest up dramatically.
        $oldPref = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri $OpencodeUrl -OutFile $zipPath -UseBasicParsing
        } finally {
            $ProgressPreference = $oldPref
        }
        Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force
        $extracted = Get-ChildItem -Path $tmpDir -Filter 'opencode.exe' -Recurse | Select-Object -First 1
        if (-not $extracted) { throw "opencode.exe not found inside zip" }
        $actual = (Get-FileHash -Path $extracted.FullName -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $OpencodeSha256) {
            throw "Checksum mismatch: expected $OpencodeSha256, got $actual"
        }
        Move-Item -Path $extracted.FullName -Destination $BinaryPath -Force
        Write-Host "opencode installed to $BinaryPath"
    } finally {
        Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    }
}

# --- 2. API key ---
New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null
if ((Test-Path $KeyFile) -and -not $NewKey) {
    Write-Host "Reusing existing API key in $KeyFile."
} else {
    Write-Host ""
    Write-Host "Create a BaluHost API key:"
    Write-Host "  https://YOUR-BALUHOST  ->  Profile  ->  API Keys  ->  New"
    Write-Host "It must start with 'balu_'."
    $secure = Read-Host -AsSecureString -Prompt "Paste API key"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if ([string]::IsNullOrEmpty($apiKey) -or -not $apiKey.StartsWith('balu_')) {
        throw "Refusing to save: key is empty or has no 'balu_' prefix."
    }
    [System.IO.File]::WriteAllText($KeyFile, $apiKey)
    Write-Host "API key saved to $KeyFile."
}

# --- 3. Config ---
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$apiKeyValue = (Get-Content -Raw -Path $KeyFile).Trim()

if (-not $BaseUrl) {
    $reply = Read-Host -Prompt "BaluHost base URL (without trailing slash) [https://baluhost.example]"
    $BaseUrl = if ([string]::IsNullOrWhiteSpace($reply)) { 'https://baluhost.example' } else { $reply }
}
if (-not $Model) {
    $reply = Read-Host -Prompt "Default model [qwen2.5-coder:14b]"
    $Model = if ([string]::IsNullOrWhiteSpace($reply)) { 'qwen2.5-coder:14b' } else { $reply }
}
if (-not $NumCtx) {
    $reply = Read-Host -Prompt "Context window (num_ctx) [32768]"
    $NumCtx = if ([string]::IsNullOrWhiteSpace($reply)) { '32768' } else { $reply }
}

$BaseUrl = $BaseUrl.TrimEnd('/')
$fullBase = "$BaseUrl/api/plugins/balu_code/ollama/api"

function ConvertTo-JsonStringFragment([string]$s) {
    # JSON-escape without surrounding quotes, so '"', '\', or control chars in
    # arbitrary values (api key, base url) can't produce invalid JSON.
    $j = $s | ConvertTo-Json -Compress
    return $j.Substring(1, $j.Length - 2)
}

$tmpl = Get-Content -Raw -Path $TemplatePath
# Use .Replace() (literal) rather than -replace (regex) — JSON-escaped values
# may contain backslashes that would be interpreted as regex escapes.
$out = $tmpl.Replace('__BASE_URL__', (ConvertTo-JsonStringFragment $fullBase)) `
            .Replace('__API_KEY__',  (ConvertTo-JsonStringFragment $apiKeyValue)) `
            .Replace('__MODEL__',    (ConvertTo-JsonStringFragment $Model)) `
            .Replace('__NUM_CTX__',  ([int]$NumCtx).ToString())

[System.IO.File]::WriteAllText($ConfigFile, $out)
Write-Host "opencode config written to $ConfigFile"

# --- 4. PATH hint ---
Write-Host ""
Write-Host "Done. To use 'opencode' from any directory:"
Write-Host ""
Write-Host "  # This session only:"
Write-Host "  `$env:Path = `"$InstallDir;`" + `$env:Path"
Write-Host ""
Write-Host "  # Permanent (User scope, takes effect in new shells):"
Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$InstallDir;`" + [Environment]::GetEnvironmentVariable('Path','User'), 'User')"
Write-Host ""
Write-Host "Then in any project: opencode"
