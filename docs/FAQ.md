# Preguntas Frecuentes y Guía de Herramientas (FAQ) — DF11 Face Studio

> Guía de referencia rápida y operativa sobre todas las funciones activas en la versión oficial.
> **Versión:** `v1.6.1` • **Actualizado:** 2026-11-13 • **Módulos Auditados:** 4/4

---

## Índice Rápido
1. [Captura en Caliente, Montaje Paso a Paso, DF11 Pure / Dual y Packs de Faces FM](#1-captura-en-caliente-montaje-paso-a-paso-df11-pure--dual-y-packs-de-faces-fm)
2. [Extractor de Caras y Zona de Corte](#2-extractor-de-caras-y-zona-de-corte)
3. [Extractor de Camisetas, Campo / Portero (GK) / Staff y #ID de Clubes](#3-extractor-de-camisetas-campo--portero-gk--staff-y-id-de-clubes)
4. [Sincronizador NG_Regens, FM27 y OneDrive](#4-sincronizador-ng_regens-fm27-y-onedrive)

---

## 1. Captura en Caliente, Montaje Paso a Paso, DF11 Pure / Dual y Packs de Faces FM

### ¿Dónde encuentro y cómo uso la exportación en DF11 Pure (`220 × 276` sin marco) y el modo Dual a dos carpetas a la vez?
* **Dónde encontrar los botones (3 accesos directos):** 1) Directamente en el **`Paso 1 · Capa Cara y Cuello`** en la fila **`Formato de modelo DF11`** (**`Classic 260×310`**, **`Pure 220×276`** o **`Dual (Ambas)`**); 2) En la cabecera superior del **`Lienzo Oficial DF11`** (**`Classic | DF11 Pure | Dual`**); y 3) En la pestaña **`Sincronizador NG_Regens`** para sincronizar lotes completos.
* **Carpetas independientes y conmutador de vista en vivo:** En modo **`Dual (Ambas)`** aparecen dos botones separados de carpeta (uno para **Classic** y otro para **Pure**, tanto en **`1. Nuestras creaciones`** como en **`2. Pack de Faces FM`**) y bajo el lienzo puedes alternar entre **`Vista Classic`** y **`Vista Pure`** antes de guardar.
* **Limpieza de contorno 100% gratuita y sin IA (ni siquiera la primera vez):** Cuando usas **`Foto Directa + Marco DF11`**, conviertes tarjetas existentes con **`Ficha → Pure`** o sincronizas lotes sin equipación de club, un algoritmo óptico determinista limpia al instante el contorno del futbolista sobre fondos suaves, de estudio o viñetas sin invocar inteligencia artificial en ningún momento. En fotos con iluminación compleja dispones además del deslizador **`Contorno Pure`** (`0%–100%`) y reimportación `1:1` sin pérdida.
* **Aviso de prioridad en `graphics/` de Football Manager:** Si en modo Dual apuntas ambas carpetas dentro del árbol activo `graphics/` de Football Manager, la app muestra un aviso preventivo recordando que el juego resuelve el mismo `#ID` por orden alfabético de carpetas.

### ¿Cómo funciona «Capturar» en 2 pasos (Seleccionar → Reencuadrar → Intro / Esc) sin tapar tu pantalla ni borrar el #ID copiado?
* **Flujo cómodo en 2 pasos (`Seleccionar → Reencuadrar → Intro / Esc`):** Al pulsar **`Capturar`** o el atajo global **`Ctrl+Shift+X`**, la ventana de la aplicación se oculta automáticamente. Arrastra con el botón izquierdo del ratón y suelta: el recuadro queda enmarcado en pantalla con 4 escuadras esmeralda sin regresar todavía a la aplicación. Si quieres ajustar la selección, vuelve a arrastrar manteniendo el botón izquierdo del ratón para dibujar un nuevo recorte que reemplaza al anterior; pulsa **`Intro`** (`Enter`) para confirmar y llevar la imagen a la app o **`Esc`** para cancelar tranquilamente con una sola mano.
* **Menú `Capturar ▾` y conservación del portapapeles:** En el menú desplegable de **`Capturar ▾`** puedes lanzar directamente **`Foto Directa + Marco DF11`** (fondo original), **`Foto Directa · Capa Blanca DF11`**, **`Recortar Cara`**, **`Extraer Camiseta`** o **`Guardar PNG como…`**, conservando siempre intacto cualquier `#ID` de Football Manager copiado con `Ctrl+C`.
* **Proporción DF11 con `Shift`, aviso de baja resolución y `Ctrl+V` seguro:** Mantén pulsado **`Shift`** al arrastrar para fijar la proporción oficial `260 × 310 px` (con aviso preventivo si el recorte mide menos de `150 px`) y pega imágenes con **`Ctrl+V`** en cualquiera de las tres herramientas sin interferir cuando estés escribiendo en cuadros de texto o números.
* **Vídeos en negro por protección del navegador:** Si al capturar un vídeo en pausa aparece un recuadro negro, desactiva *«Usar aceleración por hardware cuando esté disponible»* en los ajustes de tu navegador.

### ¿Cómo creo una ficha rápida con Foto Directa + Marco DF11 (Fondo original vs Capa Blanca DF11, 4 puntos cardinales y Zoom)?
* **Formato directo con `Fondo original` o `Capa Blanca DF11` en el Paso 1:** En el Paso 1 pulsa **`Foto Directa + Marco DF11`** y sube, captura o pega cualquier foto para aplicarle el marco biselado oficial DF11 (`260 × 310 px`). En **`Fondo Classic`** puedes alternar con un clic entre **`Fondo original`** (conserva el fondo que ya viene en tu captura) y **`Capa Blanca DF11`** (sustituye fondos suaves o de estudio por el blanco degradado oficial DF11), sin necesitar ningún paso intermedio de fondo.
* **Movimiento en los 4 puntos cardinales y Zoom con pivote central:** Desplaza la imagen en los 4 puntos cardinales mediante los botones **`↑ N`**, **`↓ S`**, **`← O`**, **`→ E`** (`0,0` para centrar), arrastrando con el ratón o con las flechas del teclado (`←` `↑` `↓` `→`, o `Shift` para mayor paso), y aumenta o disminuye por **`Zoom`** (`35%–300%`) con la rueda, la barra, el cuadro numérico exacto o las dos flechas arriba/abajo.
* **Ajustar a bordes, rescate desde Zona de corte y alternancia libre:** Con **`Ajustar a bordes`** activo evitas dejar franjas vacías, con **`Foto Directa`** rescatas sin pérdida cualquier captura tomada desde la Zona de corte, y puedes alternar en cualquier momento con **`Modo Capas (Cara + Camiseta)`** conservando intacto el encuadre de cada modo.

### ¿Cómo funciona «Calidad óptica» en el Paso 3 para mejorar la imagen final sin IA?
* **Procesamiento 100% offline y 0% IA:** En el Paso 3 (`Marco Maestro DF11 y Exportación`) regula **`Calidad óptica`** (`0%` a `100%`) con barra deslizante, número exacto o flechas arriba/abajo; emplea óptica matemática pura en local sin redes neuronales ni conexión a internet.
* **Nitidez real sin alterar rasgos:** Limpia bloques de compresión JPEG y realza micro-detalles en ojos, cabello y escudos sin halos blancos, protegiendo la textura natural de la piel y los colores intensos de las equipaciones.

### ¿Cómo funciona el Modo Capas en el Paso 1 (ratón, flechas, Zoom, Cuello cilíndrico y borrado de caras de prueba)?
* **Movimiento con ratón y flechas del teclado:** Con el Paso 1 seleccionado (`Activo · N/S/E/O, Ratón o ←↑↓→`), arrastra la cabeza con el ratón sobre el lienzo `260 × 310 px` o muévela píxel a píxel con las teclas direccionales `←` `↑` `↓` `→` (mantén `Shift` para saltos rápidos de `5 px`).
* **Zoom y Cuello cilíndrico con cuadro numérico y flechas arriba/abajo:** Tanto en `Zoom` (`15%–220%`) como en `Cuello` (`0%–150%`) dispones de barra deslizante, cuadro de texto numérico exacto y dos flechas situadas inmediatamente a su derecha (`+1%` / `-1%`). Al elevar la cabeza respecto de la camiseta, el motor alarga únicamente el **cuello cilíndrico anatómico** sin estirar verticalmente los trapecios, y con `Cuello` regulas su anchura para encajar en cualquier escote.
* **Eliminación rápida de caras guardadas o de prueba:** En la tira **`Usar cara guardada`** del Paso 1 o en la **`Biblioteca de Caras`** de `Recortar Cara`, pulsa el icono de papelera (**`🗑️`**) y confirma **`Borrar`** (o haz `Shift+Clic` para borrado directo, o usa **`Limpiar prueba (N)`** para vaciar todas las de muestra de una vez), conservando siempre `Ctrl+Z` si estaba en el lienzo.

### ¿Cómo edito una ficha ya montada de mi Pack de Faces de FM o guardo con su número original?
* **Edición y conversión directa de fichas de Facepacks:** En el Paso 1 pulsa **`Cambiar camiseta a ficha FM`** para extraer limpiamente la cabeza y cuello del futbolista sobre cualquiera de tus plantillas, **`Cambiar cara (conservar su camiseta)`** para aislar la equipación exacta de esa tarjeta en memoria, o **`Ficha → Pure`** para quitar matemáticamente el bisel de cualquier tarjeta DF11 Classic (`260 × 310 px`) y convertirla al instante en DF11 Pure (`220 × 276 px`). Si el archivo se llama `<ID>.png`, el número del futbolista se rellena solo.
* **Doble destino en el Paso 3:** Elige **`1. Nuestras creaciones`** para guardar en tu carpeta personal (`PNG Oficial` o `JPG`) **sin necesidad de indicar ningún `#ID` oficial de Football Manager** (puedes dejar el cuadro vacío para guardado automático o escribir cualquier nombre libre), o **`2. Pack de Faces FM`** para seleccionar la carpeta gráfica oficial de caras de Football Manager y guardar el archivo con su `<ID>.png` obligatorio actualizando `config.xml` de forma segura.

---

## 2. Extractor de Caras y Zona de Corte

### ¿Cómo evito cortar cabezas o pelos al subir una imagen nueva?
* **Zona de corte previa con rueda y flechas:** Tanto al subir en el lienzo como en `Extraer Cara`, la rueda del ratón acerca o aleja la zona de corte y las flechas o el ratón ajustan el encuadre antes de extraer.
* **Aviso de tope de cabeza:** Si el pelo supera la línea segura superior, aparece un aviso ámbar con el botón `Auto-proteger` y el corte solo se ejecuta al pulsar `Aplicar zona de corte`.
* **Engrosamiento natural de cuello:** Si una cara recortada tiene cuello estrecho o corto, regula `Cuello` (`0%` a `150%`) para ensanchar y prolongar la piel suavemente hasta dentro del escote de la camiseta.

---

## 3. Extractor de Camisetas, Campo / Portero (GK) / Staff y #ID de Clubes

### ¿Cómo extraigo camisetas de Campo, de Portero (GK) o trajes de Staff con máxima nitidez?
* **Clasificación `Campo`, `Portero (GK)` o `Staff` al extraer:** En `Extraer Camiseta`, selecciona en **`Destino en Paso 2 (Montaje)`** si la prenda pertenece a **`Campo`** (jugadores de campo, por defecto), **`Portero (GK)`** (guardametas) o **`Staff`** (polos, chaquetas o trajes de cuerpo técnico). En el Paso 2 verás esas tres pestañas reales de alta calidad.
* **Motor 2× SSAA y Nitidez textil:** Ajusta posición y tamaño en el lienzo con `Deshacer / Rehacer`, regula `Nitidez textil` para realzar escudos, marcas y ribetes de cuello y pulsa `Extraer solo la camiseta` (`~30-45 KB`).
* **Hombros limpios en blancas y oscuras:** `Simetrizar hombros` + `Refuerzo hombro` completan hombros blancos sobre fondo blanco sin contaminar mangas oscuras.

### ¿Cómo conviven camisetas de Campo y de Portero (GK) por temporada, conozco el #ID de cada club o elimino las que no uso?
* **Convivencia por club, temporada y rol (`Campo` / `Portero GK` / `Staff`):** Dentro de un mismo club y temporada (ej. `2026/27`) pueden convivir simultáneamente `1 ★ Titular activa` de `Campo`, `1 ★ Titular activa` de `Portero (GK)` y `1 ★ Titular activa` de `Staff` sin sobrescribirse entre sí; por defecto la asignación automática del club viste siempre la de `Campo`.
* **Cómo ver el #ID en Football Manager:** En el juego abre `Preferencias -> Interfaz` y activa *«Mostrar ID de pantalla en la barra de título para ayudar con la apariencia»* (ej. `1744` Rayo Vallecano, `1736` Real Madrid). También puedes pulsar `Importar #IDs FM` sobre tu carpeta `graphics` o escribir cualquier `#ID` numérico y nombre de club.
* **Buscador y eliminación rápida en Paso 2 y Biblioteca:** Filtra por nombre, club, `#ID`, rol (`Campo` / `Portero` / `Staff`) o temporada y elimina cualquier camiseta de prueba pulsando el icono de papelera (**`🗑️`**) y confirmando **`Borrar`** (o `Shift+Clic` para borrado directo) desde las tarjetas del Paso 2 o desde `Extraer Camiseta`.

---

## 4. Sincronizador NG_Regens, FM27 y OneDrive

### ¿Cómo sincronizo miles de caras creadas con NG_Regens en formato Classic, Pure o Dual sin dañar mis archivos?
* **Modo no destructivo:** Apunta NG_Regens a `D:\DF11Studio\NG_Regens_Vault`; la app lee la bóveda sin renombrar ni alterar su `config.xml` original.
* **Formatos Classic, Pure o Dual en carpetas independientes:** Elige **`Classic 260×310`** (`000_DF11_Regens_Override`), **`Pure 220×276`** (`000_DF11_Pure_Override`) o **`Dual (Ambas)`** para sincronizar una o las dos variantes a la vez vistiendo la camiseta `★ Titular activa` de `Campo` de cada `#ID` de club y manteniendo cada `config.xml` sincronizado.
* **Actualización en caliente y Shrink Guard:** Activa `Live Disk Sync (650ms)` en `Sincronizador NG_Regens` para convertir solo los regens nuevos y cuenta con detención automática si la bóveda pierde más del `50%` de caras por accidente.

### ¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?
* **Steam y Epic Games:** Copia el parámetro `--user_data_location="D:\FM27 Data"` desde el aviso superior y pégalo en Parámetros de lanzamiento del juego.
* **Xbox / Microsoft Store Game Pass:** En Game Pass ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca `Sports Interactive`.

### ¿Cómo reviso la Salud de la Arquitectura (GPU, modelos y base local) y la conexión entre nodos?
* **Acceso desde `Acerca de` (icono `ⓘ`):** Pulsa el botón de información **`ⓘ`** en la esquina superior derecha de la ventana y haz clic en **`Inspeccionar Salud de la Arquitectura`**.
* **Estado en tiempo real y botón de recarga:** En la cabecera del visor comprobarás si la aceleración por tarjeta gráfica está activa, los 3 modelos locales y la rapidez de lectura del catálogo, pudiendo volver a medirlos al instante con el botón **`🔄`**.
* **Mapa Topológico y Rutas de Flujo:** Haz clic sobre cualquier nodo del mapa interactivo, sobre las etiquetas inferiores o sobre las tarjetas **`Conexiones Directas`** (`← Origen` / `→ Destino`) para inspeccionar cómo se conectan los componentes, o cambia a **`Rutas de Flujo`** para seguir paso a paso cada función.
