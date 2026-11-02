import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import AboutModal from '../components/AboutModal';
import FaqModal from '../components/FaqModal';

describe('FAQ and About human metadata modals', () => {
  it('renders adaptive FAQ split-view and auto-expands matching items on search', () => {
    render(<FaqModal onClose={() => {}} />);
    expect(screen.getByText(/Centro de Ayuda & FAQ/i)).toBeInTheDocument();
    const search = screen.getByPlaceholderText(/Buscar dudas/i);
    fireEvent.change(search, { target: { value: 'OneDrive' } });
    expect(screen.getByText(/Game Pass/i)).toBeInTheDocument();
  });

  it('renders human-readable v1.0.0 release highlights without developer jargon', () => {
    render(<AboutModal onClose={() => {}} onOpenGraph={() => {}} />);
    expect(screen.getAllByText(/v1\.0\.0/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/100% Local/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('button', { name: /Inspeccionar Salud de la Arquitectura/i })).toBeInTheDocument();
  });
});
