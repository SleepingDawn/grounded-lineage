# grounded-lineage one-shot installer for Windows (PowerShell 5.1 or 7).
#
#   irm https://raw.githubusercontent.com/SleepingDawn/grounded-lineage/main/install.ps1 | iex
#
# or, from a clone:  powershell -ExecutionPolicy Bypass -File install.ps1 [--readcube] [--non-interactive]
# Options also come from $env:GL_INSTALL_ARGS (for the irm | iex form), and the install folder
# from $env:GL_ROOT (default: ~/.local/share/research-tools).
# Needs git. Installs uv (https://astral.sh/uv) if missing; uv provides Python 3.12.
# Safe to rerun: finished steps are checked and skipped. Rerun it when a session expires.
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    $env:PYTHONUTF8 = '1'
    try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $forward = @($args)
    if ($env:GL_INSTALL_ARGS) { $forward += $env:GL_INSTALL_ARGS -split '\s+' | Where-Object { $_ } }
    $root = if ($env:GL_ROOT) { $env:GL_ROOT } else { Join-Path $HOME '.local\share\research-tools' }
    for ($i = 0; $i -lt $forward.Count - 1; $i++) { if ($forward[$i] -eq '--root') { $root = $forward[$i + 1] } }

    function Invoke-Checked([string]$Exe, [string[]]$ArgList) {
        & $Exe @ArgList | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Failed: $Exe $($ArgList -join ' ') (exit $LASTEXITCODE)" }
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'git is required. Install it (winget install --id Git.Git -e) and run this again.'
    }
    $uv = $null
    foreach ($c in @((Get-Command uv -ErrorAction SilentlyContinue).Source, (Join-Path $HOME '.local\bin\uv.exe'))) {
        if ($c -and (Test-Path $c)) { $uv = $c; break }
    }
    if (-not $uv) {
        Write-Host '== Installing uv (https://astral.sh/uv/install.ps1)'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $uv = Join-Path $HOME '.local\bin\uv.exe'
        if (-not (Test-Path $uv)) { throw 'uv was installed but not found; open a new terminal and run this again.' }
    }

    # Use the clone this script sits in, else clone into the install folder.
    $here = if ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }
    if ($here -and (Test-Path (Join-Path $here 'pyproject.toml')) -and (Test-Path (Join-Path $here 'scripts\install_all.py'))) {
        $repo = $here
        if (-not $env:GL_ROOT -and -not ($forward -contains '--root')) {
            $root = Split-Path -Parent $repo
        }
    } else {
        $repo = Join-Path $root 'grounded-lineage'
        New-Item -ItemType Directory -Force $root | Out-Null
        if (Test-Path (Join-Path $repo '.git')) {
            Invoke-Checked 'git' @('-C', $repo, 'pull', '--ff-only')
        } elseif (Test-Path $repo) {
            throw "$repo exists but is not a git clone; move it away and run this again."
        } else {
            Invoke-Checked 'git' @('clone', 'https://github.com/SleepingDawn/grounded-lineage.git', $repo)
        }
    }

    Write-Host "== grounded-lineage in $repo"
    Invoke-Checked $uv @('python', 'install', '3.12')
    $py = Join-Path $repo '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) { Invoke-Checked $uv @('venv', '--python', '3.12', (Join-Path $repo '.venv')) }
    & $py -c 'print(1)' *> $null
    if ($LASTEXITCODE -ne 0) { throw "$py does not run (blocked by application control?)." }
    Push-Location $repo
    try { Invoke-Checked $uv @('pip', 'install', '--python', $py, '-e', '.') } finally { Pop-Location }

    & $py (Join-Path $repo 'scripts\install_all.py') --root $root --uv $uv @forward
    if ($LASTEXITCODE -ne 0) { throw "install_all.py failed (exit $LASTEXITCODE)" }
} @args
