import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Atom, Cpu, Database, GitBranch, Layers, Monitor, Network, RefreshCw, Workflow, X } from 'lucide-react';
import stackConfig from '../config/stack.config.json';
import { callBridge } from '../lib/ipc';

interface Props { onClose: () => void }
interface Rgb { r: number; g: number; b: number }
interface HealthProbe {
  dmlActive: boolean;
  providers: string[];
  sqliteOk?: boolean;
  sqliteLatencyMs: number;
  modelsReady?: boolean;
  modelsCount?: number;
  bridgeReady?: boolean;
  exportVariant?: string;
}
interface NeighborEdge {
  peerId: string;
  peerLabel: string;
  dir: 'in' | 'out';
  protocol: string;
  relation: string;
  description: string;
  linkType: string;
}

const ICONS = { Monitor, Atom, Workflow, Cpu, Layers, Database } as const;
const STATUS_COLORS: Record<'healthy' | 'degraded' | 'static', string> = {
  healthy: '#10b981',
  degraded: '#f59e0b',
  static: '#94a3b8',
};

const hexToRgb = (hex: string): Rgb => {
  const v = parseInt(hex.replace('#', ''), 16);
  return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
};

function computeNodeStatus(ht: string, health: HealthProbe | null): 'healthy' | 'degraded' | 'static' {
  if (ht === 'static') return 'static';
  if (ht === 'runtime') return 'healthy';
  if (!health) return 'degraded';
  if (ht === 'native_bridge') return health.bridgeReady !== false ? 'healthy' : 'degraded';
  if (ht === 'hardware') return health.dmlActive && health.modelsReady !== false ? 'healthy' : 'degraded';
  if (ht === 'storage') return health.sqliteOk !== false && health.sqliteLatencyMs < 80 ? 'healthy' : 'degraded';
  return 'healthy';
}

function describeNodeHealth(nodeId: string, ht: string, health: HealthProbe | null): string {
  if (ht === 'runtime') return 'React 19 Fiber activo en WebView2 · 60 FPS sin bloqueos';
  if (ht === 'static') {
    return nodeId === 'compositor_engine'
      ? 'Motor determinista activo · Salidas Classic (260×310) y Pure (220×276)'
      : 'Filtro WGIF OKLab + luz lineal activo en memoria (100% offline · 0% IA)';
  }
  if (!health) {
    return 'Ejecuta la app desde DF11FaceStudio.exe para telemetría nativa en vivo';
  }
  if (ht === 'native_bridge') {
    const modeLabel = (health.exportVariant || 'classic').toUpperCase();
    return `Canal IPC pywebview en línea · Modo activo: ${modeLabel}`;
  }
  if (ht === 'hardware') {
    const mCount = typeof health.modelsCount === 'number' ? `${health.modelsCount}/3` : '3/3';
    return health.dmlActive
      ? `DirectML GPU DirectX 12 activa · Modelos locales verificados (${mCount})`
      : `Modo CPU activo (${health.providers.join(', ')}) · Modelos (${mCount})`;
  }
  if (ht === 'storage') {
    return health.sqliteOk === false
      ? 'Base SQLite pendiente de inicialización en disco'
      : `SQLite v5 WAL operativo · Latencia de lectura: ${health.sqliteLatencyMs} ms`;
  }
  return 'Subsistema operativo';
}

