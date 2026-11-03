import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, HelpCircle, Search, X } from 'lucide-react';

export interface FAQItem { id: string; question: string; bullets: string[]; tags?: string[]; badge?: string; }
export interface FAQSection { id: string; title: string; description: string; items: FAQItem[]; }

const SECTIONS: FAQSection[] = [
  {
    id: 'studio',
    title: 'Montaje Paso a Paso en 4 Capas',
    description: 'Lienzo DF11 con rueda, Deshacer/Rehacer y tecla Suprimir.',
    items: [
      {
        id: 'layers',
        question: '¿Cómo funciona el montaje paso a paso y los atajos del Lienzo Oficial DF11?',
        badge: 'Novedad',
        tags: ['capas', 'ctrl+z', 'ctrl+y', 'suprimir', 'paso', 'lienzo'],
        bullets: [
          'Clic central con memoria de carpeta: Pulsa en el centro vacío del lienzo 260 × 310 px o en Subir retrato para abrir tu última carpeta usada.',
          'Orden en 4 pasos: Paso 1 (Cara y Cuello), Paso 2 (Camiseta Plantilla con buscador o Club/Staff), Paso 3 (Fondo por defecto Blanco Estudio DF11) y Paso 4 (Exportación).',
          'Deshacer, Rehacer y Suprimir: Usa los botones superiores o los atajos Ctrl+Z, Ctrl+Y y Supr para limpiar o recuperar cualquier edición.',
        ],
      },
      {
        id: 'formats',
        question: '¿En qué formato debo exportar mis fichas para Football Manager?',
        tags: ['png', 'jpg', 'config.xml'],
        bullets: [
          'PNG Oficial (Recomendado): Conserva el anillo transparente exterior y actualiza config.xml automáticamente.',
          'JPG Ligero: Aplana la tarjeta sobre blanco puro a máxima nitidez para compartirla fuera del juego.',
        ],
      },
    ],
  },
  {
    id: 'face-extractor',
    title: 'Extractor de Caras y Zona de Corte',
    description: 'Encuadre previo con rueda del ratón y relleno natural de cuello.',
    items: [
      {
        id: 'wheel-crop',
        question: '¿Cómo evito cortar cabezas o pelos al subir una imagen nueva?',
        badge: 'Esencial',
        tags: ['rueda', 'corte', 'cabeza', 'pelo', 'cuello', 'extraer cara'],
        bullets: [
          'Zona de corte previa con rueda: Acerca o aleja con la rueda del ratón y arrastra la imagen antes de pulsar Aplicar zona de corte.',
          'Aviso de tope de cabeza: Si el pelo toca el margen superior, verás un aviso con el botón Auto-proteger.',
          'Relleno natural de cuello: Ajusta el deslizador Cuello para prolongar la piel suavemente hasta dentro del cuello de la camiseta.',
        ],
      },
    ],
  },
  {
    id: 'shirt-extractor',
    title: 'Extractor de Camisetas, #ID y Temporadas',
    description: 'Extracción nítida 2× SSAA, buscador, #ID de club FM y temporadas.',
    items: [
      {
        id: 'white-shirts',
        question: '¿Cómo convierto cualquier imagen (incluidas camisetas blancas) en plantilla nítida?',
        badge: 'Calidad 2× SSAA',
        tags: ['camiseta', 'blanca', 'hombros', 'tshirt_templates', 'nitidez', 'plantilla'],
        bullets: [
          'Encuadre previo sobre el lienzo: Al subir una imagen en Extraer Camiseta, ajústala en tamaño (rueda o deslizador Tamaño) y posición con Deshacer y Rehacer (Ctrl+Z / Ctrl+Y).',
          'Nitidez textil y cuellos limpios: Regula Nitidez textil para realzar escudos, marcas y ribetes de cuello y pulsa «Extraer solo la camiseta».',
          'Hombros completos sin halos: Simetrizar hombros y Refuerzo hombro reconstruyen camisetas blancas sin contaminar mangas oscuras.',
        ],
      },
      {
        id: 'club-ids-seasons',
        question: '¿Cómo conozco el #ID de cada club, busco camisetas o actualizo temporadas?',
        badge: 'Novedad',
        tags: ['id', 'club', 'temporada', 'buscar', 'eliminar', 'borrar', 'graphics', 'activa'],
        bullets: [
          'Cómo ver el #ID en Football Manager: En Preferencias -> Interfaz activa «Mostrar ID de pantalla en la barra de título», pulsa Importar #IDs FM sobre tu carpeta graphics o escribe cualquier #ID numérico y nombre.',
          'Historial por temporadas: Añade la temporada (ej. 2026/27) y marca ★ Camiseta Titular Activa para actualizar la equipación del club conservando temporadas previas (o pulsa Activar para alternarlas).',
          'Buscador y eliminación: Filtra tus plantillas por nombre, club, #ID o temporada y usa los botones de editar o papelera (Borrar) para gestionar tshirt_templates.',
        ],
      },
    ],
  },
  {
    id: 'sync',
    title: 'Sincronizador NG_Regens y FM27',
    description: 'Conversión por lotes sin tocar tu bóveda y guía OneDrive.',
    items: [
      {
        id: 'ng-vault',
        question: '¿Cómo sincronizo miles de caras creadas con NG_Regens sin dañar mis archivos?',
        tags: ['ng_regens', 'live', 'shrink', 'boveda'],
        bullets: [
          'Modo no destructivo: Apunta NG_Regens a D:\\DF11Studio\\NG_Regens_Vault; su config.xml nunca se renombra.',
          'Actualización en caliente: Activa Live Disk Sync (650ms) para convertir solo los regens nuevos aplicando la camiseta ★ Titular activa de cada #ID de club.',
          'Protección Shrink Guard: Si tu bóveda pierde más del 50% de caras por error, la sincronización se detiene antes de borrar salidas previas.',
        ],
      },
      {
        id: 'onedrive-fm27',
        question: '¿Cómo evito que OneDrive llene mi disco C: con gráficos de Football Manager 2027?',
        badge: 'Crítico',
        tags: ['onedrive', 'steam', 'epic', 'game pass', 'disco'],
        bullets: [
          'Steam y Epic Games: Usa el parámetro --user_data_location="D:\\FM27 Data" en Parámetros de lanzamiento.',
          'Xbox / Microsoft Store Game Pass: Ese parámetro no está soportado por SEGA; abre Ajustes de OneDrive -> Elegir carpetas y desmarca Sports Interactive.',
        ],
      },
    ],
  },
];

