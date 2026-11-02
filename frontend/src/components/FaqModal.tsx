import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, HelpCircle, Search, X } from 'lucide-react';

export interface FAQItem { id: string; question: string; bullets: string[]; tags?: string[]; badge?: string; }
export interface FAQSection { id: string; title: string; description: string; items: FAQItem[]; }

const SECTIONS: FAQSection[] = [
  {
    id: 'studio',
    title: 'Estudio DF11 de 3 Capas',
    description: 'Creación rápida de futbolistas y staff en 260 × 310 px.',
    items: [
      {
        id: 'layers',
        question: '¿Cómo funcionan las 3 capas para crear un futbolista o miembro del staff?',
        badge: 'Esencial',
        tags: ['capas', 'ctrl+v', 'marco', 'bokeh'],
        bullets: [
          'Capa 3 (Marco Maestro DF11): Mantiene fijo el bisel simétrico y el anillo transparente oficial de 260 × 310 px.',
          'Capa 2 (Persona): Arrastra una foto, pulsa Subir retrato o pega con Ctrl+V para recortar el fondo localmente.',
          'Capa 1 (Fondo Opcional): Elige transparente, blanco DF11, fondos con bokeh o extrae el fondo limpio de tu foto.',
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
    id: 'kits',
    title: 'Equipaciones de Club y Staff',
    description: 'Colores auténticos de camiseta, polo técnico y traje.',
    items: [
      {
        id: 'kit-fidelity',
        question: '¿Cómo evita la app que queden logotipos antiguos o colores falsos en la camiseta?',
        badge: 'Calidad 10/10',
        tags: ['camiseta', 'escudo', 'pelo', 'barba', 'club'],
        bullets: [
          'Sustitución limpia: Al elegir Club, Polo Staff o Traje Staff, la ropa callejera anterior se elimina al 100%.',
          'Colores reales: Prioriza tus packs 2D instalados o la base curada de clubes reales; el escudo solo se estampa como insignia.',
          'Respeto anatómico: El pelo largo, la barba y las gafas quedan siempre por delante del cuello.',
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
          'Actualización en caliente: Activa Live Disk Sync (650ms) para convertir solo los regens nuevos.',
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
    <div className="fixed inset-0 z-50 bg-slate-950/60 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-5xl max-h-[86vh] rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-[#111827] text-slate-900 dark:text-slate-100 flex flex-col overflow-hidden">
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
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar dudas, atajos o funciones..." className="w-full pl-8 pr-3 py-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100" />
            </div>
            <div className="flex flex-wrap md:flex-col gap-1.5 text-xs">
              <button type="button" onClick={() => setActiveSec('all')} className={`min-h-[40px] px-3 py-2 rounded-lg text-left font-medium ${activeSec === 'all' ? 'bg-emerald-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>Todas las secciones ({allItemIds.length})</button>
              {SECTIONS.map((s) => (
                <button key={s.id} type="button" onClick={() => setActiveSec(s.id)} className={`min-h-[40px] px-3 py-2 rounded-lg text-left font-medium ${activeSec === s.id ? 'bg-emerald-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>
                  {s.title} ({s.items.length})
                </button>
              ))}
            </div>
          </aside>

          <div className="md:col-span-8 p-5 space-y-5 max-w-3xl">
            {filtered.map((sec) => (
              <div key={sec.id} className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">{sec.title}</h3>
                <div className="divide-y divide-slate-200 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-lg">
                  {sec.items.map((it) => {
                    const isOpen = Boolean(qNorm) || Boolean(openIds[it.id]);
                    return (
                      <div key={it.id} className="p-3.5 text-xs">
                        <button type="button" onClick={() => setOpenIds((p) => ({ ...p, [it.id]: !isOpen }))} className="w-full min-h-[36px] flex items-center justify-between gap-2 text-left font-semibold text-slate-900 dark:text-slate-100">
                          <span>{it.question}</span>
                          <span className="inline-flex items-center gap-1.5 shrink-0">
                            {it.badge && <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 text-[11px]">{it.badge}</span>}
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
