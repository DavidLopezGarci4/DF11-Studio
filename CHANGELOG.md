# Changelog Técnico — DF11 Face Studio

## [1.0.0] - 2026-11-02
### Added
- Toolchain aislado en `D:\DF11Studio\` (Python 3.12, `onnxruntime-directml`, `pywebview` IPC en memoria sin puertos HTTP).
- Marco maestro `260 × 310` RGBA sin pérdidas con simetría especular vertical (`df11_frame_overlay.png` + `df11_inner_mask.png`) y compositor `RGBa` premultiplicado.
- Motores ONNX DirectML verificados por `SHA-256`: `YuNet`, `selfie_multiclass_256x256` y `BiRefNet-Lite` FP16 con extracción de fondo limpio por convolución Gaussiana normalizada.
- Resolutor de equipaciones en 3 niveles (`2D Kits` -> `club_kits_seed.json` -> personalizado) y compositor afín `Z0..Z3` con borrado `P_clothes = 0`.
- Escáner `defusedxml` para bóveda `NG_Regens`, Centinela OneDrive/FM27, lote incremental en 8 hilos con `safe_ntfs_replace` y `QuiescentVaultWatcher` (`650 ms` + `Shrink Guard 50%`).
