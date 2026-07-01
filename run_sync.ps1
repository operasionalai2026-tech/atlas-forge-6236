# ════════════════════════════════════════════════════════════════════════════
#  Wrapper untuk Windows Task Scheduler.
#  Menjalankan run_sync.py dengan argumen yang diberikan, dari folder proyek.
#  Contoh dipanggil scheduler:
#     powershell -ExecutionPolicy Bypass -File run_sync.ps1 -Args "--all"
#     powershell -ExecutionPolicy Bypass -File run_sync.ps1 -Args "--orders"
# ════════════════════════════════════════════════════════════════════════════
param(
    [string]$Args = "--all"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Cari interpreter python (sesuaikan bila perlu / set env PYTHON_EXE)
$py = $env:PYTHON_EXE
if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $py = "py" }
}
if (-not $py) {
    Write-Error "Python tidak ditemukan. Set variabel lingkungan PYTHON_EXE ke path python.exe."
    exit 1
}

# Jalankan
& $py "run_sync.py" $Args.Split(" ")
exit $LASTEXITCODE
