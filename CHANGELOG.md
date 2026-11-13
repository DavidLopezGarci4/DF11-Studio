# Changelog Técnico — DF11 Face Studio

## [1.6.1] - 2026-11-13
### Fixed
- **Integridad transaccional Dual/NTFS y sondas sin efectos secundarios (`backend/bridge.py`, `backend/core/fm_config.py`, `backend/services/templates.py`, `backend/services/sync.py`, `backend/services/kits.py`)**:
  - Rollback con copia previa `prev_bytes` e inclusión de `upsert_fm_config_xml` bajo `_sync_lock` en `_commit_card_exports_atomic` para restaurar archivos sobrescritos ante fallos parciales en modo Dual; `os.chmod(dst, stat.S_IWRITE)` en `safe_ntfs_replace` y mutex `_XML_LOCK` sobre `config.xml`.
  - Sonda `probe_architecture_health` sobre `:memory:` cuando `studio_state.sqlite3` aún no existe; sentencia `INSERT ... SELECT ... WHERE 1=1 ON CONFLICT` válida en `_switch_active_save_conn`; actualización de `_fired_sig` tras `on_quiescent()` en `QuiescentVaultWatcher` y aislamiento de archivo fuente en `_resolve_archive_dir`.
- **Geometría DF11 Pure/Classic, concurrencia ONNX y huella de memoria (`backend/core/compositor.py`, `backend/core/image_guard.py`, `backend/services/vision.py`, `backend/services/head_neck.py`, `backend/services/studio_workflow.py`)**:
  - Corregido el slice superior `crop_arr[2:276, 2:222, 3]` en `unmix_df11_classic_bevel_rgba` y la extensión lateral de mangas (`pad_pure_to_df11_canvas(..., unfeather_edges=True)`) al vestir regens `220 × 276` en `sync.py`; sonda interior `[18:292, 20:240]` en `is_pre_cutout` y activación global de `Image.MAX_IMAGE_PIXELS = MAX_PIXELS`.
  - Unificado `_INFER_LOCK` (`RLock`) entre `ensure_model` y `_run_session`, eliminados `source_rgba`/`source_fg_alpha` en `HeadNeckAsset` (`~120–150 MB` menos de RAM), acotadas cachés LRU (`MAX_CACHED_HEADS = MAX_CACHED_SHIRTS = 16`) y eliminada la doble inferencia/decodificación en `load_regen_into_studio` y `load_saved_face`.
- **Ciclo de vida Win32/Captura y coherencia de estado React (`run_desktop.py`, `screen_capture.py`, `screen_clip_worker.py`, `App.tsx`, `StudioView.tsx`, `ShirtExtractorTool.tsx`, `FaceExtractorTool.tsx`, `RegensSyncView.tsx`)**:
  - Firma `ctypes.wintypes` de 64 bits con `LR_SHARED`, preservación de estado `WS_MAXIMIZE` tras capturar, guardián EOF por `stdin` + temporizador de `300 s` en `screen_clip_worker.py` y bucle `PeekMessageW`/`GetMessageW > 0` en `GlobalCaptureHotkey`.
  - Montaje persistente entre pestañas con compuertas `isActive`, secuencia monotónica `tplSelectSeqRef`, cobertura completa de `Undo/Redo` (`savedFaceId`, metadatos de equipación y `PercentStepperControl`) y selección explícita obligatoria en `tag_my_club`.

### Changed
- **Poda neta de código legado y fuente única de FAQ (`backend/bridge.py`, `backend/core/compositor.py`, `FaqModal.tsx`, `docs/FAQ.md`)**: eliminado el pipeline no modular v1.0, los presets procedurales sin uso y la tabla duplicada de `FaqModal.tsx` (ahora alimentada en tiempo de compilación desde `docs/FAQ.md?raw`), reduciendo el tamaño total del repositorio y eliminando 3 archivos residuales de raíz.

