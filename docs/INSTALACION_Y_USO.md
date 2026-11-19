# Guía de Instalación, Compilación y Uso - Open OCReader

## 1. Estructura del Proyecto

```text
Open OCReader/
├── src/                      # Código fuente en Python
│   ├── ocr_tool.py           # CLI principal
│   ├── Open_OCReader.pyw     # Lanzador gráfico sin consola
│   └── open_ocreader/        # Paquete modular (OCR, formatos, GUI, IA, logs)
├── scripts/
│   ├── windows/              # Scripts .bat y compilador .exe para Windows
│   └── linux/                # Scripts .sh de instalación, arranque y compilación
├── models/                   # Modelos GGUF locales (Qwen3-VL-4B-Instruct)
├── bin/                      # Binarios portables de llama.cpp por sistema operativo
├── dist/                     # Ejecutables compilados independientes
├── samples/                  # Documentos de muestra para pruebas
├── logs/                     # Logs rotativos de diagnóstico
└── docs/                     # Documentación técnica
```

---

## 2. Descarga de Modelos de IA (`models/`)

Los modelos de Inteligencia Artificial (`Qwen3VL-4B-Instruct-Q4_K_M.gguf` y `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`) no se incluyen directamente en el código fuente por su tamaño (~2,9 GB).

Al ejecutar cualquier función de IA (manuscritos, traducción, resumen, anonimización o preguntas), si el programa detecta que no están en `models/`, **te ofrecerá elegir entre dos fuentes de descarga**:

1. **Página Oficial (Hugging Face)**: Descarga directa desde `Qwen/Qwen3-VL-4B-Instruct-GGUF`.
2. **Proyecto GitHub**: Descarga desde las Releases oficiales de `Ydalgo/Open-OCReader`.

---

## 3. Uso en Windows

### Opción A: Sin Python instalado (Ejecutable compilado)
1. Descarga el paquete compilado de Windows desde **GitHub Releases** (o compílalo con `scripts\windows\compilar.bat`).
2. Ejecuta `dist\Open_OCReader\Open_OCReader.exe` o haz doble clic en `scripts\windows\iniciar.bat`.

### Opción B: Desde el código fuente
```powershell
pip install -r requirements.txt
# Abrir interfaz gráfica sin consola:
pythonw src\Open_OCReader.pyw
# O usar por terminal:
python src\ocr_tool.py samples\factura_prueba.png
```

### Compilar el `.exe` en Windows:
Haz doble clic en **`scripts\windows\compilar.bat`** (o ejecuta `python scripts\windows\build_exe.py --onefile` para un único fichero portátil).

---

## 4. Uso en Linux

### Instalación y arranque rápido:
```bash
chmod +x scripts/linux/*.sh
./scripts/linux/instalar.sh
./scripts/linux/iniciar.sh
```

### Compilar ejecutable independiente en Linux:
```bash
./scripts/linux/compilar.sh
```
Generará el binario listo en `dist/Open_OCReader/Open_OCReader`.

---

## 5. Versión Portable y Despliegue en Equipos sin Internet (*Air-Gapped* / Intranet Corporativa)

**Open OCReader** es **100% portable**: basta con copiar en una memoria USB o carpeta de red local la estructura del ejecutable compilado junto con las carpetas `bin/` y `models/`:

```text
Open_OCReader_Portable/
├── Open_OCReader.exe         # Ejecutable compilado (o carpeta dist/Open_OCReader/)
├── bin/                      # Binario(s) llama.cpp (ej. win-vulkan-x64 y/o win-cpu-x64)
└── models/                   # Modelos GGUF verificados con SHA-256
    ├── Qwen3VL-4B-Instruct-Q4_K_M.gguf   (o Qwen3VL-2B-Instruct-Q4_K_M.gguf para <10 GB RAM)
    ├── mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf
    └── bge-m3-Q4_K_M.gguf                (opcional, para Chat/AST híbrido en ≥6 GB RAM)
```

> ⚠️ **AVISO IMPORTANTE SOBRE HARDWARE EN COPIAS PORTABLES:**
> Los modelos descargados, los binarios de `llama.cpp` (`Vulkan` vs `CPU`) y las opciones visibles en la interfaz **se adaptan automáticamente al hardware del equipo donde se ejecuta**.
>
> * Si preparas una copia portable en un equipo potente (ej. 16–32 GB RAM con GPU Vulkan) y la trasladas a un equipo corporativo **sin conexión a Internet** con distinto hardware (ej. 4–8 GB RAM o sin Vulkan), **existe riesgo de pérdida de funcionalidades de IA, lentitud extrema o fallo al arrancar el motor local**.
> * **Recomendación para despliegues corporativos *air-gapped*:**
>   1. Incluye el binario **`bin/win-cpu-x64/`** (compatible con cualquier PC x64 incluso sin GPU Vulkan).
>   2. Si los equipos destino tienen **< 10 GB de RAM**, incluye **`Qwen3VL-2B-Instruct-Q4_K_M.gguf`** + su `mmproj` en lugar de la versión 4B.
>   3. Al arrancar, Open OCReader detecta automáticamente cualquier desajuste entre el hardware actual y los archivos presentes en `bin/` y `models/`, reutilizando el modelo local disponible cuando es posible y mostrando un aviso explícito en pantalla.

---

## 6. Instalador Empresarial Windows (`.msi` + `offline_repo/` para GPO / Intune / SCCM)

Para despliegues corporativos en equipos **sin Python, sin `.NET` y sin conexión a Internet**:

1. En tu máquina de compilación, ejecuta **`scripts\windows\compilar_msi.bat`** (o `python scripts\windows\build_msi.py --with-offline-repo`).
   * Instala automáticamente **WiX Toolset v5** si falta, compila `Open_OCReader.exe` y descarga `offline_repo/` con **todos** los binarios (`win-vulkan-x64` + `win-cpu-x64`) y **todos** los modelos (`Qwen3-VL-4B`, `Qwen3-VL-2B` y `BGE-M3`) verificados por SHA-256.
2. Distribuye la carpeta **`dist\Open_OCReader_Enterprise_Kit\`** (contiene el `.msi` y `offline_repo\`):
   ```powershell
   msiexec /i Open_OCReader_0.2.0_x64.msi /qn
   ```
3. Durante la instalación, el MSI detecta el hardware del PC destino y copia en **`C:\ProgramData\Open OCReader\`** únicamente el binario y modelos adecuados a ese equipo. Cualquier usuario estándar (sin permisos de administrador) podrá usar la app guardando sus logs y caché en **`%LOCALAPPDATA%\Open OCReader\`**.


