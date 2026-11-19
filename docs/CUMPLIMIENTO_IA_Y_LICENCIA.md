# Cumplimiento Normativo de IA, Privacidad, ENS y Licencia Libre — Open OCReader

Este documento ofrece una guía técnica de referencia para **Administraciones Públicas, empresas, Delegados de Protección de Datos (DPD/DPO) y equipos de seguridad** que evalúen el despliegue de **Open OCReader**.

---

## 1. Marco Normativo de Inteligencia Artificial y Privacidad

### 🇪🇺 Reglamento Europeo de Inteligencia Artificial (EU AI Act — Reglamento (UE) 2024/1689)
* **Nivel de riesgo**: Open OCReader actúa como herramienta auxiliar de digitalización y productividad documental (**riesgo mínimo / limitado**). No realiza identificación biométrica remota, puntuación social ni toma de decisiones automatizadas con efectos jurídicos sin intervención humana.
* **Transparencia (Art. 50)**: La interfaz separa claramente el OCR estructural determinista (`RapidOCR`) de las funciones generativas de IA (`Qwen3-VL` + `BGE-M3`), indicando siempre cuándo una salida ha sido generada por un modelo de lenguaje y qué perfil de hardware está activo.
* **Supervisión humana (*Human-in-the-Loop*)**: Toda traducción, resumen, respuesta o anonimización producida por el módulo de IA debe ser revisada por una persona antes de incorporarse a expedientes administrativos, contratos o resoluciones oficiales.

### 🇪🇺 RGPD (Reglamento (UE) 2016/679) y 🇪🇸 LOPDGDD
* **Privacidad desde el diseño y por defecto (Art. 25 RGPD)**: El procesamiento OCR, la indexación vectorial AST (`BGE-M3`) y la inferencia LLM se ejecutan **100% en local (offline / on-premise)**. Ningún documento, imagen ni texto se envía a servidores externos ni a APIs en la nube.
* **Sin transferencias internacionales de datos**: Al no existir comunicación externa durante el análisis documental, se eliminan las transferencias internacionales de datos personales.
* **Soporte a la anonimización**: El módulo híbrido (Regex + IA) facilita la seudonimización/anonimización de DNI, NIE, CIF, IBAN, teléfonos, correos, nombres y direcciones; el responsable del tratamiento debe validar siempre la versión final antes de su publicación o cesión.

### 🇪🇸 Administración Pública y Esquema Nacional de Seguridad (ENS)
* **Apto para redes aisladas (*Air-Gapped*)**: Una vez descargados y verificados los modelos (`models/`) y binarios (`bin/`), el sistema opera completamente desconectado de Internet.
* **Trazabilidad y control**:
  * Verificación criptográfica **SHA-256 obligatoria** de todos los modelos GGUF (VLM principal, proyector `mmproj` y embeddings `BGE-M3`) y binarios `llama.cpp`.
  * Exportación nativa a **PDF/A-2b** (estándar ISO 19005-2 con perfil ICC sRGB y metadatos XMP `pdfaid`) para archivo electrónico a largo plazo en Administraciones Públicas.
  * Modo de **instancia única**, logs rotativos con soporte **SIEM/Syslog JSON**, política de inmutabilidad de logs (`OPEN_OCREADER_LOCK_LOGS=1`), desactivación opcional de herramientas PDF (`OPEN_OCREADER_DISABLE_PDF_TOOLS=1`), SBOM CycloneDX 1.5 y API autenticada con `X-API-Key`.

### 🇺🇸 EE. UU. y Estándares Internacionales (NIST AI RMF, HIPAA, CCPA/CPRA, ISO/IEC 42001)
* **NIST AI RMF e ISO/IEC 42001**: Diseño modular transparente, trazable y auditable con código abierto revisable íntegramente e informe de gobernanza en 1 clic.
* **Confidencialidad (HIPAA / CCPA-CPRA)**: La ejecución íntegramente local dentro del perímetro de la organización evita la exposición de historiales clínicos o datos de clientes a proveedores SaaS de terceros.