## [1.6.0] - 2026-11-08
### Added
- **Captura de Pantalla en 2 Pasos (`Seleccionar -> Reencuadrar -> Intro / Esc`) y Eliminación de `Mini-Capturador` (`backend/core/screen_clip_worker.py`, `backend/core/screen_capture.py`, `backend/bridge.py`, `run_desktop.py`, `App.tsx`, `StudioView.tsx`)**:
  - Controlador determinista `_ClipStateController` (`IDLE -> PENDING_PRESS -> DRAGGING -> SELECTED`, histéresis de clic reflejo `< 5 px`, umbral de selección `>= 10 px` y ventana de gracia de `90 ms` para soltar `Shift` sin perder proporción `260:310`) con 4 escuadras esmeralda en las esquinas, confirmación por `Intro` (`Return` / `KP_Enter`), cancelación con una mano por `Esc`, reubicación dinámica del HUD superior/inferior y candado de exclusión `_capture_busy_lock`.
  - Eliminación completa de la ventana flotante secundaria `Mini-Capturador` (`capture_addon_html.py`, `addon_win` y métodos IPC asociados), consolidando toda la captura en la ocultación y restauración automática de la ventana principal.
- **Cuello Cilíndrico Anatómico Sin Estiramiento de Trapecios y Extractor Textil `2× SSAA` Refinado (`backend/services/head_neck.py`, `backend/services/templates.py`)**:
  - Medición de cintura submandibular `_measure_cylindrical_neck_waist` en `[chin_y - 0.52*ipd, chin_y - 0.06*ipd]` y recorte columna a columna contra `collar.y_top_curve[x]` + `in_cylindrical_tube`, permitiendo elevar la cabeza (`offset_y < 0`) con un cuello vertical anatómico (`~77 px`) sin estirar verticalmente las alas de los trapecios nativos (`z3`) y anclando la base detrás del tejido opaco (`shirt_alpha > 190`).
  - Puente de esquinas `_build_corner_bridged_vision_card` para recortes de torso sin cabeza (`panY > 0`), eliminación de `np.maximum.accumulate` vertical, supresión exterior `OKLab` por inundación (`_flood_fill_mask_np`) respetando el pecho blanco y mangas oscuras, y refinamiento de borde `_wgif_single_channel(..., r=2)`.
- **Capa Blanca Oficial DF11 Calibrada vs Fondo Original en Capturas y Fotos Directas (`backend/core/compositor.py`, `backend/core/dsp.py`, `backend/services/studio_workflow.py`, `backend/bridge.py`, `StudioView.tsx`, `App.tsx`)**:
  - Calibración fotométrica exacta de `_build_preset_bg("white_df11")` sobre fichas oficiales DF11 Classic (`R == G == B`, gradiente lineal vertical `255 -> 225` y viñeta perimetral separable `s_edge = sx + sy - sx * sy`, reduciendo el `MAE` renderizado de `6.50` a `1.18` niveles de gris).
  - Etapa 5 en `clean_pure_contour_zero_ai` con **Proyección de Línea de Color Sub-píxel** protegida por triple compuerta continua ($\tau = g_{\text{homog}} \cdot g_{\text{contrast}} \cdot g_{\text{colin}}$) y propagación de núcleo en 2 escalas (`r=2` + `r=4` en cascada), eliminando cercos oscuros en capturas tomadas sobre webs/skins oscuras al aplicar `Capa Blanca DF11` sin morder camisetas a rayas ni rizos oscuros.
  - Aislamiento antropométrico en `compute_oklab_harmonize_params` para capturas opacas, extensión lateral `x = 19` y `x = 240..241` al encuadrar recortes `220 × 276` Pure en Classic, rescate sin pérdida `promote_staged_crop_to_direct_photo` desde `Zona de corte`, menú `Capturar ▾` con `Foto Directa · Capa Blanca DF11` y selector sincronizado en Paso 1 y Paso 3 (`__keep_original__`).
