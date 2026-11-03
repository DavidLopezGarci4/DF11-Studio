import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import StudioView from '../components/StudioView';

const CLUBS = {
  '1736': { name: 'Real Madrid', pattern: 'solid', primary: '#F7F8FA', secondary: '#1E293B', collar: '#D4AF37' },
  '1708': { name: 'FC Barcelona', pattern: 'stripes', primary: '#004D98', secondary: '#A50044', collar: '#EDBB00' },
};

const ONE_PX_PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

describe('StudioView modular 3-tool & 4-step layer contract', () => {
  it('renders the 3 studio tools, 4 chronological steps, and folds Club selector until Club mode is chosen', async () => {
    render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(0\)/i })).toBeInTheDocument());
    expect(screen.getByRole('tab', { name: /Montaje Paso a Paso/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Extraer Cara/i })).toBeInTheDocument();

    expect(screen.getByText(/Paso 1 · Capa Cara y Cuello/i)).toBeInTheDocument();
    expect(screen.getByText(/Paso 2 · Capa Camiseta Plantilla/i)).toBeInTheDocument();
    expect(screen.getByText(/Paso 3 · Capa Fondo/i)).toBeInTheDocument();
    expect(screen.getByText(/Paso 4 · Marco Maestro DF11 y Exportación/i)).toBeInTheDocument();

    expect(screen.queryByLabelText(/Selector de club/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Club$/i }));
    expect(screen.getByLabelText(/Selector de club/i)).toBeInTheDocument();
  });

  it('validates Football Manager numeric and r- regen UIDs before export', async () => {
    render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(0\)/i })).toBeInTheDocument());
    const input = screen.getByLabelText(/ID Football Manager/i);
    fireEvent.change(input, { target: { value: '../bad' } });
    expect(screen.getByText(/Usa dígitos o r-/i)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'r-2002049102' } });
    expect(screen.queryByText(/Usa dígitos o r-/i)).not.toBeInTheDocument();
  });

  it('supports empty-center click picker, wheel pre-crop before extraction, Undo/Redo, and reversible Delete clear', async () => {
    const calls: Array<{ fn: string; arg?: unknown }> = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [
          {
            templateId: 'Caucasian0',
            filename: 'Caucasian0.png',
            displayName: 'Blanca Real',
            clubId: '1736',
            collarWidth: 79,
            apexY: 229,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        list_saved_faces: async () => [],
        pick_raw_face_source: async () => {
          calls.push({ fn: 'pick_raw_face_source' });
          return {
            rawDataUrl: ONE_PX_PNG,
            width: 260,
            height: 310,
            isPreCutout: false,
            crownSrcY: 24,
            suggestedViewport: { zoom: 1.0, panX: 0, panY: 0 },
            fileName: 'RegenTest.png',
          };
        },
        extract_face_from_crop: async (payload: unknown) => {
          calls.push({ fn: 'extract_face_from_crop', arg: payload });
          return {
            headAssetId: 'head-1',
            suggestedName: 'RegenTest',
            headPreviewDataUrl: ONE_PX_PNG,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
      },
    };
    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      const dropzoneBtn = screen.getByRole('button', { name: /Arrastra foto, haz clic o pulsa Ctrl\+V/i });
      fireEvent.pointerDown(dropzoneBtn, { clientX: 50, clientY: 60, pointerId: 1 });
      fireEvent.click(dropzoneBtn);

      // Enters pre-extraction wheel-crop mode WITHOUT extracting yet
      expect(await screen.findByAltText(/Zona de corte previa/i)).toBeInTheDocument();
      expect(calls.map((c) => c.fn)).toEqual(['pick_raw_face_source']);

      const canvas = screen.getByTestId('df11-official-canvas');
      fireEvent.wheel(canvas, { deltaY: -100 });
      expect(screen.getByText(/Zona de corte \(108%\)/i)).toBeInTheDocument();
      expect(calls.map((c) => c.fn)).toEqual(['pick_raw_face_source']);

      // Now user confirms crop -> extraction runs with zoomed viewport
      fireEvent.click(screen.getByRole('button', { name: /Aplicar zona de corte/i }));
      expect(await screen.findByAltText(/Previsualización DF11 260x310/i)).toBeInTheDocument();
      expect(calls.some((c) => c.fn === 'extract_face_from_crop' && (c.arg as { zoom?: number })?.zoom === 1.08)).toBe(true);
      expect(screen.getByText(/Activa: RegenTest/i)).toBeInTheDocument();

      // Press Delete (Suprimir) -> clears edited face onto Undo stack
      fireEvent.keyDown(window, { key: 'Delete' });
      await waitFor(() => expect(screen.queryByText(/Activa: RegenTest/i)).not.toBeInTheDocument());

      // Undo (Ctrl+Z / button) restores the face, Redo clears it again
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(await screen.findByText(/Activa: RegenTest/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Rehacer' }));
      await waitFor(() => expect(screen.queryByText(/Activa: RegenTest/i)).not.toBeInTheDocument());
    } finally {
      delete window.pywebview;
    }
  });

  it('extracts and saves a clean shirt template from the dedicated Extraer Camiseta tool', async () => {
    const savedCalls: unknown[] = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [],
        list_saved_faces: async () => [],
        pick_raw_shirt_source: async () => ({
          rawDataUrl: ONE_PX_PNG,
          cleanShirtDataUrl: ONE_PX_PNG,
          collarWidth: 79,
          apexY: 229,
          suggestedName: 'ItalMed9_Blanca',
        }),
        preview_shirt_extraction: async () => ({
          cleanShirtDataUrl: ONE_PX_PNG,
          collarWidth: 79,
          apexY: 229,
        }),
        save_shirt_template: async (payload: unknown) => {
          savedCalls.push(payload);
          return {
            savedTemplateId: 'ItalMed9_Blanca',
            templates: [
              {
                templateId: 'ItalMed9_Blanca',
                filename: 'ItalMed9_Blanca.png',
                displayName: 'ItalMed9_Blanca',
                clubId: '1736',
                collarWidth: 79,
                apexY: 229,
                thumbDataUrl: ONE_PX_PNG,
              },
            ],
          };
        },
        render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
      },
    };
    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      fireEvent.click(screen.getByRole('tab', { name: /Extraer Camiseta/i }));
      fireEvent.click(screen.getByRole('button', { name: /Subir camiseta/i }));
      expect(await screen.findByAltText(/Plantilla de camiseta limpia/i)).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText(/Club asociado a plantilla/i), { target: { value: '1736' } });
      fireEvent.click(screen.getByRole('button', { name: /Guardar y usar en Montaje/i }));

      await waitFor(() => expect(savedCalls.length).toBe(1));
      expect(await screen.findByText(/Paso 2 · Capa Camiseta Plantilla/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });
});
