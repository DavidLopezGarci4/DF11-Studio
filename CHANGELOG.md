# Changelog Técnico — DF11 Face Studio

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
