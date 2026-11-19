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

$KnownHashes = @{
    "Qwen3VL-4B-Instruct-Q4_K_M.gguf"     = "66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a"
    "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf" = "30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d"
    "Qwen3VL-2B-Instruct-Q4_K_M.gguf"     = "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"
    "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf" = "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82"
    "bge-m3-Q4_K_M.gguf"                  = "6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06"
}

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
        $expected = $KnownHashes[$mf]
        if ($expected) {
            $actual = (Get-FileHash -Path $srcF -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $expected.ToLower()) {
                Write-Warning "Fallo de verificación SHA-256 en $mf ($actual != $expected). Omitiendo copia."
                continue
            }
        }
        Copy-Item -Path $srcF -Destination (Join-Path $TargetModels $mf) -Force
    }
}

# 4. Endurecer permisos ACL en C:\ProgramData\Open OCReader
# Administradores y SYSTEM control total; Usuarios estándar solo lectura y ejecución (evita DLL/Model Hijacking)
try {
    & icacls.exe "$TargetRoot" /inheritance:r /grant "SYSTEM:(OI)(CI)F" /grant "Administrators:(OI)(CI)F" /grant "Users:(OI)(CI)RX" | Out-Null
} catch {
    # Ignorar si no se disponen de privilegios para alterar ACLs
}

exit 0