---

## 2. Inventario y Cumplimiento Normativo por Modelo de IA (SHA-256 Verificado)

Todos los modelos integrados en Open OCReader son **modelos de pesos abiertos bajo licencias permisivas estándar (Apache 2.0 y MIT)**, 100% compatibles con despliegues comerciales, Administraciones Públicas, ENS y GNU GPL v3.0, y están sujetos a verificación criptográfica SHA-256 automática al descargar:

| Modelo / Motor | Rol en Open OCReader | Organización | Licencia | Perfil Hardware | Tamaño aprox. | Huella SHA-256 Oficial (Verificada) |
| :--- | :--- | :--- | :---: | :--- | :---: | :--- |
| **RapidOCR (PP-OCRv4 ONNX)** | OCR estructural determinista (no generativo) | RapidAI / PaddlePaddle | **Apache 2.0** | Todos | ~15 MB | Incluido en paquete `rapidocr-onnxruntime` |
| **Qwen3-VL-4B-Instruct (Q4_K_M)** | VLM Principal (Manuscritos, Q&A, Resúmenes, Traducción, RGPD) | Qwen Team (Alibaba) | **Apache 2.0** | `standard` / `pro` (≥10 GB RAM) | 2,38 GB | `66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a` |
| **mmproj-Qwen3VL-4B (Q8_0)** | Proyector visual para `Qwen3-VL-4B` | Qwen Team (Alibaba) | **Apache 2.0** | `standard` / `pro` (≥10 GB RAM) | 433 MB | `30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d` |
| **Qwen3-VL-2B-Instruct (Q4_K_M)** | VLM Ligero (equipos con RAM reducida) | Qwen Team (Alibaba) | **Apache 2.0** | `light` / `ultra_light` (<10 GB RAM) | 1,05 GB | `089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae` |
| **mmproj-Qwen3VL-2B (Q8_0)** | Proyector visual para `Qwen3-VL-2B` | Qwen Team (Alibaba) | **Apache 2.0** | `light` / `ultra_light` (<10 GB RAM) | 424 MB | `f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82` |
| **BAAI BGE-M3 (Q4_K_M)** | Embeddings multilingües para Árbol AST Híbrido (RRF + BM25) | BAAI (Beijing Academy of AI) | **MIT** | `light` / `standard` / `pro` (≥6 GB RAM) | 418 MB | `6d39681b26c61279ac1f82db35a04a05009e94c415b51c858ff571489a82fc06` |

### Cumplimiento específico de cada modelo
* **Sin telemetría ni conexiones ocultas**: Todos los modelos se ejecutan en formato GGUF/ONNX mediante `llama.cpp` y `ONNX Runtime` completamente aislados en `127.0.0.1` con clave efímera por sesión.
* **Adaptación automática al hardware**: Si el equipo dispone de `< 6 GB` de RAM (`ultra_light`) o menos de `1,2 GB` de RAM libre en tiempo real, el modelo de embeddings `BGE-M3` se desactiva automáticamente y el Árbol AST opera únicamente con **BM25Okapi en RAM** para garantizar estabilidad sin OOM.

---

## 3. Uso Legítimo de la Pestaña "Herramientas PDF"

La pestaña **🛠️ Herramientas PDF** (desbloqueo de restricciones, eliminación de firmas digitales, limpieza de marcas de agua y optimización PDF/A) está concebida exclusivamente para **documentos propios, corporativos o con autorización legítima**:
* **No incluye fuerza bruta ni crackeo de contraseñas de apertura**: para desencriptar un PDF protegido con clave de apertura (AES-128 / AES-256), el usuario debe conocer e introducir la contraseña autorizada.
* **Responsabilidad del usuario**: El usuario es responsable del cumplimiento de la Ley de Propiedad Intelectual (LPI), el RGPD y la normativa sobre autenticidad documental.
* **Control corporativo / ENS**: Los administradores de sistemas pueden ocultar por completo esta pestaña estableciendo la variable de entorno `OPEN_OCREADER_DISABLE_PDF_TOOLS=1`.