- **Formato Oficial DF11 Pure (`220 × 276 px` RGBA PNG, `72 DPI`, `Alpha = 0`, `0%` marco) (`backend/core/compositor.py`, `backend/services/head_neck.py`, `backend/services/templates.py`, `backend/services/studio_workflow.py`)**:
  - Renderizador `render_df11_pure_card` sobre sub-ventana interior exacta `PURE_CROP_BOX = (20, 17, 240, 293)` del espacio canónico `260 × 310`, con feather perimetral determinista de `1 px` (`0.55` en aristas laterales/inferiores, `0.3025` en esquinas inferiores) y saneado `OKLab` en las esquinas inferiores `6 × 6` (`_heal_pure_bottom_corners`) para eliminar muescas heredadas de plantillas Classic redondeadas.
  - Metadato estándar `dpi=(72, 72)` en `export_df11_bytes` y bloqueo estricto de formato `JPG` cuando se exporta una variante transparente DF11 Pure.
  - Reimportación `1:1` sin pérdida (*round-trip* bit-exacto de geometría): detección `is_df11_pure_size(220, 276)`, restauración `pad_pure_to_df11_canvas` en `(20, 17)` + `unfeather_pure_perimeter_rgba` en `Foto Directa`, `Extraer Camiseta` y `Remix de Pack de Faces FM`, y máscara rectangular inferior `[19:242]` (`y >= 260`) en `templates.py` para preservar hombros inferiores rectos en Pure.
- **Arquitectura *Single-Subject Dual-Sink* y Exportación Dual Atómica (`backend/bridge.py`, `backend/core/fm_config.py`, `backend/core/paths.py`, `frontend/src/components/StudioView.tsx`, `frontend/src/App.tsx`)**:
  - Composición única de sujeto y filtro óptico `WGIF` (`compose_modular_subject_rgba` / `_build_step_subject_rgba`) bifurcada sin recalcular inferencia hacia `Classic (260 × 310)` y `Pure (220 × 276)` (`compose_step_dual_cards`, `_compose_dual`).
  - Enrutamiento de carpetas independientes aprobadas por capacidades (`export_dir` / `export_pure_dir` en *1. Nuestras creaciones* y `facepack_dir` / `facepack_pure_dir` en *2. Pack de Faces FM*), resolución de colisiones asimétricas en auto-numeración y commit atómico en 2 fases (`_commit_card_exports_atomic` vía `.tmp` + `safe_ntfs_replace`) con rollback automático si falla cualquiera de los dos sumideros o `config.xml`.
  - Detector `detect_fm_graphics_collision` con aviso preventivo no bloqueante cuando ambas salidas Dual cuelgan simultáneamente de la carpeta activa `graphics/` de Football Manager.
  - Conmutador `Classic 260×310 | Pure 220×276 | Dual (Ambas)` en Paso 4 conservando el layout `100vh` sin scroll exterior, guía óptica `220 × 276` en el lienzo fijo `260 × 310` y selector `Vista Classic | Vista Pure` en modo Dual.
- **Motor Determinista `0% IA` para Contorno DF11 Pure y Desmezclado de Bisel Classic (`backend/core/dsp.py`, `backend/core/compositor.py`, `studio_workflow.py`, `sync.py`, `bridge.py`, `StudioView.tsx`)**:
  - Sustituida por completo cualquier invocación a IA (`BiRefNet` / `onnxruntime` / `YuNet`) en `DF11 Pure` y `Dual` (en `Foto Directa`, `Ficha FM → Pure` y sincronización en lote sin equipación) por el algoritmo óptico determinista `clean_pure_contour_zero_ai` (conversión rápida `OKLab` por LUT, corte lateral dinámico de hombros `_detect_side_shoulder_row`, domo de iluminación WLS, propagación geodésica vectorizada en 8 direcciones `_geodesic_8dir_fast`, pelado perimetral de alto contraste, matting guiado `WGIF` y desmezclado algebraico de borde con guarda bilateral de luminancia).
  - Desmezclado exacto en RGBA premultiplicado `unmix_df11_classic_bevel_rgba` para convertir tarjetas `DF11 Classic (260 × 310)` a `DF11 Pure (220 × 276)` sin línea gris superior ni artefactos en esquinas, curación inferior por mediana vertical por columna (respetando camisetas a rayas) y separación `(classic_subj, pure_subj)` en modo Dual.
