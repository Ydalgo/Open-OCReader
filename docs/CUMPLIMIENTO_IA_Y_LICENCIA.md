# Cumplimiento Normativo de IA, Privacidad y Licencia Libre — Open OCReader

Este documento ofrece una guía técnica de referencia para **Administraciones Públicas, empresas, Delegados de Protección de Datos (DPD/DPO) y equipos de seguridad** que evalúen el despliegue de **Open OCReader**.

---

## 1. Marco Normativo de Inteligencia Artificial y Privacidad

### 🇪🇺 Reglamento Europeo de Inteligencia Artificial (EU AI Act — Reglamento (UE) 2024/1689)
* **Nivel de riesgo**: Open OCReader actúa como herramienta auxiliar de digitalización y productividad documental (**riesgo mínimo / limitado**). No realiza identificación biométrica remota, puntuación social ni toma de decisiones automatizadas con efectos jurídicos sin intervención humana.
* **Transparencia (Art. 50)**: La interfaz separa claramente el OCR estructural determinista (`RapidOCR`) de las funciones generativas de IA (`Qwen3-VL`), indicando siempre cuándo una salida ha sido generada por un modelo de lenguaje.
* **Supervisión humana (*Human-in-the-Loop*)**: Toda traducción, resumen, respuesta o anonimización producida por el módulo de IA debe ser revisada por una persona antes de incorporarse a expedientes administrativos, contratos o resoluciones oficiales.

### 🇪🇺 RGPD (Reglamento (UE) 2016/679) y 🇪🇸 LOPDGDD
* **Privacidad desde el diseño y por defecto (Art. 25 RGPD)**: El procesamiento OCR y de IA se ejecuta **100% en local (offline / on-premise)**. Ningún documento, imagen ni texto se envía a servidores externos ni a APIs en la nube.
* **Sin transferencias internacionales de datos**: Al no existir comunicación externa durante el análisis documental, se eliminan las transferencias internacionales de datos personales.
* **Soporte a la anonimización**: El módulo híbrido (Regex + IA) facilita la seudonimización/anonimización de DNI, NIE, CIF, IBAN, teléfonos, correos, nombres y direcciones; no obstante, el responsable del tratamiento debe verificar la versión final antes de su publicación o cesión.

### 🇪🇸 Administración Pública y Esquema Nacional de Seguridad (ENS)
* **Apto para redes aisladas (*Air-Gapped*)**: Una vez descargados los modelos (`models/`) y binarios (`bin/`), el sistema opera completamente desconectado de Internet.
* **Trazabilidad y control**: Incluye verificación criptográfica **SHA-256** de artefactos, logs rotativos auditables (`logs/`), autenticación por clave API en modo servidor, CORS restrictivo, saneamiento de entradas y aislamiento `systemd` en Linux.

### 🇺🇸 EE. UU. y Estándares Internacionales (NIST AI RMF, HIPAA, CCPA/CPRA, ISO/IEC 42001)
* **NIST AI RMF e ISO/IEC 42001**: Diseño modular transparente, trazable y auditable con código abierto revisable íntegramente.
* **Confidencialidad (HIPAA / CCPA-CPRA)**: La ejecución íntegramente local dentro del perímetro de la organización evita la exposición de historiales clínicos o datos de clientes a proveedores SaaS de terceros.

> **Aviso legal**: Open OCReader ofrece controles técnicos orientados a facilitar el cumplimiento normativo. La adecuación legal definitiva, la evaluación de impacto (EIPD) y la verificación humana de los resultados corresponden siempre a la empresa o administración que despliega el software.

---

## 2. Licencia de Código Libre y Copyleft (GNU GPL v3.0)

**Open OCReader** es **Software Libre** distribuido bajo la licencia **GNU General Public License v3.0 (GNU GPL v3.0)** ([https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html)).

### Derechos y Obligaciones Clave
1. **Libertad de uso**: Puedes usar Open OCReader libremente en entornos personales, empresariales o de la Administración Pública.
2. **Atribución obligatoria**: Si redistribuyes, reproduces o creas trabajos derivados, debes **mantener el reconocimiento y mención expresa a los autores originales** (**Ydalgo** y colaboradores) y conservar los avisos de licencia.
3. **Copyleft fuerte (Compartir Igual)**: Si modificas el programa, integras mejoras o distribuyes una versión basada en Open OCReader, **estás legalmente obligado a publicar el código fuente de tu versión derivada también como software libre bajo la misma licencia GNU GPL v3.0**. No está permitido cerrar el código ni apropiarse del proyecto en un producto privativo.

*(Nota sobre componentes de terceros: los modelos GGUF como `Qwen3-VL` y los binarios de `llama.cpp` se rigen por sus respectivas licencias abiertas oficiales: Apache 2.0 y MIT).*
