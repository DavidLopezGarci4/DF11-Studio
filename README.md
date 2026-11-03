# DF11 Face Studio (`v1.4.0`)

Estudio modular de **3 herramientas** y montaje paso a paso en **4 capas** (`260 × 310 px`), modo instantáneo **Foto Directa + Marco DF11**, mejora de **Calidad óptica 100% offline y 0% IA**, edición de fichas de **Packs de Faces FM** y sincronizador no destructivo `NG_Regens` para **Football Manager (FM24 / FM27)** en Windows PC.

---

## Inicio Rápido

1. Haz doble clic en **`DF11FaceStudio.exe`** (arranque en frío `< 0.5 s` sobre Edge WebView2 nativo).
2. Todo el entorno pesado (`Python 3.12`, `ONNX Runtime DirectML`, pesos `BiRefNet-Lite` / `Selfie-Multiclass` / `YuNet`, caché SQLite WAL y perfil WebView2) reside en `D:\DF11Studio\` para mantener intactos `C:\` y OneDrive.

---

## Modos de Uso

### 1. Estudio Modular DF11 (`[ Estudio ]`)
- **Montaje Paso a Paso (4 Capas)**:
  - *Paso 1 · Cara y Cuello o Foto Directa + Marco DF11*:
    - **`Foto Directa + Marco DF11` (0% IA)**: Sube cualquier imagen y aplícale al instante el marco biselado oficial DF11, moviéndola en los **4 puntos cardinales** (`↑ N`, `↓ S`, `← O`, `→ E` + `0,0`), con ratón o flechas del teclado y regulando el **`Zoom` (`35%–300%`)** con pivote central y **`Ajustar a bordes`**.
    - **`Modo Capas (Cara + Camiseta)`**: Movimiento con ratón, pad cardinal o flechas (`←` `↑` `↓` `→`), controles exactos de **`Zoom`** y **`Cuello`** con cuadro numérico + flechas arriba/abajo (`±1%`), **engrosamiento progresivo real del cuello** en `OKLab` y edición directa de fichas ya montadas del Pack de Faces FM (*cambiar camiseta* o *cambiar cara conservando su camiseta*).
  - *Paso 2 · Camiseta Plantilla*: Pestañas limpias **`Plantilla`** (jugadores) y **`Staff`** (cuerpo técnico / trajes), buscador instantáneo, asignación de `#ID` numérico de club y temporada, insignia `★ Titular activa` y gestión completa de `tshirt_templates`.
  - *Paso 3 · Fondo*: Blanco Estudio DF11 por defecto, transparente, presets con bokeh o extracción automática del fondo limpio de la foto.
  - *Paso 4 · Marco Maestro DF11, Calidad Óptica y Exportación*: Regulador **`Calidad óptica` (`0%–100%`)** basado en óptica matemática pura **100% offline y sin IA** (`WGIF` en `OKLab` + remuestreo subpíxel en luz lineal + deblocking JPEG `8×8`), doble destino (**1. Nuestras creaciones** o **2. Pack de Faces FM** renombrando al `<ID>.png` original y actualizando `config.xml`) y anillo exterior `Alpha = 0` garantizado.
- **Extraer Cara**: Aísla cabeza y cuello con control de zona de corte y guarda caras reutilizables en tu biblioteca local.
- **Extraer Camiseta (`2× SSAA`)**: Encuadre previo sobre el lienzo `260 × 310 px` con rueda, arrastre y `Deshacer / Rehacer`, clasificación **`Plantilla` | `Staff`**, extracción super-muestreada `520 × 620 -> 260 × 310` con ribete de cuello `OKLab` y **Nitidez textil**, vinculación a cualquier `#ID` de club de Football Manager y gestión multi-temporada.

### 2. Sincronizador `NG_Regens` & `FM27` (`[ Sincronizador NG_Regens ]`)
- **Bóveda Intacta**: Lee `D:\DF11Studio\NG_Regens_Vault\` en modo estricto de solo lectura (cero `.bak`, cero mutación de `NG_Regens`).
- **Salida Prioritaria**: Escribe en `000_DF11_Regens_Override` usando 8 hilos paralelos, aplicando automáticamente la **camiseta titular activa (`★`)** de `Plantilla` asociada al `#ID` del club del regen, vigilancia `Live Disk Sync (650ms)` y protección `Shrink Guard (50%)`.
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
