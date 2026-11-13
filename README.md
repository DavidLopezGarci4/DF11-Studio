# DF11 Face Studio (`v1.6.1`)

Estudio fotográfico en **una sola vista sin scroll exterior (`100vh`)** con soporte nativo para **DF11 Classic (`260 × 310 px` con marco)**, **DF11 Pure (`220 × 276 px` sin marco, `Alpha = 0`)** y **Exportación Dual simultánea en carpetas independientes**, **captura nativa de pantalla en 2 pasos (`Seleccionar -> Reencuadrar -> Intro / Esc` cero-portapapeles)**, modo instantáneo **Foto Directa + Marco DF11**, mejora de **Calidad óptica 100% offline**, edición `1:1` de fichas de **Packs de Faces FM** y sincronizador no destructivo `NG_Regens` para **Football Manager (FM24 / FM27)** en Windows PC.

---

## Inicio Rápido

1. Haz doble clic en **`DF11FaceStudio.exe`** (arranque en frío `< 0.5 s` sobre Edge WebView2 nativo).
2. Todo el entorno pesado (`Python 3.12`, `ONNX Runtime DirectML`, pesos `BiRefNet-Lite` / `Selfie-Multiclass` / `YuNet`, base `SQLite v5 WAL` y perfil WebView2) reside en `D:\DF11Studio\` para mantener intactos `C:\` y OneDrive.

---

## Modos de Uso

### 1. Estudio Modular DF11 (`[ Estudio ]`)
- **Montaje Paso a Paso (3 Pasos)**:
  - *Paso 1 · Cara/Cuello, Formato DF11 (`Classic | Pure | Dual`) o Foto Directa + Marco DF11*:
    - **`Foto Directa + Marco DF11` (0% IA)**: Sube o captura cualquier imagen con **Fondo original** o **Capa Blanca DF11**, moviéndola en los **4 puntos cardinales** (`↑ N`, `↓ S`, `← O`, `→ E` + `0,0`), con ratón o flechas del teclado y regulando **`Zoom` (`35%–300%)**, **`Contorno Pure`** y **`Ajustar a bordes`**.
    - **`Modo Capas (Cara + Camiseta)`**: Movimiento con ratón, pad cardinal o flechas (`←` `↑` `↓` `→`), controles exactos de **`Zoom`** y **`Cuello`** cilíndrico anatómico con cuadro numérico + flechas (`±1%`), gestión y borrado ágil de caras guardadas y edición directa de fichas del Pack de Faces FM (*cambiar camiseta*, *cambiar cara* o *Ficha → Pure*).
  - *Paso 2 · Camiseta Plantilla*: Pestañas reales **`Campo`**, **`Portero (GK)`** y **`Staff`**, buscador instantáneo, convivencia simultánea de `★ Titular activa` por club, temporada y rol, asignación de `#ID` de club y borrado directo.
  - *Paso 3 · Marco Maestro DF11 y Exportación*: Conmutador **`Vista Classic | Vista Pure`**, regulador **`Calidad óptica` (`0%–100%`)** **100% offline y 0% IA** (`WGIF` en `OKLab` + remuestreo subpíxel en luz lineal + deblocking JPEG `8×8`), doble destino (**1. Nuestras creaciones** o **2. Pack de Faces FM**) con carpetas independientes Classic/Pure, guardado atómico en 2 fases con rollback completo y actualización segura de `config.xml`.
- **Recortar Cara**: Aísla cabeza y cuello con control de zona de corte y guarda o limpia caras reutilizables en tu biblioteca local.
- **Extraer Camiseta (`2× SSAA`)**: Encuadre previo sobre el lienzo `260 × 310 px` con rueda, arrastre y `Deshacer / Rehacer` completo (incluyendo metadatos), clasificación **`Campo` | `Portero (GK)` | `Staff`**, extracción super-muestreada `520 × 620 -> 260 × 310` con ribete `OKLab` y **Nitidez textil**, vinculación a `#ID` de club y multi-temporada.

### 2. Sincronizador `NG_Regens` & `FM27` (`[ Sincronizador NG_Regens ]`)
- **Bóveda Intacta**: Lee `D:\DF11Studio\NG_Regens_Vault\` en modo estricto de solo lectura (cero `.bak`, cero mutación de `NG_Regens`).
- **Salida Prioritaria Classic, Pure o Dual**: Escribe hacia `000_DF11_Regens_Override` (`260 × 310`), `000_DF11_Pure_Override` (`220 × 276`) o **ambas carpetas a la vez (`Dual`)** vistiendo la **camiseta titular activa (`★`)** de `Campo` de la temporada más reciente asociada al `#ID` del club, con `Live Disk Sync (650ms)`, `Shrink Guard (50%)` y aviso de colisión bajo `graphics/`.
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
