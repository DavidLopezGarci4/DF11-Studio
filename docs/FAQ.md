# Preguntas Frecuentes y Guía de Herramientas (FAQ) — DF11 Face Studio

> Guía de referencia rápida y operativa sobre todas las funciones activas en la versión oficial.
> **Versión:** `v1.2.0` • **Actualizado:** 2026-11-03 • **Módulos Auditados:** 4/4

---

## Índice Rápido
1. [Montaje Paso a Paso en 4 Capas](#1-montaje-paso-a-paso-en-4-capas)
2. [Extractor de Caras y Zona de Corte](#2-extractor-de-caras-y-zona-de-corte)
3. [Extractor de Camisetas, #ID de Clubes y Temporadas](#3-extractor-de-camisetas-id-de-clubes-y-temporadas)
4. [Sincronizador NG_Regens, FM27 y OneDrive](#4-sincronizador-ng_regens-fm27-y-onedrive)

---

## 1. Montaje Paso a Paso en 4 Capas

### ¿Cómo funciona el montaje paso a paso y los atajos del Lienzo Oficial DF11?
* **Clic central con memoria de carpeta:** Pulsa en el centro vacío del lienzo `260 × 310 px` (o en `Subir retrato`) para abrir tu última carpeta usada, o pega con `Ctrl+V`.
* **Orden cronológico en 4 pasos:** Paso 1 (`Capa Cara y Cuello` con control `Cuello` para engarzar natural), Paso 2 (`Capa Camiseta Plantilla` con buscador instantáneo o Club/Staff), Paso 3 (`Capa Fondo`, por defecto `Blanco Estudio DF11`) y Paso 4 (`Marco Maestro DF11 y Exportación`).
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

## 3. Extractor de Camisetas, #ID de Clubes y Temporadas

### ¿Cómo convierto cualquier imagen (incluidas camisetas blancas) en plantilla nítida?
* **Encuadre previo sobre el lienzo:** Sube la imagen en `Extraer Camiseta`; primero verás la foto sobre el lienzo `260 × 310 px` para ampliarla o reducirla (rueda o deslizador `Tamaño`), moverla y usar `Deshacer / Rehacer` (`Ctrl+Z` / `Ctrl+Y`).
* **Motor 2× SSAA y Nitidez textil:** Ajusta `Nitidez textil` para realzar escudos, patrocinadores y ribetes de cuello sin halos y pulsa `Extraer solo la camiseta` para obtener una prenda limpia y ligera (`~30-45 KB`).
* **Hombros limpios en blancas y oscuras:** `Simetrizar hombros` + `Refuerzo hombro` completan hombros blancos sobre fondo blanco sin contaminar mangas oscuras.

### ¿Cómo conozco el #ID de cada club, busco entre muchas camisetas o actualizo temporadas?
* **Cómo ver el #ID en Football Manager:** En el juego abre `Preferencias -> Interfaz` y activa *«Mostrar ID de pantalla en la barra de título para ayudar con la apariencia»* (ej. `1744` Rayo Vallecano, `1736` Real Madrid). También puedes pulsar `Importar #IDs FM` para leer los `config.xml` de tu carpeta `graphics` o escribir cualquier `#ID` numérico y nombre de club.
* **Actualización por temporadas:** Indica la temporada (ej. `2026/27`) y marca `★ Camiseta Titular Activa` para que ese `#ID` use la nueva equipación conservando tu histórico anterior (o activa `Reemplazar anteriores` si prefieres sustituirla). Puedes cambiar cuál es la `★ Activa` en un clic con el botón `Activar`.
* **Buscador y eliminación:** Filtra por nombre, club, `#ID` o temporada en el buscador y usa los iconos de edición o papelera (`Borrar`) para modificar o eliminar cualquier plantilla de `tshirt_templates`.

---

## 4. Sincronizador NG_Regens, FM27 y OneDrive

### ¿Cómo sincronizo miles de caras creadas con NG_Regens sin dañar mis archivos?
* **Modo no destructivo:** Apunta NG_Regens a `D:\DF11Studio\NG_Regens_Vault`; la app lee la bóveda sin renombrar ni alterar su `config.xml` original.
* **Actualización en caliente con plantilla titular:** Activa `Live Disk Sync (650ms)` en la pestaña `Sincronizador NG_Regens` para convertir solo los regens nuevos hacia `000_DF11_Regens_Override` aplicando la camiseta `★ Titular activa` de cada `#ID` de club.
* **Protección Shrink Guard:** Si un archivo se trunca por accidente a menos de la mitad, la sincronización automática se detiene para proteger tu partida.

### ¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?
* **Steam y Epic Games:** Copia el parámetro `--user_data_location="D:\FM27 Data"` desde el aviso superior y pégalo en Parámetros de lanzamiento del juego.
* **Xbox / Microsoft Store Game Pass:** En Game Pass ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca `Sports Interactive`.
