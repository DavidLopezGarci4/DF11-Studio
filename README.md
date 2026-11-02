# DF11 Face Studio (`v1.0.0`)

Estudio fotográfico de **3 capas** (`260 × 310 px`) y sincronizador no destructivo de caras `NG_Regens` para **Football Manager (FM24 / FM27)** en Windows PC. Procesamiento **100% local (`0 €`)** sobre GPU DirectX 12 (`DirectML`) sin claves API ni puertos de red expuestos.

---

## Inicio Rápido

1. Haz doble clic en **`DF11FaceStudio.exe`** (arranque en frío `< 0.5 s` sobre Edge WebView2 nativo).
2. Todo el entorno pesado (`Python 3.12`, `ONNX Runtime DirectML`, pesos `BiRefNet-Lite` / `Selfie-Multiclass` / `YuNet`, caché SQLite WAL y perfil WebView2) reside en `D:\DF11Studio\` para mantener intactos `C:\` y OneDrive.

---

## Modos de Uso

### 1. Estudio DF11 de 3 Capas (`[ Estudio ]`)
- **Capa 3 · Marco Maestro DF11**: Bisel simétrico sin pérdidas y anillo exterior `Alpha = 0` garantizado, con guías ópticas de barbilla/ojos/coronilla conmutables.
- **Capa 2 · Persona + Equipación**: Arrastra un retrato, haz clic o pulsa `Ctrl+V`. Recorte sub-píxel con `BiRefNet-Lite`, armonizado de estudio en espacio `OKLab` y selector de equipación (`Original`, `Club`, `Polo Staff`, `Traje Staff`) con borrado limpio de ropa previa (`P_clothes = 0`) y respeto de pelo/barba (`Z0..Z3`).
- **Capa 1 · Fondo Opcional**: Transparente, Blanco Oficial DF11, presets con bokeh o extracción automática del fondo limpio de la propia fotografía.
- **Exportación**: `PNG` oficial de 32 bits (con actualización atómica de `config.xml`) o `JPG` ligero (`quality=95`, `4:4:4`).

### 2. Sincronizador `NG_Regens` & `FM27` (`[ Sincronizador NG_Regens ]`)
- **Bóveda Intacta**: Lee `D:\DF11Studio\NG_Regens_Vault\` en modo estricto de solo lectura (cero `.bak`, cero mutación de `NG_Regens`).
- **Salida Prioritaria**: Escribe en `000_DF11_Regens_Override` usando 8 hilos paralelos, vía rápida sin `BiRefNet` para pre-recortes transparentes, vigilancia `Live Disk Sync (650ms)` y protección `Shrink Guard (50%)`.
- **Centinela OneDrive & Disco**: Detecta carpetas bajo OneDrive y ofrece el argumento `--user_data_location="D:\FM27 Data"` para **Steam/Epic** y la guía de desvinculación de carpeta para **Xbox / Game Pass**.

---

## Verificación y Recompilación

```powershell
# Suite backend Python + DirectML (34+ tests)
D:\DF11Studio\venv\Scripts\python.exe -m pytest

# Suite frontend React 19 + Vitest
node --preserve-symlinks D:\DF11Studio\web_toolchain\node_modules\vitest\vitest.mjs run --config frontend/vite.config.ts

# Build de producción y lanzador nativo Win32
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Consulta más detalles en [docs/FAQ.md](./docs/FAQ.md) y [CHANGELOG.md](./CHANGELOG.md).