- **Sincronización Masiva `NG_Regens` en Modos Classic, Pure y Dual (`backend/services/sync.py`, `frontend/src/components/RegensSyncView.tsx`)**:
  - Soporte `variant="classic" | "pure" | "dual"` y `pure_out_dir` tanto en lote multihilo (`sync_ng_regens_batch`, 8 hilos CPU `100% 0% IA` cuando `apply_club_kits=False`) como en `Live Disk Sync (650ms)`, registrando firmas versionadas `v2_p0ai:` por variante en `regen_manifest`.

## [1.5.0] - 2026-11-05
### Added
- **Captura Nativa de Pantalla `PerMonitorV2` Cero-Portapapeles y Enrutamiento Independiente en Caliente (`backend/core/screen_clip_worker.py`, `backend/core/screen_capture.py`, `bridge.py`, `App.tsx`)**:
  - Trabajador aislado sobre el binario GUI firmado `pythonw.exe` (sin ejecutables auxiliares `.exe` sin firmar ni APIs heurísticas `GetAsyncKeyState`/`WDA_EXCLUDEFROMCAPTURE`/`WINFUNCTYPE`) con `SetProcessDpiAwarenessContext(-4)` (`DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`), `PIL.ImageGrab.grab(all_screens=True)` y lienzo virtual `tkinter` para recortar a píxel físico `1:1` sin mutar el portapapeles de Windows (preservando `<UID>` copiados de Football Manager) ni dejar temporales en disco.
  - Bloqueo opcional de proporción oficial `260:310` manteniendo `Shift` al arrastrar, detección heurística de fotogramas negros por DRM de navegador (`drmWarning`) y aviso de baja resolución (`lowResWarning` cuando `< 180 × 215 px`).
  - Selector global `[ ✂ Capturar | ▾ ]` y botones contextuales independientes hacia: **1) `Foto Directa + Marco DF11` (`0% IA`)**, **2) `Recortar Cara` (`Extraer Cara`)**, **3) `Extraer Camiseta`** (con auto-encuadre `auto_torso_frame` en `panY > 0` bajo `Y = 162` cuando el recorte no incluye cabeza) y **4) `Guardar PNG como…`** (diálogo nativo `SAVE_DIALOG` con bloqueo de solapamiento sobre `NG_Regens`).
  - Atajo global opcional no intrusivo **`Ctrl+Shift+X`** (`RegisterHotKey` con `MOD_NOREPEAT` y degradación limpia si otra app lo ocupa), pegado **`Ctrl+V`** protegido con `isTextEntryTarget` en las 3 herramientas y soporte de arrastre `data:image/` desde navegador.
- **Cimientos Multi-Partida SQLite `v4` (`backend/services/kits.py`, `backend/services/sync.py`, `bridge.py`)**:
  - Migración automática no destructiva `PRAGMA user_version = 4` añadiendo `save_profiles` (sembrada con `"default"` activa) y `save_squad_roster (save_id, uid, club_id, player_name, category)` manteniendo intacta `squad_map (uid, club_id)`.
  - Métodos `list_save_profiles`, `upsert_save_profile` y `set_active_save_profile` expuestos en `StudioBridge`.

### Changed
- **Rediseño de Cabina de Estudio `100vh` Cero-Scroll Exterior (`App.tsx`, `StudioView.tsx`, `FaceExtractorTool.tsx`, `ShirtExtractorTool.tsx`, `RegensSyncView.tsx`, `index.css`, `run_desktop.py`)**:
  - Unificación de las dos barras superiores en una única cabecera compacta `h-12` (`max-w-[1600px]`), persistencia de estado e historial `Undo/Redo` al alternar entre las 3 herramientas del estudio y ventana inicial `1360 × 840` (`min_size=(980, 680)`).
  - Anclaje directo del **Paso 4 (`Calidad óptica + Exportar DF11`)** bajo el lienzo `260 × 310 px` en la columna izquierda, eliminación de tarjetas anidadas (*card-in-card*) en Paso 1, rejilla elástica con scroll interno fino (`6 px` claro/oscuro) en Paso 2 y ancho tabular fijo `w-9` en `Bokeh` del Paso 3.

