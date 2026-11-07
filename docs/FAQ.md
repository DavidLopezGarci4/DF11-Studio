# Preguntas Frecuentes y Guía de Herramientas (FAQ) — DF11 Face Studio

> Guía de referencia rápida y operativa sobre todas las funciones activas en la versión oficial.
> **Versión:** `v1.6.0` • **Actualizado:** 2026-11-07 • **Módulos Auditados:** 4/4

---

## Índice Rápido
1. [Captura en Caliente, Montaje Paso a Paso, DF11 Pure / Dual y Packs de Faces FM](#1-captura-en-caliente-montaje-paso-a-paso-df11-pure--dual-y-packs-de-faces-fm)
2. [Extractor de Caras y Zona de Corte](#2-extractor-de-caras-y-zona-de-corte)
3. [Extractor de Camisetas, Plantilla / Staff y #ID de Clubes](#3-extractor-de-camisetas-plantilla--staff-y-id-de-clubes)
4. [Sincronizador NG_Regens, FM27 y OneDrive](#4-sincronizador-ng_regens-fm27-y-onedrive)

---

## 1. Captura en Caliente, Montaje Paso a Paso, DF11 Pure / Dual y Packs de Faces FM

### ¿Dónde encuentro y cómo uso la exportación en DF11 Pure (`220 × 276` sin marco) y el modo Dual a dos carpetas a la vez?
* **Dónde encontrar los botones (3 accesos directos):**
  1. **En la cabecera superior del `Lienzo Oficial DF11`:** Justo encima de la previsualización de tu jugador tienes el selector rápido **`Classic | DF11 Pure | Dual`**.
  2. **En el `Paso 4 · Marco Maestro DF11 y Exportación` (debajo del lienzo):** En la fila **`Formato DF11`** puedes pulsar **`Classic 260×310`**, **`Pure 220×276`** o **`Dual (Ambas)`**.
  3. **En la pestaña `Sincronizador NG_Regens`:** En la barra superior de opciones dispones del mismo selector **`Classic 260×310 | Pure 220×276 | Dual (Ambas)`** para sincronizar lotes completos.
* **Carpetas independientes y conmutador de vista en vivo:** En modo **`Dual (Ambas)`** aparecen dos botones separados de carpeta (uno para **Classic** y otro para **Pure**, tanto en **`1. Nuestras creaciones`** como en **`2. Pack de Faces FM`**) y bajo el lienzo puedes alternar entre **`Vista Classic`** y **`Vista Pure`** antes de guardar.
* **Limpieza de contorno 100% gratuita y 0% IA (ni siquiera la primera vez):** Cuando usas **`Foto Directa + Marco DF11`**, conviertes tarjetas existentes con **`Ficha FM → Pure`** o sincronizas lotes sin equipación de club, un algoritmo óptico determinista limpia al instante el contorno del futbolista (respetando camisetas blancas sobre fondo blanco y viñetas de estudio) sin invocar inteligencia artificial en ningún momento. En fotos con iluminación compleja dispones además del deslizador **`Contorno Pure (0% IA)`** (`0%–100%`) y reimportación `1:1` sin pérdida.
* **Aviso de prioridad en `graphics/` de Football Manager:** Si en modo Dual apuntas ambas carpetas dentro del árbol activo `graphics/` de Football Manager, la app muestra un aviso preventivo recordando que el juego resuelve el mismo `#ID` por orden alfabético de carpetas.

### ¿Cómo funciona «Capturar» y el «Mini-Capturador flotante» para recortar la pantalla del PC sin tapar tu imagen ni borrar el #ID copiado?
* **Mini-Capturador flotante con elección de fondo al instante:** Pulsa el icono de ventana flotante situado a la derecha de **`Capturar`** (o elige **`Mini-Capturador flotante`** en el menú `▾`) para ocultar la aplicación principal y dejar únicamente una pequeña barra flotante con **`Capturar`**, **`Foto`** (mantiene el fondo original), **`Blanco DF11`** (aplica la Capa Blanca Oficial DF11 con `0% IA`), **`Cara`**, **`Camiseta`**, **`PNG`** y el botón **`📌`** (fijar barra para encadenar capturas sin desplegar el Estudio).
* **Menú `Capturar ▾` y ocultación limpia sin tocar el portapapeles:** Tanto desde la ventana completa (**`Foto Directa + Marco DF11`** o **`Foto Directa · Capa Blanca DF11`**) como desde la barra flotante, la app se oculta antes de congelar el escritorio para no aparecer jamás en tus recortes, enviando la imagen directamente a tu herramienta elegida mientras conserva intacto cualquier `#ID` de Football Manager copiado con `Ctrl+C`.
* **Proporción DF11 con `Shift`, atajo `Ctrl+Shift+X` y `Ctrl+V` seguro:** Mantén pulsado **`Shift`** al arrastrar para fijar la proporción oficial `260 × 310 px`, activa si lo deseas el atajo global **`Ctrl+Shift+X`** desde el menú `▾` y pega imágenes con **`Ctrl+V`** en cualquiera de las tres herramientas sin interferir cuando estés escribiendo en cuadros de texto o números.
* **Vídeos en negro por protección del navegador:** Si al capturar un vídeo en pausa aparece un recuadro negro, desactiva *«Usar aceleración por hardware cuando esté disponible»* en los ajustes de tu navegador.

### ¿Cómo creo una ficha rápida con Foto Directa + Marco DF11 (Fondo original vs Capa Blanca DF11, 4 puntos cardinales y Zoom)?
* **Formato directo sin recortes ni IA, con `Fondo original` o `Capa Blanca DF11 (0% IA)`:** En el Paso 1 pulsa **`Foto Directa + Marco DF11`** y sube, captura o pega cualquier foto para aplicarle el marco biselado oficial DF11 (`260 × 310 px`). En **`Fondo Classic`** puedes alternar con un clic entre **`Fondo original`** (conserva el fondo que ya viene en tu captura) y **`Capa Blanca DF11 (0% IA)`** (sustituye el fondo por el blanco degradado oficial DF11 de estudio limpiando el contorno sin usar IA), o seleccionar cualquier escenario en el Paso 3.
* **Movimiento en los 4 puntos cardinales y Zoom con pivote central:** Desplaza la imagen en los 4 puntos cardinales mediante los botones **`↑ N`**, **`↓ S`**, **`← O`**, **`→ E`** (`0,0` para centrar), arrastrando con el ratón o con las flechas del teclado (`←` `↑` `↓` `→`, o `Shift` para mayor paso), y aumenta o disminuye por **`Zoom`** (`35%–300%`) con la rueda, la barra, el cuadro numérico exacto o las dos flechas arriba/abajo.
* **Ajustar a bordes, rescate desde Zona de corte y alternancia libre:** Con **`Ajustar a bordes`** activo evitas dejar franjas vacías, con **`Foto Directa (0% IA)`** rescatas sin pérdida cualquier captura tomada desde la Zona de corte, y puedes alternar en cualquier momento con **`Modo Capas (Cara + Camiseta)`** conservando intacto el encuadre de cada modo.

### ¿Cómo funciona «Calidad óptica» en el Paso 4 para mejorar la imagen final sin IA?
* **Procesamiento 100% offline y 0% IA:** En el Paso 4 regula **`Calidad óptica`** (`0%` a `100%`) con barra deslizante, número exacto o flechas arriba/abajo; emplea óptica matemática pura en local sin redes neuronales ni conexión a internet.
* **Nitidez real sin alterar rasgos:** Limpia bloques de compresión JPEG y realza micro-detalles en ojos, cabello y escudos sin halos blancos, protegiendo la textura natural de la piel y los colores intensos de las equipaciones.

### ¿Cómo funciona el Modo Capas en el Paso 1 (ratón, flechas, Zoom y engrosamiento de Cuello)?
* **Movimiento con ratón y flechas del teclado:** Con el Paso 1 seleccionado (`Activo · N/S/E/O, Ratón o ←↑↓→`), arrastra la cabeza con el ratón sobre el lienzo `260 × 310 px` o muévela píxel a píxel con las teclas direccionales `←` `↑` `↓` `→` (mantén `Shift` para saltos rápidos de `5 px`).
* **Zoom y Cuello con cuadro numérico y flechas arriba/abajo:** Tanto en `Zoom` (`15%–220%`) como en `Cuello` (`0%–150%`) dispones de barra deslizante, cuadro de texto numérico exacto y dos flechas situadas inmediatamente a su derecha (`+1%` / `-1%`). El control `Cuello` **engrosa progresivamente el ancho del cuello** para llenar el cuello de cualquier camiseta sin saltos bruscos.
* **Deshacer, Rehacer y Suprimir:** Usa los botones superiores o los atajos `Ctrl+Z`, `Ctrl+Y` y `Supr` para limpiar o recuperar cualquier edición al instante.

### ¿Cómo edito una ficha ya montada de mi Pack de Faces de FM o guardo con su número original?
* **Edición y conversión directa de fichas de Facepacks:** En el Paso 1 pulsa **`Cambiar camiseta a ficha FM`** para extraer limpiamente la cabeza y cuello del futbolista sobre cualquiera de tus plantillas, **`Cambiar cara (conservar su camiseta)`** para aislar la equipación exacta de esa tarjeta en memoria, o **`Ficha → Pure (0% IA)`** para quitar matemáticamente el bisel de cualquier tarjeta DF11 Classic (`260 × 310 px`) y convertirla al instante en DF11 Pure (`220 × 276 px`) sin IA. Si el archivo se llama `<ID>.png`, el número del futbolista se rellena solo.
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

### ¿Cómo sincronizo miles de caras creadas con NG_Regens en formato Classic, Pure o Dual sin dañar mis archivos?
* **Modo no destructivo:** Apunta NG_Regens a `D:\DF11Studio\NG_Regens_Vault`; la app lee la bóveda sin renombrar ni alterar su `config.xml` original.
* **Formatos Classic, Pure o Dual en carpetas independientes:** Elige **`Classic 260×310`** (`000_DF11_Regens_Override`), **`Pure 220×276`** (`000_DF11_Pure_Override`) o **`Dual (Ambas)`** para sincronizar una o las dos variantes a la vez vistiendo la camiseta `★ Titular activa` de `Plantilla` de cada `#ID` de club y manteniendo cada `config.xml` sincronizado.
* **Actualización en caliente y Shrink Guard:** Activa `Live Disk Sync (650ms)` en `Sincronizador NG_Regens` para convertir solo los regens nuevos y cuenta con detención automática si un archivo se trunca por accidente a menos de la mitad.

### ¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?
* **Steam y Epic Games:** Copia el parámetro `--user_data_location="D:\FM27 Data"` desde el aviso superior y pégalo en Parámetros de lanzamiento del juego.
* **Xbox / Microsoft Store Game Pass:** En Game Pass ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca `Sports Interactive`.

### ¿Cómo reviso la Salud de la Arquitectura (GPU, modelos y base local) y la conexión entre nodos?
* **Acceso desde `Acerca de` (icono `ⓘ`):** Pulsa el botón de información **`ⓘ`** en la esquina superior derecha de la ventana y haz clic en **`Inspeccionar Salud de la Arquitectura`**.
* **Estado en tiempo real y botón de recarga:** En la cabecera del visor comprobarás si la aceleración por tarjeta gráfica está activa, los 3 modelos locales y la rapidez de lectura del catálogo, pudiendo volver a medirlos al instante con el botón **`🔄`**.
* **Mapa Topológico y Rutas de Flujo:** Haz clic sobre cualquier nodo del mapa interactivo, sobre las etiquetas inferiores o sobre las tarjetas **`Conexiones Directas`** (`← Origen` / `→ Destino`) para inspeccionar cómo se conectan los componentes, o cambia a **`Rutas de Flujo`** para seguir paso a paso cada función.
