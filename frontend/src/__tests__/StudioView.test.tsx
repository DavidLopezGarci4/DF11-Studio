import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import StudioView from '../components/StudioView';

if (typeof window !== 'undefined' && typeof window.PointerEvent === 'undefined') {
  window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
}

const CLUBS = {
  '1736': { name: 'Real Madrid', pattern: 'solid', primary: '#F7F8FA', secondary: '#1E293B', collar: '#D4AF37' },
  '1708': { name: 'FC Barcelona', pattern: 'stripes', primary: '#004D98', secondary: '#A50044', collar: '#EDBB00' },
  '999': { name: 'AFC Ajax', pattern: 'solid', primary: '#FFFFFF', secondary: '#D2122E', collar: '#D2122E' },
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

  it('frames raw shirt with zoom/pan on canvas, supports StrictMode Undo/Redo, and extracts only on button click', async () => {
    const extractCalls: unknown[] = [];
    const savedCalls: unknown[] = [];
    let pickSeq = 0;
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [],
        list_saved_faces: async () => [],
        pick_raw_shirt_source: async () => {
          pickSeq += 1;
          return {
            shirtSourceId: `shirt-src-${pickSeq}`,
            rawDataUrl: ONE_PX_PNG,
            width: 270,
            height: 293,
            suggestedName: pickSeq === 1 ? 'Rayo_Local' : 'Barca_Visita',
            suggestedViewport: { zoom: 1.0, panX: 0, panY: 0 },
          };
        },
        preview_shirt_extraction: async (payload: unknown) => {
          extractCalls.push(payload);
          return {
            cleanShirtDataUrl: ONE_PX_PNG,
            collarWidth: 83,
            apexY: 227,
          };
        },
        save_shirt_template: async (payload: unknown) => {
          savedCalls.push(payload);
          return {
            savedTemplateId: 'Rayo_Local',
            templates: [
              {
                templateId: 'Rayo_Local',
                filename: 'Rayo_Local.png',
                displayName: 'Rayo_Local',
                clubId: '1736',
                collarWidth: 83,
                apexY: 227,
                thumbDataUrl: ONE_PX_PNG,
              },
            ],
          };
        },
        render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
      },
    };
    try {
      render(
        <StrictMode>
          <StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />
        </StrictMode>,
      );
      fireEvent.click(screen.getByRole('tab', { name: /Extraer Camiseta/i }));
      fireEvent.click(screen.getByRole('button', { name: /Subir camiseta/i }));

      // 1. Shows raw image positioned on the canvas FIRST without extracting
      expect(await screen.findByAltText(/Encuadre previo de camiseta/i)).toBeInTheDocument();
      expect(extractCalls).toHaveLength(0);

      // 2. Zoom with mouse wheel and move by dragging on canvas
      const shirtCanvas = screen.getByTestId('shirt-extractor-canvas');
      fireEvent.wheel(shirtCanvas, { deltaY: 100 });
      expect(screen.getByText(/Zoom 94%/i)).toBeInTheDocument();

      fireEvent.pointerDown(shirtCanvas, { clientX: 100, clientY: 100, pointerId: 1 });
      fireEvent.pointerMove(shirtCanvas, { clientX: 112, clientY: 108, pointerId: 1 });
      fireEvent.pointerUp(shirtCanvas, { clientX: 112, clientY: 108, pointerId: 1 });
      expect(screen.getByText(/X:12 Y:8/i)).toBeInTheDocument();
      expect(extractCalls).toHaveLength(0);

      // 3. Undo & Redo framing changes before extraction (including Ctrl+Z while range slider is focused)
      const zoomSlider = screen.getByLabelText(/Tamaño de camiseta en el lienzo/i);
      zoomSlider.focus();
      fireEvent.keyDown(zoomSlider, { key: 'z', ctrlKey: true });
      expect(screen.getByText(/X:0 Y:0/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Rehacer' }));
      expect(screen.getByText(/X:12 Y:8/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Rehacer' })).toBeDisabled();

      // 4. Press button to extract ONLY the shirt at the chosen position & size
      fireEvent.click(screen.getByRole('button', { name: /Extraer solo la camiseta/i }));
      expect(await screen.findByAltText(/Plantilla de camiseta limpia/i)).toBeInTheDocument();
      expect(extractCalls).toHaveLength(1);
      expect(extractCalls[0]).toMatchObject({ shirtSourceId: 'shirt-src-1', zoom: 0.94, panX: 12, panY: 8 });

      // 5. Upload a second shirt, then Undo -> restores BOTH Shirt #1's sourceId AND displayName ('Rayo_Local')
      fireEvent.click(screen.getByRole('button', { name: /Subir camiseta/i }));
      await waitFor(() => expect(screen.getByLabelText(/Nombre de plantilla de camiseta/i)).toHaveValue('Barca_Visita'));
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(await screen.findByAltText(/Plantilla de camiseta limpia/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Nombre de plantilla de camiseta/i)).toHaveValue('Rayo_Local');
      expect(extractCalls).toHaveLength(1);

      fireEvent.change(screen.getByLabelText(/Club asociado a plantilla/i), { target: { value: '1736' } });
      fireEvent.click(screen.getByRole('button', { name: /Guardar y usar en Montaje/i }));

      await waitFor(() => expect(savedCalls.length).toBe(1));
      expect(savedCalls[0]).toMatchObject({
        shirtSourceId: 'shirt-src-1',
        displayName: 'Rayo_Local',
        zoom: 0.94,
        panX: 12,
        panY: 8,
      });
      expect(await screen.findByText(/Paso 2 · Capa Camiseta Plantilla/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });

  it('waits for WebView2 pywebviewready and supports custom #ClubID, Nitidez textil, catalog search, seasonal active switch, and deletion', async () => {
    const bridgeCalls: Array<{ fn: string; arg?: unknown }> = [];
    let currentTemplates = [
      {
        templateId: 'Rayo_2025_26',
        filename: 'Rayo_2025_26.png',
        displayName: 'Rayo Local 25/26',
        clubId: '1744',
        clubName: 'Rayo Vallecano',
        season: '2025/26',
        isActiveForClub: false,
        collarWidth: 82,
        apexY: 226,
        thumbDataUrl: ONE_PX_PNG,
      },
      {
        templateId: 'Rayo_2026_27',
        filename: 'Rayo_2026_27.png',
        displayName: 'Rayo Local 26/27',
        clubId: '1744',
        clubName: 'Rayo Vallecano',
        season: '2026/27',
        isActiveForClub: true,
        collarWidth: 83,
        apexY: 227,
        thumbDataUrl: ONE_PX_PNG,
      },
    ];

    window.chrome = { webview: {} };
    delete window.pywebview;

    setTimeout(() => {
      window.pywebview = {
        api: {
          list_shirt_templates: async () => currentTemplates,
          list_saved_faces: async () => [],
          pick_raw_shirt_source: async () => ({
            shirtSourceId: 'shirt-numancia-1',
            rawDataUrl: ONE_PX_PNG,
            width: 260,
            height: 310,
            suggestedName: 'Numancia_Local',
            suggestedViewport: { zoom: 1.0, panX: 0, panY: 0 },
          }),
          preview_shirt_extraction: async (payload: unknown) => {
            bridgeCalls.push({ fn: 'preview_shirt_extraction', arg: payload });
            return { cleanShirtDataUrl: ONE_PX_PNG, collarWidth: 81, apexY: 228 };
          },
          save_shirt_template: async (payload: unknown) => {
            bridgeCalls.push({ fn: 'save_shirt_template', arg: payload });
            const next = {
              templateId: 'Numancia_Local_2026_27',
              filename: 'Numancia_Local_2026_27.png',
              displayName: 'Numancia_Local',
              clubId: '999123',
              clubName: 'CD Numancia B',
              season: '2026/27',
              isActiveForClub: true,
              collarWidth: 81,
              apexY: 228,
              thumbDataUrl: ONE_PX_PNG,
            };
            currentTemplates = [...currentTemplates, next];
            return { savedTemplateId: next.templateId, templates: currentTemplates };
          },
          set_active_club_shirt_template: async (templateId: unknown) => {
            bridgeCalls.push({ fn: 'set_active_club_shirt_template', arg: templateId });
            currentTemplates = currentTemplates.map((t) =>
              t.clubId === '1744' ? { ...t, isActiveForClub: t.templateId === templateId } : t,
            );
            return { activeTemplateId: String(templateId), templates: currentTemplates };
          },
          delete_shirt_template: async (templateId: unknown) => {
            bridgeCalls.push({ fn: 'delete_shirt_template', arg: templateId });
            currentTemplates = currentTemplates.filter((t) => t.templateId !== templateId);
            return { deletedTemplateId: String(templateId), templates: currentTemplates };
          },
          render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
        },
      };
      window.dispatchEvent(new Event('pywebviewready'));
    }, 20);

    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);

      // Delayed WebView2 bridge injection resolves initial templates (2) instead of getting stuck on empty fallback
      await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(2\)/i })).toBeInTheDocument());
      fireEvent.click(screen.getByRole('tab', { name: /Extraer Camiseta \(2\)/i }));

      // Toggle inline FM #ID guide
      fireEvent.click(screen.getByRole('button', { name: /¿Cómo saber el #ID del club\?/i }));
      expect(screen.getByText(/3 formas rápidas de conocer el #ID único/i)).toBeInTheDocument();

      // Upload shirt, adjust Nitidez textil (detailCrispness), extract, assign arbitrary #ID + season, and save in tshirt_templates
      fireEvent.click(screen.getByRole('button', { name: /Subir camiseta/i }));
      expect(await screen.findByAltText(/Encuadre previo de camiseta/i)).toBeInTheDocument();

      const crispSlider = screen.getByLabelText(/Nitidez textil de la camiseta/i);
      fireEvent.change(crispSlider, { target: { value: '0.55' } });
      fireEvent.click(screen.getByRole('button', { name: /Extraer solo la camiseta/i }));
      expect(await screen.findByAltText(/Plantilla de camiseta limpia/i)).toBeInTheDocument();
      expect(bridgeCalls.find((c) => c.fn === 'preview_shirt_extraction')?.arg).toMatchObject({
        detailCrispness: 0.55,
      });

      // Typing past known club prefix '999' (AFC Ajax) -> '999123' must clear auto-filled clubName instead of carrying 'AFC Ajax'
      fireEvent.change(screen.getByLabelText(/ID numérico del club/i), { target: { value: '999' } });
      expect(screen.getByLabelText(/Nombre del club/i)).toHaveValue('AFC Ajax');
      fireEvent.change(screen.getByLabelText(/ID numérico del club/i), { target: { value: '999123' } });
      expect(screen.getByLabelText(/Nombre del club/i)).toHaveValue('');

      fireEvent.change(screen.getByLabelText(/Nombre del club/i), { target: { value: 'CD Numancia B' } });
      fireEvent.change(screen.getByLabelText(/Temporada de la camiseta/i), { target: { value: '2026/27' } });
      fireEvent.click(screen.getByRole('button', { name: /Guardar en tshirt_templates/i }));

      await waitFor(() => expect(bridgeCalls.some((c) => c.fn === 'save_shirt_template')).toBe(true));
      expect(bridgeCalls.find((c) => c.fn === 'save_shirt_template')?.arg).toMatchObject({
        clubId: '999123',
        clubName: 'CD Numancia B',
        season: '2026/27',
        isActiveForClub: true,
        detailCrispness: 0.55,
      });

      // Search & filter catalog, promote historical 2025/26 shirt to ★ active, then delete a template
      const searchInput = screen.getByLabelText(/Buscar plantillas de camiseta/i);
      fireEvent.change(searchInput, { target: { value: '1744' } });
      expect(screen.getByText('Rayo Local 25/26')).toBeInTheDocument();
      expect(screen.queryByText('Numancia_Local')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Activar/i }));
      await waitFor(() =>
        expect(bridgeCalls.some((c) => c.fn === 'set_active_club_shirt_template' && c.arg === 'Rayo_2025_26')).toBe(true),
      );

      fireEvent.click(screen.getByRole('button', { name: /Eliminar plantilla Rayo Local 26\/27/i }));
      fireEvent.click(screen.getByRole('button', { name: 'Borrar' }));
      await waitFor(() =>
        expect(bridgeCalls.some((c) => c.fn === 'delete_shirt_template' && c.arg === 'Rayo_2026_27')).toBe(true),
      );
      expect(screen.queryByText('Rayo Local 26/27')).not.toBeInTheDocument();
    } finally {
      delete window.pywebview;
      delete window.chrome;
    }
  });
});