### Fixed
- **Endurecimiento del importador de vistas de plantilla FM (`import_squad_club_mappings` en `backend/services/sync.py`)**: priorización de nombres completos de club (`custom_clubs`, `shirt_templates` y catálogo semilla) y exclusión de números cortos (`< 3` dígitos como edad o dorsal) cuando no existen como `club_id` conocido ni en cabecera explícita de club.

## [1.4.0] - 2026-11-03
### Added
- **Modo `Foto Directa + Marco DF11` en Paso 1 (`step1Mode: 'direct_photo'` en `StudioView.tsx`, `studio_workflow.py`, `compositor.py`, `bridge.py`)**:
  - Vía ultrarrápida **100% offline y 0% IA** (`pick_direct_photo_source`, `load_direct_photo_source`, `ModularWorkflowSession.load_direct_photo`) que aplica directamente el bisel oficial `df11_frame_overlay.png` y el anillo exterior `Alpha = 0` (`df11_inner_mask.png`) sobre cualquier imagen sin invocar sesiones ONNX (`YuNet`, `BiRefNet`, `Selfie-Multiclass`).
  - Cruceta táctil de **4 puntos cardinales** (`↑ N`, `↓ S`, `← O`, `→ E` + centrado `0,0`), arrastre con ratón y flechas del teclado (`1 px` / `5 px` con `Shift`).
  - **`Zoom` (`35%–300%`) con pivote óptico central `(130, 155)` sin deriva acumulativa** (rueda del ratón, barra deslizante, cuadro numérico exacto y flechas arriba/abajo `±1%`), opción **`Ajustar a bordes`** (`clamp_direct_pan`) e historial `Deshacer / Rehacer` independiente de `Modo Capas`.
- **Motor DSP de Óptica Pura Cero-IA (`backend/core/dsp.py` + control `Calidad óptica` en Paso 4)**:
  - Tablas LUT vectorizadas `sRGB <-> luz lineal` (`8192` entradas) y conversión perceptual `sRGB <-> OKLab` con preservación de tono en compresión de gamut.
  - Remuestreo subpíxel premultiplicado en luz lineal (`resample_linear_subpixel_rgba` en modos `raw`, `contain` y `cover`) con selección automática `Lanczos` (`eff_scale <= 1.35`) / `Bicubic` (`eff_scale > 1.35`) en ventana fuente `O(260 × 310)` constante.
  - Deblocking adaptativo en fronteras `8×8` DCT (`deblock_jpeg_8x8_roi`) sobre la ROI recortada.
  - Filtro guiado ponderado exacto **`WGIF` (`Weighted Guided Image Filter`) `O(1)`** sobre luminancia `OKLab L` (`enhance_df11_pure_optics`), con soft-coring $\tau(L)$ para tonos de piel oscuros y brillos especulares, techo `tanh` anti-doble-enfoque, moderación selectiva de piel excluyendo equipaciones rojas/naranjas y limpieza cromática guiada en `(a, b)`.

### Fixed
- **Doble premultiplicación de canal alfa en composiciones modulares**: sustituido `resample_rgba_premultiplied` con `Image.Resampling.LANCZOS` sobre imágenes ya convertidas a `"RGBa"` en `compositor.py` por `resample_linear_subpixel_rgba` en luz lineal sin oscurecimiento de semitransparencias de cabello.
- **Protección de altas luces en `Luz DF11` para escenas completas**: `harmonize_oklab_pure_optics` (`np.all(fg)`) evalúa `p92_l` en el modo Foto Directa para no quemar fondos claros ni camisetas blancas cuando no existe máscara de recorte.

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
