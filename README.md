# DF11 Face Studio (`v1.2.0`)

Estudio modular de **3 herramientas** y montaje paso a paso en **4 capas** (`260 × 310 px`), más sincronizador no destructivo de caras `NG_Regens` para **Football Manager (FM24 / FM27)** en Windows PC. Procesamiento **100% local (`0 €`)** sobre GPU DirectX 12 (`DirectML`) sin claves API ni puertos de red expuestos.

---

## Inicio Rápido

1. Haz doble clic en **`DF11FaceStudio.exe`** (arranque en frío `< 0.5 s` sobre Edge WebView2 nativo).
2. Todo el entorno pesado (`Python 3.12`, `ONNX Runtime DirectML`, pesos `BiRefNet-Lite` / `Selfie-Multiclass` / `YuNet`, caché SQLite WAL y perfil WebView2) reside en `D:\DF11Studio\` para mantener intactos `C:\` y OneDrive.

---

## Modos de Uso

### 1. Estudio Modular DF11 (`[ Estudio ]`)
- **Montaje Paso a Paso (4 Capas)**:
  - *Paso 1 · Cara y Cuello*: Clic central con memoria de carpeta, zona de corte previa con rueda antes de extraer, engarce automático de cuello (`NeckBridge`) en espacio `OKLab` e historial completo `Deshacer / Rehacer` (`Ctrl+Z` / `Ctrl+Y` / `Supr`).
  - *Paso 2 · Camiseta Plantilla*: Buscador instantáneo en `tshirt_templates`, asignación de `#ID` numérico de club y temporada, insignia `★ Titular activa`, borrado de plantillas o equipaciones `Club` / `Polo Staff` / `Traje Staff`.
  - *Paso 3 · Fondo*: Blanco Estudio DF11 por defecto, transparente, presets con bokeh o extracción automática del fondo limpio de la foto.
  - *Paso 4 · Marco Maestro DF11 y Exportación*: Bisel oficial simétrico con anillo exterior `Alpha = 0` garantizado en `PNG` de 32 bits (con actualización atómica de `config.xml`) o `JPG` ligero (`quality=95`, `4:4:4`).
- **Extraer Cara**: Aísla cabeza y cuello con control de zona de corte y guarda caras reutilizables en tu biblioteca local.
- **Extraer Camiseta (`2× SSAA`)**: Encuadre previo sobre el lienzo `260 × 310 px` con rueda, arrastre y `Deshacer / Rehacer`, extracción super-muestreada `520 × 620 -> 260 × 310` con ribete de cuello `OKLab` y control de **Nitidez textil**, vinculación a cualquier `#ID` de club de Football Manager (con guía integrada e importador de `config.xml` desde `Graphics`), gestión multi-temporada (`★ Titular activa` vs `Histórico`), buscador y eliminación de plantillas.

### 2. Sincronizador `NG_Regens` & `FM27` (`[ Sincronizador NG_Regens ]`)
- **Bóveda Intacta**: Lee `D:\DF11Studio\NG_Regens_Vault\` en modo estricto de solo lectura (cero `.bak`, cero mutación de `NG_Regens`).
- **Salida Prioritaria**: Escribe en `000_DF11_Regens_Override` usando 8 hilos paralelos, aplicando automáticamente la **camiseta titular activa (`★`)** asociada al `#ID` del club del regen, vigilancia `Live Disk Sync (650ms)` y protección `Shrink Guard (50%)`.
- **Centinela OneDrive & Disco**: Detecta carpetas bajo OneDrive y ofrece el argumento `--user_data_location="D:\FM27 Data"` para **Steam/Epic** y la guía de desvinculación de carpeta para **Xbox / Game Pass**.

---

## Verificación y Recompilación

```powershell
# Suite backend Python + DirectML
D:\DF11Studio\venv\Scripts\python.exe -m pytest

# Suite frontend React 19 + Vitest
node --preserve-symlinks D:\DF11Studio\web_toolchain\node_modules\vitest\vitest.mjs run --config frontend/vite.config.ts

# Build de producción y lanzador nativo Win32
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Consulta más detalles en [docs/FAQ.md](./docs/FAQ.md) y [CHANGELOG.md](./CHANGELOG.md).
