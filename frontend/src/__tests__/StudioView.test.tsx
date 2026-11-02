import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import StudioView from '../components/StudioView';

const CLUBS = {
  '1736': { name: 'Real Madrid', pattern: 'solid', primary: '#F7F8FA', secondary: '#1E293B', collar: '#D4AF37' },
  '1708': { name: 'FC Barcelona', pattern: 'stripes', primary: '#004D98', secondary: '#A50044', collar: '#EDBB00' },
};

describe('StudioView 3-layer contract', () => {
  it('renders strictly the 3 DF11 layers and keeps Club selector folded until Club mode is chosen', () => {
    render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
    expect(screen.getByText(/Capa 3 · Marco Maestro DF11/i)).toBeInTheDocument();
    expect(screen.getByText(/Capa 2 · Persona/i)).toBeInTheDocument();
    expect(screen.getByText(/Capa 1 · Fondo/i)).toBeInTheDocument();

    expect(screen.queryByLabelText(/Selector de club/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Club$/i }));
    expect(screen.getByLabelText(/Selector de club/i)).toBeInTheDocument();
  });

  it('validates Football Manager numeric and r- regen UIDs before export', () => {
    render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
    const input = screen.getByLabelText(/ID Football Manager/i);
    fireEvent.change(input, { target: { value: '../bad' } });
    expect(screen.getByText(/Usa dígitos o r-/i)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'r-2002049102' } });
    expect(screen.queryByText(/Usa dígitos o r-/i)).not.toBeInTheDocument();
  });
});
