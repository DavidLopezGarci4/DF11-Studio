# Preguntas Frecuentes y Guía de Herramientas (FAQ) — DF11 Face Studio

> Guía de referencia rápida y operativa sobre todas las funciones activas en la versión oficial.
> **Versión:** `v1.0.0` • **Actualizado:** 2026-11-02 • **Módulos Auditados:** 3/3

---

## Índice Rápido
1. [Estudio DF11 de 3 Capas](#1-estudio-df11-de-3-capas)
2. [Equipaciones de Club y Staff](#2-equipaciones-de-club-y-staff)
3. [Sincronizador NG_Regens, FM27 y OneDrive](#3-sincronizador-ng_regens-fm27-y-onedrive)

---

## 1. Estudio DF11 de 3 Capas

### ¿Cómo funcionan las 3 capas para crear un futbolista o miembro del staff?
* **Capa 3 (Marco Maestro DF11):** Mantiene fijo el bisel interior simétrico y el anillo exterior transparente oficial de `260 × 310 px`.
* **Capa 2 (Persona):** Permite arrastrar una foto, hacer clic en `Subir retrato` o pegar con `Ctrl+V` para recortar el fondo sin coste de API.
* **Capa 1 (Fondo Opcional):** Elige entre transparente, blanco estudio oficial DF11, fondos de estadio/despacho con bokeh o extraer el fondo limpio de tu propia foto.

### ¿En qué formato debo exportar mis fichas para Football Manager?
* **PNG Oficial (Recomendado):** Conserva el anillo transparente exterior para integrarse en cualquier skin clara u oscura de Football Manager y actualiza `config.xml`.
* **JPG Ligero:** Aplana la tarjeta sobre blanco puro a máxima nitidez cuando solo quieras compartir la ficha como imagen suelta.

---

## 2. Equipaciones de Club y Staff

### ¿Cómo evita la app que queden logotipos antiguos o colores falsos en la camiseta?
* **Sustitución limpia:** Al activar `Equipación -> Club`, `Polo Staff` o `Traje Staff`, la prenda callejera anterior desaparece por completo antes de vestir la nueva camiseta.
* **Colores reales:** La app prioriza tus packs de camisetas 2D instalados o la base curada de clubes reales, y usa el escudo únicamente como insignia en el pecho.
* **Respeto anatómico:** El pelo largo, la barba y las gafas se mantienen siempre por delante del cuello de la equipación.

---

## 3. Sincronizador NG_Regens, FM27 y OneDrive

### ¿Cómo sincronizo miles de caras creadas con NG_Regens sin dañar mis archivos?
* **Modo no destructivo:** Apunta NG_Regens a `D:\DF11Studio\NG_Regens_Vault`; la app lee la bóveda sin renombrar ni alterar su `config.xml` original.
* **Actualización en caliente:** Activa `Live Disk Sync (650ms)` en la pestaña `Sincronizador NG_Regens` para convertir solo los regens nuevos hacia `000_DF11_Regens_Override`.
* **Protección Shrink Guard:** Si un archivo se trunca por accidente a menos de la mitad, la sincronización automática se detiene para proteger tu partida.

### ¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?
* **Steam y Epic Games:** Copia el parámetro `--user_data_location="D:\FM27 Data"` desde el aviso superior y pégalo en Parámetros de lanzamiento del juego.
* **Xbox / Microsoft Store Game Pass:** En Game Pass ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca `Sports Interactive`.