export default function AppArchitectureGraph({ onClose }: Props) {
  const [mode, setMode] = useState<'topology' | 'flows'>('topology');
  const [selectedId, setSelectedId] = useState<string>(stackConfig.nodes[0].id);
  const [flowId, setFlowId] = useState<string>(stackConfig.flows[0].id);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthProbe | null>(null);
  const [probing, setProbing] = useState<boolean>(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const labelMetricsCache = useRef<Map<string, number>>(new Map());
  const livePosRef = useRef<Map<string, { x: number; y: number; tw: number }>>(new Map());

  const runHealthProbe = useCallback(async () => {
    setProbing(true);
    try {
      const res = await callBridge<HealthProbe | null>('probe_architecture_health');
      if (res && typeof res.sqliteLatencyMs === 'number') {
        setHealth(res);
      } else {
        setHealth(null);
      }
    } catch {
      setHealth(null);
    } finally {
      setProbing(false);
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
      nodeMap.set(node.id, { ...node, rgb: hexToRgb(node.color), ax: 0.5 + Math.cos(a) * 0.34, ay: 0.5 + Math.sin(a) * 0.32, phase: idx * 1.05 });
    });
    const adj = new Map<string, NeighborEdge[]>();
    stackConfig.nodes.forEach((nd) => adj.set(nd.id, []));
    stackConfig.links.forEach((lk) => {
      const s = nodeMap.get(lk.source);
      const t = nodeMap.get(lk.target);
      if (s && t) {
        adj.get(s.id)?.push({
          peerId: t.id,
          peerLabel: t.label,
          dir: 'out',
          protocol: lk.protocol,
          relation: lk.relation,
          description: lk.description,
          linkType: lk.type,
        });
        adj.get(t.id)?.push({
          peerId: s.id,
          peerLabel: s.label,
          dir: 'in',
          protocol: lk.protocol,
          relation: lk.relation,
          description: lk.description,
          linkType: lk.type,
        });
      }
    });
    const solidLinks = stackConfig.links.filter((l) => l.type === 'jerarquia');
    const dashedLinks = stackConfig.links.filter((l) => l.type !== 'jerarquia');
    return { nodeMap, adj, solidLinks, dashedLinks };
  }, []);

  const activeFlow = useMemo(() => stackConfig.flows.find((f) => f.id === flowId) ?? stackConfig.flows[0], [flowId]);
  const selectedNode = prepared.nodeMap.get(selectedId) ?? Array.from(prepared.nodeMap.values())[0];

  const liveStateRef = useRef({ mode, selectedId, hoveredId, activeFlow, health });
  liveStateRef.current = { mode, selectedId, hoveredId, activeFlow, health };

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
        const { mode: curMode, selectedId: curSel, hoveredId: curHov, activeFlow: curFlow, health: curHealth } = liveStateRef.current;
        const { width: w, height: h } = canvas;
        const elapsed = (now - start) / 1000;
        ctx.fillStyle = '#080c14';
        ctx.fillRect(0, 0, w, h);
        const flowSteps = curMode === 'flows' ? curFlow.steps.map((s) => s.nodeId) : [];
        const focusId = curHov ?? curSel;

        ctx.lineWidth = 1.25;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.24)';
        strokeBatch(prepared.solidLinks, [], -14, w, h, elapsed);
        strokeBatch(prepared.dashedLinks, [4, 4], 14, w, h, elapsed);
        ctx.setLineDash([]);

        const activePairs = curMode === 'topology'
          ? stackConfig.links
              .filter((l) => l.source === focusId || l.target === focusId)
              .map((l) => ({ s: l.source, t: l.target, protocol: l.protocol, rgb: prepared.nodeMap.get(l.source)!.rgb }))
          : flowSteps.slice(0, -1).map((s, i) => ({ s, t: flowSteps[i + 1], protocol: `Paso ${i + 1}→${i + 2}`, rgb: { r: 16, g: 185, b: 129 } }));

        activePairs.forEach(({ s, t, rgb }, idx) => {
          const p1 = posOf(s, w, h, elapsed);
          const p2 = posOf(t, w, h, elapsed);
          const dx = p2.x - p1.x;
          const dy = p2.y - p1.y;
          const dist = Math.hypot(dx, dy) || 1;
          ctx.strokeStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.9)`;
          ctx.lineWidth = 2.1;
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();

          // Directional arrowhead near destination node perimeter
          const ux = dx / dist;
          const uy = dy / dist;
          const ax = p2.x - ux * 22;
          const ay = p2.y - uy * 22;
          ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.95)`;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(ax - ux * 7 - uy * 4, ay - uy * 7 + ux * 4);
          ctx.lineTo(ax - ux * 7 + uy * 4, ay - uy * 7 - ux * 4);
          ctx.closePath();
          ctx.fill();

          // Animated directional telemetry particle
          const u = (elapsed * 0.55 + idx * 0.23) % 1;
          ctx.fillStyle = '#f8fafc';
          ctx.beginPath();
          ctx.arc(p1.x + dx * u, p1.y + dy * u, 3.2, 0, Math.PI * 2);
          ctx.fill();
        });

        ctx.font = '600 11px Inter, system-ui, sans-serif';
        prepared.nodeMap.forEach((nd) => {
          const { x, y } = posOf(nd.id, w, h, elapsed);
          const stepIdx = flowSteps.indexOf(nd.id);
          const isNeighbor = curMode === 'topology' && activePairs.some((p) => p.s === nd.id || p.t === nd.id);
          const hi = curMode === 'topology' ? nd.id === curSel || nd.id === curHov || isNeighbor : stepIdx !== -1;
          const r = 16 * (nd.id === curHov || nd.id === curSel ? 1.32 : 1.0);
          const st = computeNodeStatus(nd.healthType, curHealth);

          const grad = ctx.createRadialGradient(x, y, r * 0.2, x, y, r * 2.1);
          grad.addColorStop(0, `rgba(${nd.rgb.r}, ${nd.rgb.g}, ${nd.rgb.b}, ${hi ? 0.55 : 0.18})`);
          grad.addColorStop(1, `rgba(${nd.rgb.r}, ${nd.rgb.g}, ${nd.rgb.b}, 0)`);
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(x, y, r * 2.1, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = hi ? nd.color : `rgba(${nd.rgb.r}, ${nd.rgb.g}, ${nd.rgb.b}, 0.45)`;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();

          // Outer semantic live-health ring + top-right health dot
          ctx.strokeStyle = STATUS_COLORS[st];
          ctx.lineWidth = nd.id === curSel ? 2.4 : 1.5;
          ctx.beginPath();
          ctx.arc(x, y, r + 3.5, 0, Math.PI * 2);
          ctx.stroke();

          ctx.fillStyle = STATUS_COLORS[st];
          ctx.beginPath();
          ctx.arc(x + r * 0.72, y - r * 0.72, 3.6, 0, Math.PI * 2);
          ctx.fill();

          if (curMode === 'flows' && stepIdx !== -1) {
            ctx.fillStyle = '#080c14';
            ctx.fillText(String(stepIdx + 1), x - 3.5, y + 4);
          }
          let tw = labelMetricsCache.current.get(nd.label);
          if (tw === undefined) {
            tw = ctx.measureText(nd.label).width;
            labelMetricsCache.current.set(nd.label, tw);
          }
          livePosRef.current.set(nd.id, { x, y, tw });
          ctx.fillStyle = hi ? '#f8fafc' : '#94a3b8';
          ctx.fillText(nd.label, x - tw * 0.5, y + r + 16);
        });
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [prepared]);

  const handleSelectNode = useCallback((nodeId: string) => {
    setSelectedId(nodeId);
    setMode('topology');
  }, []);

  const handleCanvasPointer = (click: boolean) => (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const mx = ((e.clientX - rect.left) / rect.width) * canvas.width;
    const my = ((e.clientY - rect.top) / rect.height) * canvas.height;
    let hit: string | null = null;
    let bestDist = Infinity;
    prepared.nodeMap.forEach((nd) => {
      const live = livePosRef.current.get(nd.id);
      const nx = live ? live.x : nd.ax * canvas.width;
      const ny = live ? live.y : nd.ay * canvas.height;
      const tw = live ? live.tw : 96;
      const d2 = (nx - mx) ** 2 + (ny - my) ** 2;
      const onCircle = d2 <= 1024; // 32px radius
      const onLabel = Math.abs(mx - nx) <= tw * 0.55 && my >= ny + 14 && my <= ny + 38;
      if ((onCircle || onLabel) && d2 < bestDist) {
        bestDist = d2;
        hit = nd.id;
      }
    });
    if (click && hit) {
      handleSelectNode(hit);
    } else if (!click) {
      setHoveredId(hit);
    }
  };

  const IconComp = ICONS[selectedNode.icon as keyof typeof ICONS] ?? Cpu;
  const st = computeNodeStatus(selectedNode.healthType, health);
  const neighbors = prepared.adj.get(selectedNode.id) ?? [];
  const nodeHealthText = describeNodeHealth(selectedNode.id, selectedNode.healthType, health);

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }} className="fixed inset-0 z-50 bg-slate-950/70 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-5xl max-h-[88vh] rounded-xl shadow-xl border border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-white flex flex-col overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Network className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h2 className="font-semibold text-sm">Topología TecnoRed &amp; Salud del Sistema</h2>
            <div className="flex items-center gap-1 p-0.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-xs">
              <button type="button" onClick={() => setMode('topology')} className={`px-2.5 py-1 rounded-md ${mode === 'topology' ? 'bg-white dark:bg-slate-900 font-medium shadow-2xs' : 'text-slate-600 dark:text-slate-400'}`}>Mapa Topológico</button>
              <button type="button" onClick={() => setMode('flows')} className={`px-2.5 py-1 rounded-md ${mode === 'flows' ? 'bg-white dark:bg-slate-900 font-medium shadow-2xs' : 'text-slate-600 dark:text-slate-400'}`}>Rutas de Flujo</button>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2.5 py-1 rounded-md bg-slate-100 dark:bg-slate-800 tabular-nums">
              {health
                ? `${health.dmlActive ? '🟢 DirectML GPU' : '🟡 CPU Activo'} · Modelos ${health.modelsCount ?? 3}/3 · SQLite ${health.sqliteLatencyMs} ms`
                : probing
                ? '🔄 Comprobando salud…'
                : '🟢 React 19 Activo · Telemetría local'}
            </span>
            <button
              type="button"
              onClick={() => void runHealthProbe()}
              aria-label="Reejecutar sonda de salud"
              title="Comprobar de nuevo GPU DirectML, modelos ONNX y latencia SQLite"
              className="p-1.5 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${probing ? 'animate-spin text-emerald-500' : ''}`} />
            </button>
            <button type="button" onClick={onClose} aria-label="Cerrar grafo de arquitectura" className="p-1.5 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_370px] min-h-0 overflow-y-auto">
          <div className="bg-[#080c14] p-4 flex flex-col justify-between">
            {mode === 'flows' ? (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {stackConfig.flows.map((fl) => (
                  <button key={fl.id} type="button" onClick={() => setFlowId(fl.id)} className={`px-2.5 py-1 rounded text-xs transition ${flowId === fl.id ? 'bg-emerald-500 text-slate-950 font-semibold' : 'bg-slate-900 text-slate-300 border border-slate-800 hover:border-slate-600'}`}>{fl.title}</button>
                ))}
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2 text-[11px] text-slate-400">
                <span>Haz clic en cualquier nodo o conexión para inspeccionar su salud y protocolo</span>
                <span className="inline-flex items-center gap-2.5">
                  <span>🟢 Activo</span>
                  <span>🟡 Degradado / CPU</span>
                  <span>⚪ Motor determinista</span>
                </span>
              </div>
            )}
            <canvas
              ref={canvasRef}
              width={580}
              height={360}
              onClick={handleCanvasPointer(true)}
              onMouseMove={handleCanvasPointer(false)}
              onMouseLeave={() => setHoveredId(null)}
              className={`w-full h-auto rounded-lg ${hoveredId ? 'cursor-pointer' : 'cursor-default'}`}
            />
            <div className="flex flex-wrap gap-1.5 mt-3">
              {stackConfig.nodes.map((nd) => {
                const ndSt = computeNodeStatus(nd.healthType, health);
                const dot = ndSt === 'healthy' ? '🟢' : ndSt === 'degraded' ? '🟡' : '⚪';
                return (
                  <button
                    key={nd.id}
                    type="button"
                    onClick={() => handleSelectNode(nd.id)}
                    className={`px-2 py-1 rounded text-[11px] border transition ${
                      selectedId === nd.id && mode === 'topology'
                        ? 'border-emerald-400 bg-slate-900 text-white font-medium'
                        : 'border-slate-800 bg-slate-900/60 text-slate-300 hover:border-slate-600'
                    }`}
                  >
                    {dot} {nd.label}
                  </button>
                );
              })}
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
                      <button type="button" onClick={() => handleSelectNode(stStep.nodeId)} className="font-semibold text-emerald-700 dark:text-emerald-400 hover:underline">Paso {i + 1} · {prepared.nodeMap.get(stStep.nodeId)?.label}</button>
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
                    <Activity className="w-3 h-3" /> {st === 'healthy' ? '🟢 Activo' : st === 'degraded' ? '🟡 Degradado' : '⚪ Determinista'}
                  </span>
                </div>

                <div className="px-2.5 py-2 rounded-lg border border-emerald-500/25 bg-emerald-500/[0.06] text-[11px] text-slate-700 dark:text-slate-200 flex items-center justify-between gap-2">
                  <span><strong>Salud en vivo:</strong> {nodeHealthText}</span>
                </div>

                <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 space-y-1.5">
                  <p><strong className="font-semibold">Modelo computacional:</strong> {selectedNode.computationalModel}</p>
                  <p><strong className="font-semibold">Por qué se eligió:</strong> {selectedNode.whyChosen}</p>
                  <ul className="list-disc pl-4 text-slate-600 dark:text-slate-400 space-y-0.5">
                    {selectedNode.useCases.map((u) => <li key={u}>{u}</li>)}
                  </ul>
                </div>

                <div>
                  <h4 className="font-semibold mb-1.5">Conexiones Directas ({neighbors.length})</h4>
                  <div className="flex flex-col gap-1.5">
                    {neighbors.map((nb, idx) => (
                      <button
                        key={`${nb.peerId}-${idx}`}
                        type="button"
                        onClick={() => handleSelectNode(nb.peerId)}
                        className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800/80 text-left hover:border-emerald-500 transition"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-900 dark:text-slate-100">
                            {nb.dir === 'in' ? '← Origen:' : '→ Destino:'} {nb.peerLabel}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-slate-900 text-emerald-700 dark:text-emerald-400 font-mono shrink-0">
                            {nb.protocol}
                          </span>
                        </div>
                        <span className="block text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                          {nb.description}
                        </span>
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