> **Aviso legal**: Open OCReader ofrece controles técnicos orientados a facilitar el cumplimiento normativo. La adecuación legal definitiva, la evaluación de impacto (EIPD) y la verificación humana de los resultados corresponden siempre a la empresa o administración que despliega el software.

---

## 4. Licencia de Código Libre y Copyleft (GNU GPL v3.0)

**Open OCReader** es **Software Libre** distribuido bajo la licencia **GNU General Public License v3.0 (GNU GPL v3.0)** ([https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html)).

### Derechos y Obligaciones Clave
1. **Libertad de uso**: Puedes usar Open OCReader libremente en entornos personales, empresariales o de la Administración Pública.
2. **Atribución obligatoria**: Si redistribuyes, reproduces o creas trabajos derivados, debes **mantener el reconocimiento y mención expresa a los autores originales** (**Ydalgo** y colaboradores) y conservar los avisos de licencia.
3. **Copyleft fuerte (Compartir Igual)**: Si modificas el programa, integras mejoras o distribuyes una versión basada en Open OCReader, **estás legalmente obligado a publicar el código fuente de tu versión derivada también como software libre bajo la misma licencia GNU GPL v3.0**. No está permitido cerrar el código ni apropiarse del proyecto en un producto privativo.

*(Nota sobre componentes de terceros: los modelos GGUF `Qwen3-VL` y `BGE-M3`, los binarios de `llama.cpp` y las librerías auxiliares se rigen por sus respectivas licencias abiertas oficiales: Apache 2.0, MIT, MPL-2.0 y AGPL-3.0, todas compatibles con la distribución bajo GNU GPL v3.0).*

---

## 5. Reconocimiento y Créditos al Proyecto Hermano: GuarIdA

Gran parte de la arquitectura técnica, la ingeniería de contexto sin límites y la optimización de inferencia local de **Open OCReader** son adaptaciones directas de las soluciones, registros de decisiones de arquitectura (ADRs) y código fuente del proyecto:

