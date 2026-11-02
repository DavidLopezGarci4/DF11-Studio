import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Atom, Cpu, Database, GitBranch, Layers, Monitor, Network, RefreshCw, Workflow, X } from 'lucide-react';
import stackConfig from '../config/stack.config.json';
import { callBridge } from '../lib/ipc';

interface Props { onClose: () => void }
interface Rgb { r: number; g: number; b: number }
interface HealthProbe { dmlActive: boolean; providers: string[]; sqliteLatencyMs: number }
interface NeighborEdge { peerId: string; peerLabel: string; dir: 'in' | 'out'; protocol: string }

const ICONS = { Monitor, Atom, Workflow, Cpu, Layers, Database } as const;
const hexToRgb = (hex: string): Rgb => {
  const v = parseInt(hex.replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
};

export default function AppArchitectureGraph({ onClose }: Props) {
  const [mode, setMode] = useState<'topology' | 'flows'>('topology');
  const [selectedId, setSelectedId] = useState<string>(stackConfig.nodes[0].id);
  const [flowId, setFlowId] = useState<string>(stackConfig.flows[0].id);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthProbe | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const labelMetricsCache = useRef<Map<string, number>>(new Map());

  const runHealthProbe = useCallback(async () => {
    try {
      const res = await callBridge<HealthProbe | null>('probe_architecture_health');
      if (res && typeof res.sqliteLatencyMs === 'number') setHealth(res);
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    void runHealthProbe();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, runHealthProbe]);

  const prepared = useMemo(() => {
    const n = stackConfig.nodes.length;
    const nodeMap = new Map<string, (typeof stackConfig.nodes)[number] & { rgb: Rgb; ax: number; ay: number; phase: number }>();
    stackConfig.nodes.forEach((node, idx) => {
      const a = (idx / n) * Math.PI * 2 - Math.PI / 2;
      nodeMap.set(node.id, { ...node, rgb: hexToRgb(node.color), ax: 0.5 + Math.cos(a) * 0.34, ay: 0.5 + Math.sin(a) * 0.33, phase: idx * 1.05 });
    });
    const adj = new Map<string, NeighborEdge[]>();
    stackConfig.nodes.forEach((nd) => adj.set(nd.id, []));
    stackConfig.links.forEach((lk) => {
      const s = nodeMap.get(lk.source);
      const t = nodeMap.get(lk.target);
      if (s && t) {
        adj.get(s.id)?.push({ peerId: t.id, peerLabel: t.label, dir: 'out', protocol: lk.protocol });
        adj.get(t.id)?.push({ peerId: s.id, peerLabel: s.label, dir: 'in', protocol: lk.protocol });
      }
    });
    const solidLinks = stackConfig.links.filter((l) => l.type === 'jerarquia');
    const dashedLinks = stackConfig.links.filter((l) => l.type !== 'jerarquia');
    return { nodeMap, adj, solidLinks, dashedLinks };
  }, []);

  const activeFlow = useMemo(() => stackConfig.flows.find((f) => f.id === flowId) ?? stackConfig.flows[0], [flowId]);
  const selectedNode = prepared.nodeMap.get(selectedId) ?? Array.from(prepared.nodeMap.values())[0];
  const nodeStatus = (ht: string) => (ht === 'static' ? 'static' : !health ? (ht === 'runtime' ? 'healthy' : 'static') : ht === 'hardware' ? (health.dmlActive ? 'healthy' : 'degraded') : ht === 'storage' ? (health.sqliteLatencyMs < 50 ? 'healthy' : 'degraded') : 'healthy');

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext?.('2d');
    if (!canvas || !ctx) return undefined;
    let raf = 0;
    const start = performance.now();
    const posOf = (id: string, w: number, h: number, t: number) => {
      const nd = prepared.nodeMap.get(id)!;
      return { x: nd.ax * w + Math.cos(t * 0.9 + nd.phase) * 4, y: nd.ay * h + Math.sin(t * 0.9 + nd.phase) * 4 };
    };
    const strokeBatch = (links: typeof stackConfig.links, dash: number[], bend: number, w: number, h: number, t: number) => {
      ctx.setLineDash(dash);
      ctx.beginPath();
      links.forEach((lk) => {
        const p1 = posOf(lk.source, w, h, t);
        const p2 = posOf(lk.target, w, h, t);
        ctx.moveTo(p1.x, p1.y);
        ctx.quadraticCurveTo((p1.x + p2.x) * 0.5, (p1.y + p2.y) * 0.5 + bend, p2.x, p2.y);
      });
      ctx.stroke();
    };

    const draw = (now: number) => {
      if (!document.hidden) {
        const { width: w, height: h } = canvas;
        const elapsed = (now - start) / 1000;
        ctx.fillStyle = '#080c14';
        ctx.fillRect(0, 0, w, h);
        const flowSteps = mode === 'flows' ? activeFlow.steps.map((s) => s.nodeId) : [];

        ctx.lineWidth = 1.25;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.22)';
        strokeBatch(prepared.solidLinks, [], -16, w, h, elapsed);
        strokeBatch(prepared.dashedLinks, [4, 4], 16, w, h, elapsed);
        ctx.setLineDash([]);

        const activePairs = mode === 'topology'
          ? stackConfig.links.filter((l) => l.source === selectedId || l.target === selectedId).map((l) => ({ s: l.source, t: l.target, rgb: prepared.nodeMap.get(l.source)!.rgb }))
          : flowSteps.slice(0, -1).map((s, i) => ({ s, t: flowSteps[i + 1], rgb: { r: 16, g: 185, b: 129 } }));

        activePairs.forEach(({ s, t, rgb }, idx) => {
          const p1 = posOf(s, w, h, elapsed);
          const p2 = posOf(t, w, h, elapsed);
          ctx.strokeStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.85)`;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
          const u = (elapsed * 0.55 + idx * 0.23) % 1;
          ctx.fillStyle = '#f8fafc';
          ctx.beginPath();
          ctx.arc(p1.x + (p2.x - p1.x) * u, p1.y + (p2.y - p1.y) * u, 3, 0, Math.PI * 2);
          ctx.fill();
        });

        ctx.font = '600 11px Inter, system-ui, sans-serif';
        prepared.nodeMap.forEach((nd) => {
          const { x, y } = posOf(nd.id, w, h, elapsed);
          const stepIdx = flowSteps.indexOf(nd.id);
          const hi = mode === 'topology' ? nd.id === selectedId || nd.id === hoveredId : stepIdx !== -1;
          const r = 16 * (nd.id === hoveredId || nd.id === selectedId ? 1.35 : 1.0);
          const grad = ctx.createRadialGradient(x, y, r * 0.2, x, y, r * 2.1);
          grad.addColorStop(0, `rgba(${nd.rgb.r}, ${nd.rgb.g}, ${nd.rgb.b}, ${hi ? 0.55 : 0.2})`);
          grad.addColorStop(1, `rgba(${nd.rgb.r}, ${nd.rgb.g}, ${nd.rgb.b}, 0)`);
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(x, y, r * 2.1, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = hi ? nd.color : `rgba(${nd.rgb.r}, ${nd.rgb.g}, ${nd.rgb.b}, 0.45)`;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();
          if (mode === 'flows' && stepIdx !== -1) {
            ctx.fillStyle = '#080c14';
            ctx.fillText(String(stepIdx + 1), x - 3.5, y + 4);
          }
          let tw = labelMetricsCache.current.get(nd.label);
          if (tw === undefined) {
            tw = ctx.measureText(nd.label).width;
            labelMetricsCache.current.set(nd.label, tw);
          }
          ctx.fillStyle = hi ? '#f8fafc' : '#94a3b8';
          ctx.fillText(nd.label, x - tw * 0.5, y + r + 15);
        });
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [activeFlow, hoveredId, mode, prepared, selectedId]);

  const handleCanvasPointer = (click: boolean) => (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * canvas.width;
    const my = ((e.clientY - rect.top) / rect.height) * canvas.height;
    let hit: string | null = null;
    prepared.nodeMap.forEach((nd) => {
      if ((nd.ax * canvas.width - mx) ** 2 + (nd.ay * canvas.height - my) ** 2 <= 784) hit = nd.id;
    });
    if (click && hit) setSelectedId(hit);
    else if (!click) setHoveredId(hit);
  };

  const IconComp = ICONS[selectedNode.icon as keyof typeof ICONS] ?? Cpu;
  const st = nodeStatus(selectedNode.healthType);
  const neighbors = prepared.adj.get(selectedNode.id) ?? [];

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} className="fixed inset-0 z-50 bg-slate-950/70 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-5xl max-h-[88vh] rounded-xl shadow-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-white flex flex-col overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Network className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h2 className="font-semibold text-sm">Topología TecnoRed & Salud del Sistema</h2>
            <div className="flex items-center gap-1 p-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs">
              <button type="button" onClick={() => setMode('topology')} className={`px-2.5 py-1 rounded-md ${mode === 'topology' ? 'bg-white dark:bg-slate-900 font-medium' : 'text-slate-600 dark:text-slate-400'}`}>Mapa Topológico</button>
              <button type="button" onClick={() => setMode('flows')} className={`px-2.5 py-1 rounded-md ${mode === 'flows' ? 'bg-white dark:bg-slate-900 font-medium' : 'text-slate-600 dark:text-slate-400'}`}>Rutas de Flujo</button>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded bg-slate-100 dark:bg-slate-800 tabular-nums">
              {health ? `${health.dmlActive ? '🟢 DirectML GPU' : '🟡 CPU Fallback'} · SQLite ${health.sqliteLatencyMs} ms` : '⚪ Telemetría pasiva'}
            </span>
            <button type="button" onClick={() => void runHealthProbe()} aria-label="Reejecutar sonda de salud" className="p-1.5 rounded bg-slate-100 dark:bg-slate-800"><RefreshCw className="w-3.5 h-3.5" /></button>
            <button type="button" onClick={onClose} aria-label="Cerrar grafo de arquitectura" className="p-1.5 rounded bg-slate-100 dark:bg-slate-800"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_360px] min-h-0 overflow-y-auto">
          <div className="bg-[#080c14] p-4 flex flex-col justify-between">
            {mode === 'flows' && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {stackConfig.flows.map((fl) => (
                  <button key={fl.id} type="button" onClick={() => setFlowId(fl.id)} className={`px-2.5 py-1 rounded text-xs transition ${flowId === fl.id ? 'bg-emerald-500 text-slate-950 font-semibold' : 'bg-slate-900 text-slate-300 border border-slate-800'}`}>{fl.title}</button>
                ))}
              </div>
            )}
            <canvas ref={canvasRef} width={580} height={360} onClick={handleCanvasPointer(true)} onMouseMove={handleCanvasPointer(false)} className="w-full h-auto rounded-lg cursor-pointer" />
            <div className="flex flex-wrap gap-1.5 mt-3">
              {stackConfig.nodes.map((nd) => (
                <button key={nd.id} type="button" onClick={() => setSelectedId(nd.id)} className={`px-2 py-1 rounded text-[11px] border ${selectedId === nd.id ? 'border-emerald-400 bg-slate-900 text-white' : 'border-slate-800 bg-slate-900/60 text-slate-400'}`}>{nd.label}</button>
              ))}
            </div>
          </div>

          <aside className="p-4 border-t lg:border-t-0 lg:border-l border-slate-200 dark:border-slate-800 space-y-3 text-xs overflow-y-auto">
            {mode === 'flows' ? (
              <div className="space-y-2.5">
                <div className="font-semibold text-sm flex items-center gap-1.5"><GitBranch className="w-4 h-4 text-emerald-600 dark:text-emerald-400" /> {activeFlow.title}</div>
                <p className="text-slate-600 dark:text-slate-300 leading-relaxed">{activeFlow.explanation}</p>
                <ol className="space-y-2 pt-1">
                  {activeFlow.steps.map((stStep, i) => (
                    <li key={stStep.nodeId} className="p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50">
                      <button type="button" onClick={() => { setSelectedId(stStep.nodeId); setMode('topology'); }} className="font-semibold text-emerald-700 dark:text-emerald-400 hover:underline">Paso {i + 1} · {prepared.nodeMap.get(stStep.nodeId)?.label}</button>
                      <p className="text-slate-600 dark:text-slate-400 mt-0.5">{stStep.role}</p>
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <IconComp className="w-4 h-4 shrink-0" style={{ color: selectedNode.color }} />
                    <div>
                      <h3 className="font-semibold text-sm">{selectedNode.label}</h3>
                      <span className="text-[11px] text-slate-500 dark:text-slate-400">{selectedNode.role}</span>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-[11px] inline-flex items-center gap-1 shrink-0">
                    <Activity className="w-3 h-3" /> {st === 'healthy' ? '🟢 Activo' : st === 'degraded' ? '🟡 Degradado' : '⚪ Estático'}
                  </span>
                </div>
                <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 space-y-1.5">
                  <p><strong className="font-semibold">Modelo computacional:</strong> {selectedNode.computationalModel}</p>
                  <p><strong className="font-semibold">Por qué se eligió:</strong> {selectedNode.whyChosen}</p>
                  <ul className="list-disc pl-4 text-slate-600 dark:text-slate-400 space-y-0.5">
                    {selectedNode.useCases.map((u) => <li key={u}>{u}</li>)}
                  </ul>
                </div>
                <div>
                  <h4 className="font-semibold mb-1.5">Conexiones Directas (Topología)</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {neighbors.map((nb, idx) => (
                      <button key={`${nb.peerId}-${idx}`} type="button" onClick={() => setSelectedId(nb.peerId)} className="px-2 py-1 rounded border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-left hover:border-emerald-500">
                        <span className="font-medium">{nb.dir === 'in' ? '← Origen:' : '→ Destino:'} {nb.peerLabel}</span>
                        <span className="block text-[10px] text-slate-500 dark:text-slate-400">{nb.protocol}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}
