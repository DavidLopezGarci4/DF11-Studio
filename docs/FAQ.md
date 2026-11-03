# Preguntas Frecuentes y Guía de Herramientas (FAQ) — DF11 Face Studio

> Guía de referencia rápida y operativa sobre todas las funciones activas en la versión oficial.
> **Versión:** `v1.1.0` • **Actualizado:** 2026-11-03 • **Módulos Auditados:** 4/4

---

## Índice Rápido
1. [Montaje Paso a Paso en 4 Capas](#1-montaje-paso-a-paso-en-4-capas)
2. [Extractor de Caras y Zona de Corte](#2-extractor-de-caras-y-zona-de-corte)
3. [Extractor de Camisetas y Plantillas de Club](#3-extractor-de-camisetas-y-plantillas-de-club)
4. [Sincronizador NG_Regens, FM27 y OneDrive](#4-sincronizador-ng_regens-fm27-y-onedrive)

---

## 1. Montaje Paso a Paso en 4 Capas

### ¿Cómo funciona el montaje paso a paso y los atajos del Lienzo Oficial DF11?
* **Clic central con memoria de carpeta:** Pulsa en el centro vacío del lienzo `260 × 310 px` (o en `Subir retrato`) para abrir tu última carpeta usada, o pega con `Ctrl+V`.
* **Orden cronológico en 4 pasos:** Paso 1 (`Capa Cara y Cuello` con control `Cuello` para engarzar natural), Paso 2 (`Capa Camiseta Plantilla` o Club/Staff), Paso 3 (`Capa Fondo`, por defecto `Blanco Estudio DF11`) y Paso 4 (`Marco Maestro DF11 y Exportación`).
* **Deshacer, Rehacer y Suprimir:** Usa los botones superiores o los atajos `Ctrl+Z`, `Ctrl+Y` y `Supr` para limpiar o recuperar cualquier cambio al instante.

### ¿En qué formato debo exportar mis fichas para Football Manager?
* **PNG Oficial (Recomendado):** Conserva el anillo exterior transparente (`Alpha = 0`) para integrarse en cualquier skin clara u oscura de Football Manager y actualiza `config.xml`.
* **JPG Ligero:** Aplana la tarjeta sobre blanco puro a máxima nitidez cuando solo quieras compartir la ficha como imagen suelta.

---

## 2. Extractor de Caras y Zona de Corte

### ¿Cómo evito cortar cabezas o pelos al subir una imagen nueva?
* **Zona de corte previa con rueda:** Tanto al subir en el lienzo como en la pestaña `Extraer Cara`, la rueda del ratón acerca o aleja la zona de corte antes de extraer.
* **Aviso de tope de cabeza:** Si el pelo supera la línea segura superior, aparece un aviso ámbar con el botón `Auto-proteger` y el corte solo se ejecuta al pulsar `Aplicar zona de corte`.
* **Relleno natural de cuello:** Si una cara recortada viene con el cuello corto, el deslizador `Cuello` prolonga la piel suavemente hasta dentro de la camiseta elegida.

---

## 3. Extractor de Camisetas y Plantillas de Club

### ¿Cómo convierto cualquier imagen (incluidas camisetas blancas) en plantilla limpia?
* **Pestaña Extraer Camiseta:** Sube una foto con la equipación; la herramienta borra cabeza, cuello y fondo dejando únicamente la camiseta limpia sobre damero oscuro.
* **Hombros blancos completos:** Activa `Simetrizar hombros` y ajusta `Refuerzo hombro` para conservar mangas y hombros blancos incluso cuando el fondo original también sea blanco.
* **Vínculo por club:** Dale un nombre personalizado, asóciala a un club y pulsa `Guardar en tshirt_templates` para reutilizarla en el Estudio y en los lotes de regens.

---

## 4. Sincronizador NG_Regens, FM27 y OneDrive

### ¿Cómo sincronizo miles de caras creadas con NG_Regens sin dañar mis archivos?
* **Modo no destructivo:** Apunta NG_Regens a `D:\DF11Studio\NG_Regens_Vault`; la app lee la bóveda sin renombrar ni alterar su `config.xml` original.
* **Actualización en caliente:** Activa `Live Disk Sync (650ms)` en la pestaña `Sincronizador NG_Regens` para convertir solo los regens nuevos hacia `000_DF11_Regens_Override`.
* **Protección Shrink Guard:** Si un archivo se trunca por accidente a menos de la mitad, la sincronización automática se detiene para proteger tu partida.

### ¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?
* **Steam y Epic Games:** Copia el parámetro `--user_data_location="D:\FM27 Data"` desde el aviso superior y pégalo en Parámetros de lanzamiento del juego.
* **Xbox / Microsoft Store Game Pass:** En Game Pass ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca `Sports Interactive`.
