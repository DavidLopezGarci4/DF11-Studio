# Changelog Técnico — DF11 Face Studio

## [1.3.0] - 2026-11-03
### Added
- **Controles de precisión milimétrica en Paso 1 (`StudioView.tsx` + `backend/services/head_neck.py`)**:
  - Desplazamiento de la cabeza y de la zona de corte tanto con el ratón como con las teclas direccionales `←` `↑` `↓` `→` (`1 px` normal, `5 px` con `Shift`) con agrupación inteligente en la pila `Deshacer / Rehacer`.
  - Componente `PercentStepperControl` para **`Zoom`** (`15%–220%`) y **`Cuello`** (`0%–150%`): barra deslizante + cuadro de texto numérico exacto + botones de flecha arriba/abajo (`±1%`) situados inmediatamente a su derecha.
- **Clasificación exclusiva `Plantilla` | `Staff` en plantillas textiles (`kits.py` v3, `templates.py`, `ShirtExtractorTool.tsx`, `StudioView.tsx`)**:
  - Eliminadas del Paso 2 las pestañas generativas de baja calidad (`Original / Sin`, `Club`, `Polo Staff`, `Traje Staff`), dejando únicamente **`Plantilla`** (`player`) y **`Staff`** (`staff`).
  - Migración automática SQLite `PRAGMA user_version = 3` con columna `category` e invariante de prenda titular activa independiente por par `(club_id, category)`.
  - Selector de destino `Plantilla` | `Staff` al extraer o editar prendas en `Extraer Camiseta` y en el Paso 2.
- **Remix de fichas ya montadas de Packs de Faces FM (`studio_workflow.py`, `head_neck.py`, `bridge.py`, `StudioView.tsx`)**:
  - Endpoints IPC `pick_facepack_card`, `load_facepack_card`, `switch_facepack_remix_mode` y `save_adhoc_shirt_template`.
  - Modo `swap_shirt` (*Cambiar camiseta a ficha FM*): des-enmarca anillos exteriores `Alpha = 0` de tarjetas DF11 con fondo opaco (`prepare_facepack_card_for_head_extraction`) antes de ejecutar `BiRefNet`, extrae cabeza y cuello limpios y autocompleta el `<UID>` del jugador.
  - Modo `swap_face` (*Cambiar cara conservando su camiseta*): aísla la camiseta original de la ficha en una capa en memoria `adhoc:shirt-<N>` para vestir cualquier cara nueva o guardarla en `tshirt_templates`.
- **Doble destino de exportación en Paso 4 (`bridge.py`, `fm_config.py`, `StudioView.tsx`)**:
  - Selector explícito entre **1. Nuestras creaciones** (`exportDir`) y **2. Pack de Faces FM** (`facepackDir`, guardando `<UID>.png` con validación de ruta aprobada `_require_approved` y fast-path idempotente en `upsert_fm_config_xml` para no reescribir `config.xml` masivos cuando el `<UID>` ya está registrado).

### Fixed
- **Engrosamiento progresivo real del cuello (`Cuello` / `neckFill`) en `backend/services/head_neck.py`**: corregido `_build_directional_neck_bridge` y `_build_collar_funnel_mask`, donde `in_lower_socket` forzaba antes el 100% del ancho del escote `[x_l+2 .. x_r-2]` para todo `neck_fill > 0.01`; ahora `neck_fill` interpola de forma continua y monótona la anchura anatómica del cuello desde perfil estrecho hasta llenado convexo completo del cuello de la camiseta (`0%` a `150%`).

## [1.2.0] - 2026-11-03
### Added
- **Motor de extracción textil `2× SSAA` (`520 × 620 -> 260 × 310`) en `backend/services/templates.py`**: super-muestreo `2×` con *Edge-Guided Collar Matting* en espacio perceptual `OKLab`, descontaminación exclusiva de borde (`fg_shirt < 0.93` preservando el 100% del RGB interior de escudos y patrocinadores), micro-contraste regulable en luminancia (`detailCrispness` / `Nitidez textil`), reducción `Lanczos` premultiplicada sin halos oscuros y compresión PNG `optimize=True, compress_level=9` (`~28–45 KB` por plantilla, `0 MB` extra en modelos).
- **Gestión completa de `#ID` de club, multi-temporada y catálogo en `ShirtExtractorTool.tsx` + `StudioView.tsx` + `kits.py`**:
  - Tabla SQLite `custom_clubs` y migración automática `PRAGMA user_version = 2` (`club_name`, `season`, `is_active_for_club`) en `shirt_templates`.
  - Asignación de cualquier `#ID` numérico de Football Manager + nombre de club personalizado, guía desplegable in-app (`Preferencias -> Mostrar ID de pantalla en la barra de título`) e importador nativo de `config.xml` desde carpetas `graphics` (`import_clubs_from_fm_graphics`).
  - Soporte multi-temporada con conmutación en 1 clic de `★ Camiseta Titular Activa` por `#ID` (`set_active_club_shirt_template`), opción de reemplazo directo (`replacePreviousForClub`) y auto-promoción al borrar.
  - Buscador instantáneo por nombre, club, `#ID` o temporada, filtros (`Todas`, `★ Activas`, `Histórico`, `Sin club`), edición inline y eliminación segura de plantillas (`delete_shirt_template`).