export default function FaqModal({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [activeSec, setActiveSec] = useState<string>('all');
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({ layers: true });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const qNorm = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    return SECTIONS.filter((s) => activeSec === 'all' || s.id === activeSec)
      .map((s) => ({
        ...s,
        items: s.items.filter((it) => !qNorm || it.question.toLowerCase().includes(qNorm) || it.bullets.some((b) => b.toLowerCase().includes(qNorm)) || it.tags?.some((t) => t.toLowerCase().includes(qNorm))),
      }))
      .filter((s) => s.items.length > 0);
  }, [activeSec, qNorm]);

  const allItemIds = SECTIONS.flatMap((s) => s.items.map((i) => i.id));
  const setAllOpen = (val: boolean) => setOpenIds(Object.fromEntries(allItemIds.map((id) => [id, val])));

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-5xl max-h-[86vh] rounded-xl shadow-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-white flex flex-col overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <HelpCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" /> Centro de Ayuda &amp; FAQ
          </div>
          <div className="flex items-center gap-2 text-xs">
            <button type="button" onClick={() => setAllOpen(true)} className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Expandir todo</button>
            <button type="button" onClick={() => setAllOpen(false)} className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">Colapsar todo</button>
            <button type="button" aria-label="Cerrar ayuda" onClick={onClose} className="p-1.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto grid grid-cols-1 md:grid-cols-12">
          <aside className="md:col-span-4 p-4 border-b md:border-b-0 md:border-r border-slate-200 dark:border-slate-800 space-y-3 bg-slate-50/70 dark:bg-slate-900/40">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
              <input aria-label="Buscar en preguntas frecuentes" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar dudas, atajos o funciones..." className="w-full pl-8 pr-3 py-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100" />
            </div>
            <div className="flex flex-wrap md:flex-col gap-1.5 text-xs">
              <button type="button" onClick={() => setActiveSec('all')} className={`min-h-[44px] px-3 py-2 rounded-lg text-left font-medium ${activeSec === 'all' ? 'bg-emerald-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>Todas las secciones ({allItemIds.length})</button>
              {SECTIONS.map((s) => (
                <button key={s.id} type="button" onClick={() => setActiveSec(s.id)} className={`min-h-[44px] px-3 py-2 rounded-lg text-left font-medium ${activeSec === s.id ? 'bg-emerald-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>
                  {s.title} ({s.items.length})
                </button>
              ))}
            </div>
          </aside>

          <div className="md:col-span-8 p-5 space-y-5 max-w-3xl">
            {filtered.length === 0 ? (
              <div className="py-10 text-center space-y-2 text-xs text-slate-600 dark:text-slate-400">
                <p>Sin coincidencias para <strong className="text-slate-900 dark:text-white">“{query}”</strong>.</p>
                <button type="button" onClick={() => { setQuery(''); setActiveSec('all'); }} className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-medium">Limpiar búsqueda</button>
              </div>
            ) : filtered.map((sec) => (
              <div key={sec.id} className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">{sec.title}</h3>
                <div className="divide-y divide-slate-200 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-lg">
                  {sec.items.map((it) => {
                    const isOpen = Boolean(qNorm) || Boolean(openIds[it.id]);
                    return (
                      <div key={it.id} className="p-3.5 text-xs">
                        <button type="button" aria-expanded={isOpen} onClick={() => setOpenIds((p) => ({ ...p, [it.id]: !isOpen }))} className="w-full min-h-[44px] flex items-center justify-between gap-2 text-left font-semibold text-slate-900 dark:text-white">
                          <span>{it.question}</span>
                          <span className="inline-flex items-center gap-1.5 shrink-0">
                            {it.badge && <span className="px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20 text-[11px]">{it.badge}</span>}
                            {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          </span>
                        </button>
                        {isOpen && (
                          <ul className="mt-2 space-y-1.5 pl-4 list-disc text-slate-600 dark:text-slate-300 leading-relaxed">
                            {it.bullets.map((b, i) => <li key={i}>{b}</li>)}
                          </ul>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