🛡️ **[GuarIdA (Guardián de Identidad y Asistencia con IA Local)](https://github.com/Ydalgo/GuarIdA)**
* **Enlace al repositorio oficial:** [https://github.com/Ydalgo/GuarIdA](https://github.com/Ydalgo/GuarIdA)
* **Autoría original:** Ydalgo (Software Libre bajo GPLv3).

### Módulos y Conceptos Transferidos desde GuarIdA:
1. **Árbol de Nodos Documental (AST)** (`src/open_ocreader/ai/doc_tree.py`):
   Diseñado originalmente en los ADRs 0009 y 0012 de GuarIdA. Descompone documentos masivos en una estructura de nodos jerárquicos con rutas de sección (`Pág. X > Sección Y > Subsección Z`) para recuperar únicamente los fragmentos exactos que resuelven la pregunta del usuario sin superar la ventana de contexto.
2. **Compresión de Vocabulario BPE y Minificación** (`src/open_ocreader/ai/chunking.py`):
   Algoritmo de condensación semántica que reduce los espacios en blanco, estandariza saltos de línea y elimina ruido tipográfico, multiplicando la capacidad efectiva de tokens disponibles en el LLM.
3. **Recuperación Híbrida RRF (Reciprocal Rank Fusion)** (`src/open_ocreader/ai/multi_doc_chat.py`):
   Fusión armónica del algoritmo probabilístico léxico BM25Okapi y el espacio vectorial denso multilingüe BGE-M3 para una precisión quirúrgica en búsquedas documentales cruzadas.
4. **Persistencia Segregada en SQLite WAL con Compresión** (`src/open_ocreader/ai/doc_cache.py`):
   Arquitectura de almacenamiento desacoplada con transacciones ACID en modo WAL y compresión `zstd`/`zlib`, indexando cada fichero por su digest SHA-256 para evitar reprocesamientos innecesarios.
5. **Observación Continua de Hardware y Perfiles Dinámicos** (`src/open_ocreader/ai/hardware.py`):
   Clasificación en 4 escalones (`ultra_light`, `light`, `standard`, `pro`) según la RAM disponible y el soporte de aceleradores (Vulkan/Metal/CPU), garantizando que el software nunca provoque fallos por falta de memoria (Out-Of-Memory / OOM).
6. **Reutilización de KV Cache (`cache_prompt`)**:
   Preservación de los tensores de atención del prompt del sistema para reducir a milisegundos la latencia de primer token en turnos de conversación sucesivos.

> 📢 **Derivación y Colaboración en GuarIdA**:
> Invitamos formalmente a los usuarios de Open OCReader, investigadores y administraciones interesadas en la soberanía del dato a conocer, evaluar y colaborar con el proyecto **[GuarIdA](https://github.com/Ydalgo/GuarIdA)**, el cual se encuentra actualmente en fase activa de desarrollo y sentará las bases de la próxima generación de asistentes soberanos.

---

## 6. Exención de Responsabilidad, Integridad de Pesos y Rieles Éticos (Prompt Madre)

Para garantizar la máxima transparencia jurídica y técnica frente a usuarios y organizaciones, se establecen los siguientes principios de gobernanza:

### 1. Integridad Absoluta de Pesos Neuronales
* Open OCReader ejecuta modelos abiertos desarrollados por terceros (**Qwen3-VL** por Alibaba Cloud y **BGE-M3** por BAAI).
* El autor y mantenedor (**Ydalgo**) **NO entrena, NO re-entrena, NO afina (fine-tuning) ni altera los pesos numéricos originales** de las redes neuronales.
* Los modelos se descargan y ejecutan íntegramente en sus versiones cuantizadas GGUF oficiales, sujetas a verificación criptográfica **SHA-256 en tiempo constante**.

### 2. Exención de Responsabilidad por Respuestas del Modelo
* Ni el autor (**Ydalgo**) ni los colaboradores del proyecto se hacen responsables de las respuestas, opiniones, alucinaciones, inexactitudes fácticas o expresiones inadecuadas que el modelo de lenguaje de terceros pudiera formular ante consultas complejas o textos anómalos.
* El software se distribuye «tal cual» (*as is*), bajo la licencia **GNU General Public License v3.0**, sin garantías de ningún tipo respecto a la certeza de las respuestas generadas por los modelos de IA.

### 3. Rieles de Comportamiento Institucional (Prompt Madre)
Para evitar salidas inapropiadas o descortesías y asegurar un rendimiento óptimo, Open OCReader implementa una capa centralizada de salvaguardas éticas (*Guardrails* / Prompt Madre) inyectada en todas las tareas de IA:
* **Cortesía y respeto**: Tono siempre formal, digno, respetuoso y constructivo, bloqueando cualquier forma de hostilidad, sarcasmo o descalificación.
* **Neutralidad forense**: Ante textos polémicos o con contenido sensible, el modelo actúa como un analizador neutral sin adoptar sesgos.
* **Honestidad analítica (Anti-alucinación)**: Si un dato no figura en los extractos documentales provistos, el modelo debe declarar con transparencia su desconocimiento en lugar de inventar datos.

### 4. Supervisión Humana Obligatoria (Human-in-the-Loop)
Conforme a las exigencias del Reglamento Europeo de IA (EU AI Act):
* **Toda salida generada por la IA debe ser revisada, contrastada y validada por una persona física responsable** antes de su incorporación a expedientes administrativos, resoluciones jurídicas o decisiones comerciales.
