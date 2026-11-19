<#
.SYNOPSIS
  Aprovisionador automático de hardware ejecutado por el instalador MSI de Open OCReader.
  Inspecciona el hardware del PC destino (RAM y GPU Vulkan/CPU) y copia desde la carpeta
  compañera `<SourceDir>\offline_repo\` hacia `C:\ProgramData\Open OCReader\` ÚNICAMENTE
  los binarios y modelos GGUF adecuados al equipo, accesibles para todos los usuarios.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir
)

$ErrorActionPreference = "SilentlyContinue"
$SourceDir = $SourceDir.TrimEnd('\', '"', ' ')
$OfflineRepo = Join-Path $SourceDir "offline_repo"

if (-not (Test-Path $OfflineRepo)) {
    # Instalación estándar online (sin carpeta offline_repo compañera) -> salir limpiamente
    exit 0
}

$TargetRoot = Join-Path $env:ProgramData "Open OCReader"
$TargetBin = Join-Path $TargetRoot "bin"
$TargetModels = Join-Path $TargetRoot "models"
New-Item -ItemType Directory -Force -Path $TargetBin, $TargetModels | Out-Null

# 1. Detectar hardware real del equipo destino
$RamBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$RamGB = [math]::Round($RamBytes / 1GB, 2)
$HasVulkan = Test-Path (Join-Path $env:SystemRoot "System32\vulkan-1.dll")

# 2. Copiar binario(s) llama.cpp adecuados (siempre incluir CPU como respaldo seguro)
$SrcBinRoot = Join-Path $OfflineRepo "bin"
if ($HasVulkan -and (Test-Path (Join-Path $SrcBinRoot "win-vulkan-x64"))) {
    Copy-Item -Path (Join-Path $SrcBinRoot "win-vulkan-x64") -Destination $TargetBin -Recurse -Force
}
if (Test-Path (Join-Path $SrcBinRoot "win-cpu-x64")) {
    Copy-Item -Path (Join-Path $SrcBinRoot "win-cpu-x64") -Destination $TargetBin -Recurse -Force
}

# 3. Seleccionar modelos GGUF según RAM total del PC destino
$SrcModels = Join-Path $OfflineRepo "models"
$ModelsToCopy = @()

if ($RamGB -ge 10.0) {
    $ModelsToCopy += "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    $ModelsToCopy += "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
    $ModelsToCopy += "bge-m3-Q4_K_M.gguf"
} elseif ($RamGB -ge 6.0) {
    $ModelsToCopy += "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
    $ModelsToCopy += "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
    $ModelsToCopy += "bge-m3-Q4_K_M.gguf"
} elseif ($RamGB -ge 4.0) {
    $ModelsToCopy += "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
    $ModelsToCopy += "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
}
# Si RamGB < 4.0 (perfil ocr_only): no se copian modelos pesados para no desperdiciar disco

foreach ($mf in $ModelsToCopy) {
    $srcF = Join-Path $SrcModels $mf
    if (Test-Path $srcF) {
        Copy-Item -Path $srcF -Destination (Join-Path $TargetModels $mf) -Force
    }
}

exit 0
