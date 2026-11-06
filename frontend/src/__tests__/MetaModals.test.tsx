import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import AboutModal from '../components/AboutModal';
import AppArchitectureGraph from '../components/AppArchitectureGraph';
import FaqModal from '../components/FaqModal';

describe('FAQ and About human metadata modals', () => {
  it('renders adaptive FAQ split-view and auto-expands matching items on search', () => {
    render(<FaqModal onClose={() => {}} />);
    expect(screen.getByText(/Centro de Ayuda & FAQ/i)).toBeInTheDocument();
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
  });

  it('renders human-readable v1.6.0 release highlights and collapsible previous history without developer jargon', () => {
    render(<AboutModal onClose={() => {}} onOpenGraph={() => {}} />);
    expect(screen.getAllByText(/v1\.6\.0/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Build 10600/i)).toBeInTheDocument();
    expect(screen.getAllByText(/100% Local/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Historial de versiones anteriores/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Inspeccionar Salud de la Arquitectura/i })).toBeInTheDocument();
  });

  it('supports TecnoRed topology neighbor navigation and flow route switching', async () => {
    HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
    render(<AppArchitectureGraph onClose={() => {}} />);
    expect(await screen.findByText(/Topología TecnoRed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /→ Destino: React 19/i }));
    expect(screen.getByText(/Árbol declarativo Fiber/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Rutas de Flujo/i }));
    expect(screen.getByText(/Paso 1/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i })).toBeInTheDocument();
  });
});
