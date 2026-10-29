param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

# --- Validar formato de version ---
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Error "Version debe tener formato x.y.z (ej: 0.0.1)"
    exit 1
}

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$InstallerDir = $PSScriptRoot
$UploadDir = Join-Path $InstallerDir "upload-to-release"
$SetupName = "NeuroFlex-Setup-$Version.exe"
$SetupPath = Join-Path $UploadDir $SetupName
$LatestJsonPath = Join-Path $UploadDir "latest.json"

# Crear y limpiar carpeta de salida
if (Test-Path $UploadDir) {
    Remove-Item "$UploadDir\*" -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path $UploadDir -Force | Out-Null
}
Write-Host "  Directorio: $UploadDir"

# --- 1. Build PyInstaller ---
Write-Host "[1/4] Compilando con PyInstaller..."
$PyInstaller = @(
    (Join-Path $RepoRoot ".venv\Scripts\pyinstaller.exe"),
    (Join-Path $RepoRoot "venv\Scripts\pyinstaller.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $PyInstaller) {
    Write-Error "No se encuentra pyinstaller en .venv ni en venv"
    exit 1
}
Push-Location $RepoRoot
try {
    & $PyInstaller "neuroflex.spec" --noconfirm
    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller fallo con codigo $LASTEXITCODE"
        exit 1
    }
} finally {
    Pop-Location
}
Write-Host "  PyInstaller completado."

# --- 2. Build NSIS ---
Write-Host "[2/4] Compilando instalador NSIS..."
$Makensis = "C:\Program Files (x86)\NSIS\makensis.exe"
if (-not (Test-Path $Makensis)) {
    Write-Error "No se encuentra makensis en $Makensis"
    exit 1
}
& $Makensis "/DAPP_VERSION=$Version" (Join-Path $InstallerDir "neuroflex.nsi")
if ($LASTEXITCODE -ne 0) {
    Write-Error "NSIS fallo con codigo $LASTEXITCODE"
    exit 1
}
Write-Host "  NSIS completado."

# --- Mover .exe a upload-to-release ---
$NsisOutputPath = Join-Path $InstallerDir $SetupName
if (Test-Path $NsisOutputPath) {
    Move-Item $NsisOutputPath $SetupPath -Force
    Write-Host "  Movido a: $SetupPath"
}

# --- 3. Calcular SHA256 ---
Write-Host "[3/4] Calculando SHA256..."
if (-not (Test-Path $SetupPath)) {
    Write-Error "No se encontro el instalador generado: $SetupPath"
    exit 1
}
$Sha256 = (Get-FileHash $SetupPath -Algorithm SHA256).Hash
Write-Host "  SHA256: $Sha256"

# --- 4. Generar latest.json ---
Write-Host "[4/4] Generando latest.json..."
$LatestUrl = "https://github.com/basstiago/neuroflex-dashboard/releases/download/v$Version/$SetupName"
$Latest = @{
    version   = $Version
    url       = $LatestUrl
    sha256    = $Sha256
    changelog = ""
}
$LatestJson = $Latest | ConvertTo-Json -Compress
$LatestJson | Out-File -FilePath $LatestJsonPath -Encoding utf8 -NoNewline
Write-Host "  latest.json generado."

# --- Resumen ---
Write-Host ""
Write-Host "========================================"
Write-Host " Release v$Version lista"
Write-Host "========================================"
Write-Host " Instalador : $SetupPath"
Write-Host " SHA256     : $Sha256"
Write-Host " latest.json: $LatestJsonPath"
Write-Host ""
Write-Host "Para subir manualmente a la release:"
Write-Host "  1. $SetupName"
Write-Host "  2. latest.json"
Write-Host "========================================"