- **Catálogo semilla ampliado (`assets/kits/club_kits_seed.json`)**: 54 clubes con cobertura completa de LaLiga, clubes históricos españoles (`#1744` Rayo Vallecano, Celta, Girona, Mallorca, Osasuna, Deportivo, Zaragoza, Sporting, Oviedo, Racing…) y grandes ligas europeas.
- **Encuadre previo sobre el lienzo e historial `Deshacer / Rehacer` en `Extraer Camiseta`**: ajuste libre de posición y escala (`0.2x..4.0x`) antes de pulsar `Extraer solo la camiseta`, con pila pura de 40 pasos (`Ctrl+Z`, `Ctrl+Y`, `Supr`) y caché LRU `shirtSourceId`.

### Fixed
- **Condición de carrera `pywebviewready` en arranque en frío (`frontend/src/lib/ipc.ts`, `App.tsx`, `StudioView.tsx`)**: espera reactiva a la inyección de `window.pywebview.api` en WebView2 y recarga automática en el evento `pywebviewready`, evitando caer en `FALLBACK_BOOT` (que mostraba solo 2 clubes).
- **Coherencia cromática en simetría de hombros (`backend/services/templates.py`)**: la reconstrucción bilateral verifica compatibilidad de color con la manga inferior, impidiendo que fotos asimétricas con hombros oscuros sobre fondo blanco (`rayo.png`) expongan franjas blancas mientras mantiene intactos los hombros blancos (`Caucasian0.png`, `ItalMed9.png`).
- **Des-biselado condicional en fotos externas**: `_has_df11_outer_ring` limita la compensación del bisel interior a tarjetas `260 × 310` con firma real de marco DF11.

## [1.1.0] - 2026-11-03
### Added
- **Herramienta Extractor de Caras (`FaceExtractorTool` + `backend/services/head_neck.py`)**: pre-encuadre con rueda de ratón (`CropViewport`), aviso anti-corte de coronilla (`crownSrcY < 19`), extracción limpia de cabeza y cuello (`BiRefNet` + `selfie_multiclass_256x256`), y biblioteca reutilizable en `D:\DF11Studio\caras_extraidas` y `D:\DF11Studio\caras_prueba`.
- **Herramienta Extractor de Camisetas (`ShirtExtractorTool` + `backend/services/templates.py`)**: extracción exclusiva de prenda con des-biselado matemático del marco `df11_frame_overlay.png`, controles `Simetrizar hombros` + `Refuerzo hombro`, archivo no destructivo en `cache/raw_tshirt_sources/` y vinculación SQLite `shirt_templates` (`template_id`, `display_name`, `club_id`).
- **Montaje Paso a Paso en 4 Capas (`StudioView` + `backend/services/studio_workflow.py`)**: clic central vacío con recordatorio de última carpeta, selección previa de zona de corte con rueda antes de extraer, pila `Undo/Redo` (`Ctrl+Z` / `Ctrl+Y`), limpieza reversible con `Suprimir` (`Delete`), y puente anatómico cilíndrico `NeckBridge` en espacio perceptual `OKLab`.
- **Integración automática con `NG_Regens` (`backend/services/sync.py`)**: las sincronizaciones masivas aplican automáticamente la plantilla `tshirt_templates` vinculada al `club_id` del regen cuando existe en SQLite.

### Fixed
- **Hombros blancos sobre fondo blanco (`Caucasian0.png`, `ItalMed9.png`)**: sustituido el producto `biref_a * p_clothes` por `non_skin_gate` (`1 - p_skin_hair`) fuera del cuello (`|x - 130| >= 45, y >= 188`), simetría bilateral exacta `260 - x` (`19 <-> 241`) y solidez descendente `np.maximum.accumulate` en mangas.
- **Fallback CPU bajo límite de memoria DirectML (`backend/services/vision.py`)**: liberación completa de sesiones D3D12 (`_SESSIONS.clear()`, `gc.collect()`, `enable_cpu_mem_arena=False`) ante `DXGI_ERROR_DEVICE_RESET (887A0007)`.

## [1.0.0] - 2026-11-02
### Added
- Toolchain aislado en `D:\DF11Studio\` (Python 3.12, `onnxruntime-directml`, `pywebview` IPC en memoria sin puertos HTTP).
- Marco maestro `260 × 310` RGBA sin pérdidas con simetría especular vertical (`df11_frame_overlay.png` + `df11_inner_mask.png`) y compositor `RGBa` premultiplicado.
- Motores ONNX DirectML verificados por `SHA-256`: `YuNet`, `selfie_multiclass_256x256` y `BiRefNet-Lite` FP16 con extracción de fondo limpio por convolución Gaussiana normalizada.
- Resolutor de equipaciones en 3 niveles (`2D Kits` -> `club_kits_seed.json` -> personalizado) y compositor afín `Z0..Z3` con borrado `P_clothes = 0`.
- Escáner `defusedxml` para bóveda `NG_Regens`, Centinela OneDrive/FM27, lote incremental en 8 hilos con `safe_ntfs_replace` y `QuiescentVaultWatcher` (`650 ms` + `Shrink Guard 50%`).
- Selector nativo de imágenes y carpetas con persistencia de la última ruta utilizada en `app_prefs` (`last_image_dir`, `last_bg_dir`, `last_vault_dir`, `last_export_dir`) y desbloqueo de clic en el lienzo de subida.
