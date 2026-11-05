# Preguntas Frecuentes y Guía de Herramientas (FAQ) — DF11 Face Studio

> Guía de referencia rápida y operativa sobre todas las funciones activas en la versión oficial.
> **Versión:** `v1.5.0` • **Actualizado:** 2026-11-05 • **Módulos Auditados:** 4/4

---

## Índice Rápido
1. [Captura en Caliente, Montaje Paso a Paso, Foto Directa y Packs de Faces FM](#1-captura-en-caliente-montaje-paso-a-paso-foto-directa-y-packs-de-faces-fm)
2. [Extractor de Caras y Zona de Corte](#2-extractor-de-caras-y-zona-de-corte)
3. [Extractor de Camisetas, Plantilla / Staff y #ID de Clubes](#3-extractor-de-camisetas-plantilla--staff-y-id-de-clubes)
4. [Sincronizador NG_Regens, FM27 y OneDrive](#4-sincronizador-ng_regens-fm27-y-onedrive)

---

## 1. Captura en Caliente, Montaje Paso a Paso, Foto Directa y Packs de Faces FM

### ¿Cómo funciona «Capturar» y el «Mini-Capturador flotante» para recortar la pantalla del PC sin tapar tu imagen ni borrar el #ID copiado?
* **Mini-Capturador flotante (pantalla despejada):** Pulsa el icono de ventana flotante situado a la derecha de **`Capturar`** (o elige **`Mini-Capturador flotante`** en el menú `▾`) para ocultar la aplicación principal y dejar únicamente una pequeña barra flotante con **`Capturar`**, **`Foto`**, **`Cara`**, **`Camiseta`**, **`PNG`** y el botón **`📌`** (fijar barra para encadenar varias capturas seguidas sin desplegar el Estudio).
* **Cuatro destinos independientes y ocultación limpia sin tocar el portapapeles:** Tanto desde la ventana completa como desde la barra flotante, la app se oculta por completo antes de congelar el escritorio para no aparecer jamás en tus recortes, enviando la imagen directamente a **`Foto Directa + Marco DF11`**, **`Recortar Cara`**, **`Extraer Camiseta`** o **`Guardar PNG como…`** mientras conserva intacto cualquier `#ID` de Football Manager copiado con `Ctrl+C`.
* **Proporción DF11 con `Shift`, atajo `Ctrl+Shift+X` y `Ctrl+V` seguro:** Mantén pulsado **`Shift`** al arrastrar para fijar la proporción oficial `260 × 310 px`, activa si lo deseas el atajo global **`Ctrl+Shift+X`** desde el menú `▾` y pega imágenes con **`Ctrl+V`** en cualquiera de las tres herramientas sin interferir cuando estés escribiendo en cuadros de texto o números.
* **Vídeos en negro por protección del navegador:** Si al capturar un vídeo en pausa aparece un recuadro negro, desactiva *«Usar aceleración por hardware cuando esté disponible»* en los ajustes de tu navegador.

### ¿Cómo creo una ficha rápida con Foto Directa + Marco DF11 (4 puntos cardinales y Zoom)?
* **Formato directo sin recortes ni IA:** En el Paso 1 pulsa **`Foto Directa + Marco DF11`** y sube, arrastra o pega cualquier foto para aplicarle directamente el marco biselado oficial DF11 (`260 × 310 px`) sin separar cabeza ni camiseta.
* **Movimiento en los 4 puntos cardinales y Zoom con pivote central:** Desplaza la imagen en los 4 puntos cardinales mediante los botones **`↑ N`**, **`↓ S`**, **`← O`**, **`→ E`** (`0,0` para centrar), arrastrando con el ratón o con las flechas del teclado (`←` `↑` `↓` `→`, o `Shift` para mayor paso), y aumenta o disminuye por **`Zoom`** (`35%–300%`) con la rueda, la barra, el cuadro numérico exacto o las dos flechas arriba/abajo.
* **Ajustar a bordes y alternancia libre:** Con **`Ajustar a bordes`** activo evitas dejar franjas vacías cuando la foto cubre todo el lienzo, y puedes alternar en cualquier momento con **`Modo Capas (Cara + Camiseta)`** conservando intacto el encuadre de cada modo.

### ¿Cómo funciona «Calidad óptica» en el Paso 4 para mejorar la imagen final sin IA?
* **Procesamiento 100% offline y 0% IA:** En el Paso 4 regula **`Calidad óptica`** (`0%` a `100%`) con barra deslizante, número exacto o flechas arriba/abajo; emplea óptica matemática pura en local sin redes neuronales ni conexión a internet.
* **Nitidez real sin alterar rasgos:** Limpia bloques de compresión JPEG y realza micro-detalles en ojos, cabello y escudos sin halos blancos, protegiendo la textura natural de la piel y los colores intensos de las equipaciones.

### ¿Cómo funciona el Modo Capas en el Paso 1 (ratón, flechas, Zoom y engrosamiento de Cuello)?
* **Movimiento con ratón y flechas del teclado:** Con el Paso 1 seleccionado (`Activo · N/S/E/O, Ratón o ←↑↓→`), arrastra la cabeza con el ratón sobre el lienzo `260 × 310 px` o muévela píxel a píxel con las teclas direccionales `←` `↑` `↓` `→` (mantén `Shift` para saltos rápidos de `5 px`).
* **Zoom y Cuello con cuadro numérico y flechas arriba/abajo:** Tanto en `Zoom` (`15%–220%`) como en `Cuello` (`0%–150%`) dispones de barra deslizante, cuadro de texto numérico exacto y dos flechas situadas inmediatamente a su derecha (`+1%` / `-1%`). El control `Cuello` **engrosa progresivamente el ancho del cuello** para llenar el cuello de cualquier camiseta sin saltos bruscos.
* **Deshacer, Rehacer y Suprimir:** Usa los botones superiores o los atajos `Ctrl+Z`, `Ctrl+Y` y `Supr` para limpiar o recuperar cualquier edición al instante.

### ¿Cómo edito una ficha ya montada de mi Pack de Faces de FM o guardo con su número original?
* **Edición directa de fichas de Facepacks:** En el Paso 1 pulsa **`Cambiar camiseta a ficha FM`** para extraer limpiamente la cabeza y cuello del futbolista sobre cualquiera de tus plantillas, o **`Cambiar cara (conservar su camiseta)`** para aislar la equipación exacta de esa tarjeta en memoria (pudiendo alternar entre `Usar su cara` / `Usar su camiseta` o guardarla en `tshirt_templates`). Si el archivo se llama `<ID>.png`, el número del futbolista se rellena solo.
* **Doble destino en el Paso 4:** Elige **`1. Nuestras creaciones`** para guardar en tu carpeta personal (`PNG Oficial` o `JPG`) **sin necesidad de indicar ningún `#ID` oficial de Football Manager** (puedes dejar el cuadro vacío para guardado automático o escribir cualquier nombre libre), o **`2. Pack de Faces FM`** para seleccionar la carpeta gráfica oficial de caras de Football Manager y guardar el archivo con su `<ID>.png` obligatorio actualizando `config.xml` de forma segura.

---

## 2. Extractor de Caras y Zona de Corte

### ¿Cómo evito cortar cabezas o pelos al subir una imagen nueva?
* **Zona de corte previa con rueda y flechas:** Tanto al subir en el lienzo como en `Extraer Cara`, la rueda del ratón acerca o aleja la zona de corte y las flechas o el ratón ajustan el encuadre antes de extraer.
* **Aviso de tope de cabeza:** Si el pelo supera la línea segura superior, aparece un aviso ámbar con el botón `Auto-proteger` y el corte solo se ejecuta al pulsar `Aplicar zona de corte`.
* **Engrosamiento natural de cuello:** Si una cara recortada tiene cuello estrecho o corto, regula `Cuello` (`0%` a `150%`) para ensanchar y prolongar la piel suavemente hasta dentro del escote de la camiseta.

---

## 3. Extractor de Camisetas, Plantilla / Staff y #ID de Clubes

### ¿Cómo extraigo camisetas de jugador o trajes de Staff con máxima nitidez?
* **Clasificación `Plantilla` o `Staff` al extraer:** En `Extraer Camiseta`, selecciona en **`Destino en Paso 2 (Montaje)`** si la prenda pertenece a **`Plantilla`** (equipaciones de futbolistas) o **`Staff`** (polos, chaquetas o trajes de cuerpo técnico). En el Paso 2 solo verás esas dos pestañas reales de alta calidad.
* **Motor 2× SSAA y Nitidez textil:** Ajusta posición y tamaño en el lienzo con `Deshacer / Rehacer`, regula `Nitidez textil` para realzar escudos, marcas y ribetes de cuello y pulsa `Extraer solo la camiseta` (`~30-45 KB`).
* **Hombros limpios en blancas y oscuras:** `Simetrizar hombros` + `Refuerzo hombro` completan hombros blancos sobre fondo blanco sin contaminar mangas oscuras.

### ¿Cómo conozco el #ID de cada club, busco entre muchas camisetas o actualizo temporadas?
* **Cómo ver el #ID en Football Manager:** En el juego abre `Preferencias -> Interfaz` y activa *«Mostrar ID de pantalla en la barra de título para ayudar con la apariencia»* (ej. `1744` Rayo Vallecano, `1736` Real Madrid). También puedes pulsar `Importar #IDs FM` sobre tu carpeta `graphics` o escribir cualquier `#ID` numérico y nombre de club.
* **Actualización por temporadas:** Indica la temporada (ej. `2026/27`) y marca `★ Prenda Titular Activa`; cada club puede tener su camiseta titular de `Plantilla` y su prenda titular de `Staff` de forma independiente.
* **Buscador y eliminación:** Filtra por nombre, club, `#ID`, tipo (`Plantilla` / `Staff`) o temporada y usa los iconos de edición o papelera (`Borrar`) para gestionar `tshirt_templates`.

---

## 4. Sincronizador NG_Regens, FM27 y OneDrive

### ¿Cómo sincronizo miles de caras creadas con NG_Regens sin dañar mis archivos?
* **Modo no destructivo:** Apunta NG_Regens a `D:\DF11Studio\NG_Regens_Vault`; la app lee la bóveda sin renombrar ni alterar su `config.xml` original.
* **Actualización en caliente con plantilla titular:** Activa `Live Disk Sync (650ms)` en `Sincronizador NG_Regens` para convertir solo los regens nuevos hacia `000_DF11_Regens_Override` aplicando la camiseta `★ Titular activa` de `Plantilla` de cada `#ID` de club.
* **Protección Shrink Guard:** Si un archivo se trunca por accidente a menos de la mitad, la sincronización automática se detiene para proteger tu partida.

### ¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?
* **Steam y Epic Games:** Copia el parámetro `--user_data_location="D:\FM27 Data"` desde el aviso superior y pégalo en Parámetros de lanzamiento del juego.
* **Xbox / Microsoft Store Game Pass:** En Game Pass ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca `Sports Interactive`.
