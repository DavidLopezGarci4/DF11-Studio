import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import AboutModal from '../components/AboutModal';
import AppArchitectureGraph from '../components/AppArchitectureGraph';
import FaqModal from '../components/FaqModal';

describe('FAQ and About human metadata modals', () => {
  it('renders adaptive FAQ split-view with DF11 Pure/Dual expanded by default and auto-expands matching items on search', () => {
    render(<FaqModal onClose={() => {}} />);
    expect(screen.getByText(/Centro de Ayuda & FAQ/i)).toBeInTheDocument();
    expect(screen.getByText(/3 accesos directos/i)).toBeInTheDocument();
    const search = screen.getByPlaceholderText(/Buscar dudas/i);
    fireEvent.change(search, { target: { value: 'OneDrive' } });
    expect(screen.getByText(/Game Pass/i)).toBeInTheDocument();
    fireEvent.change(search, { target: { value: 'barra de título' } });
    expect(screen.getByText(/Importar #IDs FM/i)).toBeInTheDocument();
    fireEvent.change(search, { target: { value: 'facepack' } });
    expect(screen.getAllByText(/ficha ya montada/i).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(search, { target: { value: 'Foto Directa' } });
    expect(screen.getAllByText(/puntos cardinales/i).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(search, { target: { value: 'Calidad óptica' } });
    expect(screen.getAllByText(/100% offline/i).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(search, { target: { value: 'Capturar' } });
    expect(screen.getAllByText(/portapapeles/i).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(search, { target: { value: 'DF11 Pure' } });
    expect(screen.getAllByText(/220 × 276/i).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(search, { target: { value: 'Portero' } });
    expect(screen.getAllByText(/Portero \(GK\)/i).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(search, { target: { value: 'nodos' } });
    expect(screen.getByText(/Inspeccionar Salud de la Arquitectura/i)).toBeInTheDocument();
  });

  it('renders human-readable v1.6.1 release highlights and collapsible previous history without developer jargon', () => {
    render(<AboutModal onClose={() => {}} onOpenGraph={() => {}} />);
    expect(screen.getAllByText(/v1\.6\.1/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Build 10601/i)).toBeInTheDocument();
    expect(screen.getByText(/Cambio de pestaña sin perder tu montaje/i)).toBeInTheDocument();
    expect(screen.getAllByText(/100% Local/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Historial de versiones anteriores/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Inspeccionar Salud de la Arquitectura/i })).toBeInTheDocument();
  });

  it('supports TecnoRed live health probing, topology neighbor navigation, and flow-to-topology node switching', async () => {
    let probeCalls = 0;
    window.pywebview = {
      api: {
        probe_architecture_health: async () => {
          probeCalls += 1;
          return {
            dmlActive: true,
            providers: ['DmlExecutionProvider', 'CPUExecutionProvider'],
            sqliteOk: true,
            sqliteLatencyMs: 1.2,
            modelsReady: true,
            modelsCount: 3,
            bridgeReady: true,
            exportVariant: 'dual',
          };
        },
      },
    };
    try {
      HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
      render(<AppArchitectureGraph onClose={() => {}} />);
      expect(await screen.findByText(/Topología TecnoRed/i)).toBeInTheDocument();
      expect(await screen.findByText(/DirectML GPU · Modelos 3\/3 · SQLite 1\.2 ms/i)).toBeInTheDocument();
      expect(screen.getByText(/Modo activo: DUAL/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /→ Destino: React 19/i }));
      expect(screen.getByText(/Árbol declarativo Fiber/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Rutas de Flujo/i }));
      expect(screen.getAllByText(/Paso 1/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole('button', { name: /Formato DF11 Pure \(220×276\) y Exportación Dual/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i })).toBeInTheDocument();

      // Clicking a bottom node pill while in 'flows' mode auto-switches back to 'topology' inspector
      fireEvent.click(screen.getByRole('button', { name: /ONNX Runtime DirectML/i }));
      expect(screen.getByText(/DirectML GPU DirectX 12 activa/i)).toBeInTheDocument();

      const refreshBtn = screen.getByRole('button', { name: /Reejecutar sonda de salud/i });
      fireEvent.click(refreshBtn);
      await waitFor(() => expect(probeCalls).toBeGreaterThanOrEqual(2));
      await waitFor(() => expect(refreshBtn.querySelector('.animate-spin')).toBeNull());
    } finally {
      delete window.pywebview;
    }
  });
});
