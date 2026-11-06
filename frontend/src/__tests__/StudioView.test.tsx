import { StrictMode, useState } from 'react';
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
  it('renders the 3 studio tools, 4 chronological steps, and ONLY Plantilla and Staff tabs in Paso 2', async () => {
    render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(0\)/i })).toBeInTheDocument());
    expect(screen.getByRole('tab', { name: /Montaje Paso a Paso/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Extraer Cara/i })).toBeInTheDocument();

    const step1 = screen.getByText(/Paso 1 · Capa Cara y Cuello/i);
    const step2 = screen.getByText(/Paso 2 · Capa Camiseta Plantilla/i);
    const step3 = screen.getByText(/Paso 3 · Capa Fondo/i);
    const step4 = screen.getByText(/Paso 4 · Marco Maestro DF11 y Exportación/i);
    expect(step1).toBeInTheDocument();
    expect(step2).toBeInTheDocument();
    expect(step3).toBeInTheDocument();
    expect(step4).toBeInTheDocument();

    // In compressed / single-column layout and Tab focus order, Paso 1 -> 2 -> 3 -> 4 must stay strictly chronological
    expect(step1.compareDocumentPosition(step2) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(step2.compareDocumentPosition(step3) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(step3.compareDocumentPosition(step4) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Procedural low-quality tabs must be completely gone; only Plantilla & Staff remain
    expect(screen.getByRole('button', { name: /^Plantilla$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Staff$/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Original \/ Sin/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Club$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Polo Staff/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Traje Staff/i })).not.toBeInTheDocument();
  });

  it('allows optional/free names in 1. Nuestras creaciones while enforcing FM numeric and r- regen UIDs in 2. Pack de Faces FM', async () => {
    render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(0\)/i })).toBeInTheDocument());
    const input = screen.getByLabelText(/ID Football Manager/i);

    // 1. Nuestras creaciones: empty or free footballer name is valid; path traversal is rejected
    expect(screen.queryByText(/Nombre no válido/i)).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'Isi Palazón' } });
    expect(screen.queryByText(/Nombre no válido/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Usa dígitos o r-/i)).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: '../bad' } });
    expect(screen.getByText(/Nombre no válido/i)).toBeInTheDocument();

    // 2. Pack de Faces FM: requires strict numeric or r-<digits> official FM UID
    fireEvent.click(screen.getByRole('button', { name: /Pack de Faces FM/i }));
    fireEvent.change(input, { target: { value: 'Isi Palazón' } });
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

  it('supports Paso 1 directional arrow-key head movement and exact numeric + up/down arrow controls for Zoom & Cuello', async () => {
    const previewPayloads: Array<Record<string, unknown>> = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [
          {
            templateId: 'Navy_Player',
            filename: 'Navy_Player.png',
            displayName: 'Titular Local',
            clubId: '1736',
            category: 'player',
            collarWidth: 79,
            apexY: 228,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        list_saved_faces: async () => [{ faceId: 'smp:Cara1.png', name: 'Cara1', kind: 'sample', thumbDataUrl: ONE_PX_PNG }],
        load_saved_face: async () => ({
          headAssetId: 'head-arrow-1',
          name: 'Cara1',
          isPreCutout: true,
          autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
          previewDataUrl: ONE_PX_PNG,
        }),
        render_modular_preview: async (payload: unknown) => {
          previewPayloads.push(payload as Record<string, unknown>);
          return { previewDataUrl: ONE_PX_PNG };
        },
      },
    };
    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      const faceBtn = await screen.findByRole('button', { name: /Cara1/i });
      fireEvent.click(faceBtn);
      expect(await screen.findByText(/Activa: Cara1/i)).toBeInTheDocument();

      // Select Paso 1 and move head with directional arrow keys (1px normal, 5px with Shift)
      fireEvent.click(screen.getByText(/Paso 1 · Capa Cara y Cuello/i));
      fireEvent.keyDown(window, { key: 'ArrowRight' });
      fireEvent.keyDown(window, { key: 'ArrowDown' });
      fireEvent.keyDown(window, { key: 'ArrowUp', shiftKey: true });
      expect(screen.getByText(/X:1 · Y:-4/i)).toBeInTheDocument();

      // Undo restores X:0 · Y:0
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(screen.getByText(/X:0 · Y:0/i)).toBeInTheDocument();

      // Exact numeric text box + immediate right up/down arrow buttons for Zoom
      const zoomInput = screen.getByLabelText(/Valor exacto de Zoom/i);
      fireEvent.change(zoomInput, { target: { value: '115' } });
      fireEvent.blur(zoomInput);
      expect(zoomInput).toHaveValue('115');
      fireEvent.click(screen.getByRole('button', { name: /Subir Zoom/i }));
      expect(zoomInput).toHaveValue('116');
      fireEvent.click(screen.getByRole('button', { name: /Bajar Zoom/i }));
      expect(zoomInput).toHaveValue('115');

      // Exact numeric text box + immediate right up/down arrow buttons for Cuello (neck thickening)
      const neckInput = screen.getByLabelText(/Valor exacto de Cuello/i);
      fireEvent.change(neckInput, { target: { value: '62' } });
      fireEvent.blur(neckInput);
      expect(neckInput).toHaveValue('62');
      fireEvent.click(screen.getByRole('button', { name: /Subir Cuello/i }));
      expect(neckInput).toHaveValue('63');

      await waitFor(() =>
        expect(
          previewPayloads.some(
            (p) => Math.abs(Number(p.scale) - 1.15) < 1e-3 && Math.abs(Number(p.neckFill) - 0.63) < 1e-3,
          ),
        ).toBe(true),
      );
    } finally {
      delete window.pywebview;
    }
  });

  it('supports Staff category extraction/filtering, FM Facepack Card Remix (swap shirt & swap face), and Paso 4 dual export targets', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    let currentTemplates = [
      {
        templateId: 'Player_Kit',
        filename: 'Player_Kit.png',
        displayName: 'Equipación Jugador',
        clubId: '1736',
        category: 'player' as 'player' | 'staff',
        collarWidth: 79,
        apexY: 228,
        thumbDataUrl: ONE_PX_PNG,
      },
    ];
    let latestFacepackDir = '';

    window.pywebview = {
      api: {
        list_shirt_templates: async () => currentTemplates,
        list_saved_faces: async () => [],
        pick_raw_shirt_source: async () => ({
          shirtSourceId: 'suit-src-1',
          rawDataUrl: ONE_PX_PNG,
          width: 260,
          height: 310,
          suggestedName: 'Traje_Mister',
          suggestedViewport: { zoom: 1.0, panX: 0, panY: 0 },
        }),
        preview_shirt_extraction: async () => ({
          cleanShirtDataUrl: ONE_PX_PNG,
          collarWidth: 76,
          apexY: 230,
        }),
        save_shirt_template: async (payload: unknown) => {
          calls.push({ fn: 'save_shirt_template', args: [payload] });
          const next = {
            templateId: 'Traje_Mister',
            filename: 'Traje_Mister.png',
            displayName: 'Traje_Mister',
            clubId: '1736',
            category: ((payload as { category?: 'player' | 'staff' })?.category ?? 'player') as 'player' | 'staff',
            collarWidth: 76,
            apexY: 230,
            thumbDataUrl: ONE_PX_PNG,
          };
          currentTemplates = [...currentTemplates, next];
          return { savedTemplateId: next.templateId, templates: currentTemplates };
        },
        pick_facepack_card: async (...args: unknown[]) => {
          calls.push({ fn: 'pick_facepack_card', args });
          const mode = String(args[0] || 'swap_shirt');
          if (mode === 'swap_face') {
            return {
              remixMode: 'swap_face',
              detectedUid: '29184012',
              cardLabel: '29184012',
              facepackDir: 'D:\\FM27\\graphics\\faces',
              adhocShirtId: 'adhoc:shirt-1',
              adhocShirtLabel: 'Camiseta ficha 29184012',
              adhocShirtThumbDataUrl: ONE_PX_PNG,
              collarWidth: 80,
              apexY: 227,
              autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
              previewDataUrl: ONE_PX_PNG,
            };
          }
          return {
            remixMode: 'swap_shirt',
            detectedUid: '29184012',
            cardLabel: '29184012',
            facepackDir: 'D:\\FM27\\graphics\\faces',
            headAssetId: 'head-remix-29184012',
            templateId: 'Traje_Mister',
            isPreCutout: false,
            autoFit: { scale: 0.98, offsetX: 1, offsetY: -2, neckFill: 0.95 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        switch_facepack_remix_mode: async (...args: unknown[]) => {
          calls.push({ fn: 'switch_facepack_remix_mode', args });
          return {
            remixMode: 'swap_face',
            detectedUid: '29184012',
            cardLabel: '29184012',
            adhocShirtId: 'adhoc:shirt-1',
            adhocShirtLabel: 'Camiseta ficha 29184012',
            adhocShirtThumbDataUrl: ONE_PX_PNG,
            collarWidth: 80,
            apexY: 227,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        choose_directory: async (which: unknown) => {
          calls.push({ fn: 'choose_directory', args: [which] });
          return { path: 'D:\\FM27\\graphics\\faces_megapack' };
        },
        export_modular_card: async (payload: unknown) => {
          calls.push({ fn: 'export_modular_card', args: [payload] });
          return { savedPath: 'D:\\FM27\\graphics\\faces\\29184012.png' };
        },
        render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
      },
    };

    try {
      render(
        <StudioView
          clubs={CLUBS}
          exportDir="D:\\DF11Studio\\Exports"
          facepackDir={latestFacepackDir}
          onExportDirChange={() => {}}
          onFacepackDirChange={(dir) => {
            latestFacepackDir = dir;
          }}
          initialJump={null}
        />,
      );

      await waitFor(() => expect(screen.getByText('Equipación Jugador')).toBeInTheDocument());

      // 1. Switch to Staff tab in Paso 2 -> Player_Kit is hidden; click '+ Extraer' -> opens ShirtExtractorTool pre-set to 'staff'
      fireEvent.click(screen.getByRole('button', { name: /^Staff$/i }));
      expect(screen.queryByText('Equipación Jugador')).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /\+ Extraer/i }));

      fireEvent.click(screen.getByRole('button', { name: /Subir camiseta/i }));
      expect(await screen.findByAltText(/Encuadre previo de camiseta/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Extraer solo la camiseta/i }));
      expect(await screen.findByAltText(/Plantilla de camiseta limpia/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Guardar y usar en Montaje/i }));

      await waitFor(() => expect(calls.some((c) => c.fn === 'save_shirt_template')).toBe(true));
      expect(calls.find((c) => c.fn === 'save_shirt_template')?.args[0]).toMatchObject({ category: 'staff' });
      expect(await screen.findByText('Traje_Mister')).toBeInTheDocument();

      // 2. Load assembled FM Facepack card ('Cambiar camiseta a ficha FM') -> auto-populates UID '29184012' & facepackDir
      fireEvent.click(screen.getByRole('button', { name: /Cambiar camiseta a ficha FM/i }));
      await waitFor(() => expect(screen.getByLabelText(/ID Football Manager/i)).toHaveValue('29184012'));
      expect(latestFacepackDir).toBe('D:\\FM27\\graphics\\faces');

      // Switch loaded card to 'swap_face' -> mounts card's own shirt ('Camiseta ficha 29184012')
      fireEvent.click(screen.getByRole('button', { name: /Usar su camiseta/i }));
      expect(await screen.findByText(/Camiseta ficha 29184012/i)).toBeInTheDocument();

      // 3. Paso 4 Dual Destination: export first to 'Nuestras creaciones', then to 'Pack de Faces FM'
      fireEvent.click(screen.getByRole('button', { name: /Nuestras creaciones/i }));
      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11/i }));
      await waitFor(() =>
        expect(
          calls.some(
            (c) =>
              c.fn === 'export_modular_card' &&
              (c.args[0] as { exportTarget?: string })?.exportTarget === 'creations',
          ),
        ).toBe(true),
      );

      fireEvent.click(screen.getByRole('button', { name: /Pack de Faces FM/i }));
      fireEvent.click(screen.getByRole('button', { name: /Elegir carpeta Pack Faces FM/i }));
      await waitFor(() => expect(calls.some((c) => c.fn === 'choose_directory' && c.args[0] === 'facepack')).toBe(true));

      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11/i }));
      await waitFor(() =>
        expect(
          calls.some(
            (c) =>
              c.fn === 'export_modular_card' &&
              (c.args[0] as { exportTarget?: string; uid?: string; fmt?: string })?.exportTarget === 'facepack' &&
              (c.args[0] as { uid?: string })?.uid === '29184012' &&
              (c.args[0] as { fmt?: string })?.fmt === 'png',
          ),
        ).toBe(true),
      );
    } finally {
      delete window.pywebview;
    }
  });

  it('coalesces multi-digit stepper typing & slider drags into 1 Undo step, allows Paso 1 arrows on checkboxes, and keeps remix state across Undo', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [
          {
            templateId: 'Player_Kit',
            filename: 'Player_Kit.png',
            displayName: 'Equipación Jugador',
            clubId: '1736',
            category: 'player',
            collarWidth: 79,
            apexY: 228,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        list_saved_faces: async () => [{ faceId: 'smp:Cara2.png', name: 'Cara2', kind: 'sample', thumbDataUrl: ONE_PX_PNG }],
        load_saved_face: async () => ({
          headAssetId: 'head-saved-2',
          name: 'Cara2',
          isPreCutout: true,
          autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
          previewDataUrl: ONE_PX_PNG,
        }),
        pick_facepack_card: async () => ({
          remixMode: 'swap_shirt',
          detectedUid: '29184012',
          cardLabel: '29184012',
          facepackDir: 'D:\\FM27\\graphics\\faces',
          headAssetId: 'head-remix-29184012',
          templateId: 'Player_Kit',
          isPreCutout: false,
          autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
          previewDataUrl: ONE_PX_PNG,
        }),
        switch_facepack_remix_mode: async (mode: unknown) => {
          calls.push({ fn: 'switch_facepack_remix_mode', args: [mode] });
          if (mode === 'swap_face') {
            return {
              remixMode: 'swap_face',
              detectedUid: '29184012',
              cardLabel: '29184012',
              adhocShirtId: 'adhoc:shirt-1',
              adhocShirtLabel: 'Camiseta ficha 29184012',
              adhocShirtThumbDataUrl: ONE_PX_PNG,
              collarWidth: 80,
              apexY: 227,
              autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
              previewDataUrl: ONE_PX_PNG,
            };
          }
          return {
            remixMode: 'swap_shirt',
            detectedUid: '29184012',
            cardLabel: '29184012',
            headAssetId: 'head-remix-29184012',
            templateId: 'Player_Kit',
            isPreCutout: false,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        save_adhoc_shirt_template: async () => ({
          savedTemplateId: 'Camiseta_29184012',
          templates: [
            {
              templateId: 'Player_Kit',
              filename: 'Player_Kit.png',
              displayName: 'Equipación Jugador',
              clubId: '1736',
              category: 'player',
              collarWidth: 79,
              apexY: 228,
              thumbDataUrl: ONE_PX_PNG,
            },
            {
              templateId: 'Camiseta_29184012',
              filename: 'Camiseta_29184012.png',
              displayName: 'Camiseta ficha 29184012',
              clubId: '',
              category: 'player',
              collarWidth: 80,
              apexY: 227,
              thumbDataUrl: ONE_PX_PNG,
            },
          ],
        }),
        render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
      },
    };

    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      fireEvent.click(await screen.findByRole('button', { name: /Cambiar camiseta a ficha FM/i }));
      expect(await screen.findByText(/Activa: Ficha FM 29184012/i)).toBeInTheDocument();

      // 1. Multi-digit typing '1' -> '12' -> '125' in Cuello must take ONLY 1 Undo click to return to 100%!
      const neckInput = screen.getByLabelText(/Valor exacto de Cuello/i);
      fireEvent.focus(neckInput);
      fireEvent.change(neckInput, { target: { value: '1' } });
      fireEvent.change(neckInput, { target: { value: '12' } });
      fireEvent.change(neckInput, { target: { value: '125' } });
      fireEvent.blur(neckInput);
      expect(neckInput).toHaveValue('125');
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(neckInput).toHaveValue('100');

      // 2. Dragging Zoom range slider across multiple intermediate ticks takes ONLY 1 Undo click!
      const zoomSlider = screen.getByLabelText(/Barra de Zoom de cabeza/i);
      const zoomInput = screen.getByLabelText(/Valor exacto de Zoom/i);
      fireEvent.pointerDown(zoomSlider);
      fireEvent.change(zoomSlider, { target: { value: '110' } });
      fireEvent.change(zoomSlider, { target: { value: '120' } });
      fireEvent.change(zoomSlider, { target: { value: '132' } });
      fireEvent.pointerUp(zoomSlider);
      expect(zoomInput).toHaveValue('132');
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(zoomInput).toHaveValue('100');

      // 3. Clicking 'Luz DF11' checkbox (focusing <input type="checkbox">) must NOT block Paso 1 ArrowRight head movement!
      const luzCheckbox = screen.getByRole('checkbox', { name: /Luz DF11/i });
      luzCheckbox.focus();
      fireEvent.keyDown(luzCheckbox, { key: 'ArrowRight' });
      expect(screen.getByText(/X:1 · Y:0/i)).toBeInTheDocument();

      // 4. Replacing remix face with saved 'Cara2' and clicking 'Usar su cara' MUST restore 'Ficha FM 29184012' (no dead no-op!)
      fireEvent.click(screen.getByRole('button', { name: /Cara2/i }));
      expect(await screen.findByText(/Activa: Cara2/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Usar su cara/i }));
      expect(await screen.findByText(/Activa: Ficha FM 29184012/i)).toBeInTheDocument();

      // 5. Switch to 'Usar su camiseta', save adhoc shirt to templates, then Undo -> isolated banner reappears!
      fireEvent.click(screen.getByRole('button', { name: /Usar su camiseta/i }));
      expect(await screen.findByText(/Camiseta original aislada de la ficha del Pack de Faces/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Guardar en plantillas/i }));
      await waitFor(() =>
        expect(screen.queryByText(/Camiseta original aislada de la ficha del Pack de Faces/i)).not.toBeInTheDocument(),
      );
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(await screen.findByText(/Camiseta original aislada de la ficha del Pack de Faces/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });

  it('preserves empty regen jump templateId across async catalog load, isolates sequential facepack remixes, and preserves Undo on same-prefix edits', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    let cardPickCount = 0;

    window.pywebview = {
      api: {
        list_shirt_templates: async () => [
          {
            templateId: 'Staff_555000',
            filename: 'Staff_555000.png',
            displayName: 'Traje Club 555',
            clubId: '555000',
            category: 'staff',
            isActiveForClub: true,
            collarWidth: 76,
            apexY: 230,
            thumbDataUrl: ONE_PX_PNG,
          },
          {
            templateId: 'Madrid_Player',
            filename: 'Madrid_Player.png',
            displayName: 'Titular Madrid',
            clubId: '1736',
            category: 'player',
            isActiveForClub: true,
            collarWidth: 79,
            apexY: 228,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        list_saved_faces: async () => [],
        auto_fit_head_to_template: async () => ({ scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 }),
        pick_facepack_card: async (mode: unknown) => {
          cardPickCount += 1;
          calls.push({ fn: 'pick_facepack_card', args: [mode, cardPickCount] });
          if (cardPickCount === 1) {
            return {
              remixMode: 'swap_shirt',
              detectedUid: '29184012',
              cardLabel: '29184012',
              facepackDir: 'D:\\FM27\\graphics\\faces',
              headAssetId: 'head-card-1',
              templateId: 'Madrid_Player',
              isPreCutout: false,
              autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
              previewDataUrl: ONE_PX_PNG,
            };
          }
          if (cardPickCount === 2) {
            return {
              remixMode: 'swap_face',
              detectedUid: '19005544',
              cardLabel: '19005544',
              facepackDir: 'D:\\FM27\\graphics\\faces',
              adhocShirtId: 'adhoc:shirt-2',
              adhocShirtLabel: 'Camiseta ficha 19005544',
              adhocShirtThumbDataUrl: ONE_PX_PNG,
              collarWidth: 80,
              apexY: 227,
              autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
              previewDataUrl: ONE_PX_PNG,
            };
          }
          return {
            remixMode: 'swap_shirt',
            detectedUid: '30009911',
            cardLabel: '30009911',
            facepackDir: 'D:\\FM27\\graphics\\faces',
            headAssetId: 'head-card-3',
            templateId: 'Madrid_Player',
            isPreCutout: false,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        switch_facepack_remix_mode: async (mode: unknown) => {
          calls.push({ fn: 'switch_facepack_remix_mode', args: [mode] });
          return {
            remixMode: 'swap_shirt',
            detectedUid: '19005544',
            cardLabel: '19005544',
            headAssetId: 'head-card-2',
            templateId: 'Madrid_Player',
            isPreCutout: false,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        export_modular_card: async (payload: unknown) => {
          calls.push({ fn: 'export_modular_card', args: [payload] });
          return { savedPath: 'D:\\DF11Studio\\Exports\\r-8801.png' };
        },
        render_modular_preview: async (payload: unknown) => {
          calls.push({ fn: 'render_modular_preview', args: [payload] });
          return { previewDataUrl: ONE_PX_PNG };
        },
      },
    };

    function JumpHarness() {
      const [jump, setJump] = useState<{
        uid: string;
        headAssetId: string;
        matchedTemplateId: string;
        clubId: string;
        previewDataUrl: string;
        isPreCutout: boolean;
        autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
      } | null>({
        uid: 'r-8801',
        headAssetId: 'head-regen-8801',
        matchedTemplateId: '',
        clubId: '555000',
        previewDataUrl: ONE_PX_PNG,
        isPreCutout: true,
        autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
      });
      return (
        <StudioView
          clubs={CLUBS}
          exportDir="D:\\DF11Studio\\Exports"
          onExportDirChange={() => {}}
          initialJump={jump}
          onConsumeJump={() => setJump(null)}
        />
      );
    }

    try {
      const { unmount } = render(
        <StrictMode>
          <JumpHarness />
        </StrictMode>,
      );

      // 1. Async catalog load must NOT overwrite unmatched regen jump's templateId: '' with Madrid_Player or Staff_555000!
      await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(2\)/i })).toBeInTheDocument());
      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11/i }));
      await waitFor(() => expect(calls.some((c) => c.fn === 'export_modular_card')).toBe(true));
      expect(calls.find((c) => c.fn === 'export_modular_card')?.args[0]).toMatchObject({
        uid: 'r-8801',
        headAssetId: 'head-regen-8801',
        templateId: '',
      });

      // 2. Clearing '0' -> '' -> '0' -> '05' must preserve '0' as the Undo restore point!
      const neckInput = screen.getByLabelText(/Valor exacto de Cuello/i);
      fireEvent.focus(neckInput);
      fireEvent.change(neckInput, { target: { value: '0' } });
      fireEvent.blur(neckInput);
      expect(neckInput).toHaveValue('0');

      fireEvent.focus(neckInput);
      fireEvent.change(neckInput, { target: { value: '' } });
      fireEvent.change(neckInput, { target: { value: '0' } });
      fireEvent.change(neckInput, { target: { value: '05' } });
      fireEvent.blur(neckInput);
      expect(neckInput).toHaveValue('5');
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(neckInput).toHaveValue('0');

      // 3. Sequential Facepack Card Remix: Card #1 (swap_shirt) -> Card #2 (swap_face) -> select Madrid_Player -> 'Usar su cara' MUST extract Card #2's face!
      fireEvent.click(screen.getByRole('button', { name: /Cambiar camiseta a ficha FM/i }));
      expect(await screen.findByText(/Activa: Ficha FM 29184012/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Cambiar cara \(conservar su camiseta\)/i }));
      expect(await screen.findByText(/Camiseta ficha 19005544/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Titular Madrid/i }));
      fireEvent.click(screen.getByRole('button', { name: /Usar su cara/i }));
      expect(await screen.findByText(/Activa: Ficha FM 19005544/i)).toBeInTheDocument();
      expect(calls.some((c) => c.fn === 'switch_facepack_remix_mode' && c.args[0] === 'swap_shirt')).toBe(true);

      // Loading Card #3 (swap_shirt) clears Card #2's isolated shirt banner from Paso 2
      fireEvent.click(screen.getByRole('button', { name: /Cambiar camiseta a ficha FM/i }));
      expect(await screen.findByText(/Activa: Ficha FM 30009911/i)).toBeInTheDocument();
      expect(screen.queryByText(/Camiseta ficha 19005544/i)).not.toBeInTheDocument();

      unmount();

      // 4. Fresh mount with ONLY Staff templates must NOT pre-select a Staff suit under the Plantilla tab
      window.pywebview = {
        api: {
          list_shirt_templates: async () => [
            {
              templateId: 'Staff_555000',
              filename: 'Staff_555000.png',
              displayName: 'Traje Club 555',
              clubId: '555000',
              category: 'staff',
              isActiveForClub: true,
              collarWidth: 76,
              apexY: 230,
              thumbDataUrl: ONE_PX_PNG,
            },
          ],
          list_saved_faces: async () => [],
          render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
        },
      };
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(1\)/i })).toBeInTheDocument());
      expect(screen.queryByLabelText(/Nombre de la camiseta activa/i)).not.toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });

  it('supports Paso 1 Foto Directa + Marco DF11 with 4-cardinal pad, center-pivot zoom, Undo/Redo, and Paso 4 Calidad óptica', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [
          {
            templateId: 'Madrid_Player',
            filename: 'Madrid_Player.png',
            displayName: 'Titular Madrid',
            clubId: '1736',
            category: 'player',
            isActiveForClub: true,
            collarWidth: 79,
            apexY: 228,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        list_saved_faces: async () => [],
        pick_direct_photo_source: async (...args: unknown[]) => {
          calls.push({ fn: 'pick_direct_photo_source', args });
          return {
            directPhotoId: 'direct-1',
            fileName: '29184012.jpg',
            label: '29184012',
            detectedUid: '29184012',
            width: 420,
            height: 280,
            isPreCutout: false,
            clampPan: true,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        pick_raw_face_source: async () => {
          throw new Error('pick_raw_face_source must not be called in Foto Directa mode');
        },
        render_modular_preview: async (payload: unknown) => {
          calls.push({ fn: 'render_modular_preview', args: [payload] });
          return { previewDataUrl: ONE_PX_PNG };
        },
        export_modular_card: async (payload: unknown) => {
          calls.push({ fn: 'export_modular_card', args: [payload] });
          return { savedPath: 'D:\\DF11Studio\\Exports\\29184012.png' };
        },
      },
    };

    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      await waitFor(() => expect(screen.getByRole('tab', { name: /Extraer Camiseta \(1\)/i })).toBeInTheDocument());

      // Switch Paso 1 to 'Foto Directa + Marco DF11' and load a photo directly (no head/neck crop staging!)
      fireEvent.click(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i }));
      fireEvent.click(screen.getByRole('button', { name: /Subir foto directa/i }));

      expect(await screen.findByText(/Activa: 29184012/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/ID Football Manager/i)).toHaveValue('29184012');
      expect(screen.queryByAltText(/Zona de corte previa/i)).not.toBeInTheDocument();
      expect(screen.getByText(/Modo Foto Directa activo/i)).toBeInTheDocument();

      // Zoom in slightly via wheel (100% -> 110%) so 420x280 has vertical headroom (limY = 13.9px > 8px), then move in all 4 cardinal points (N, S, O, E) + keyboard arrow
      const canvas = screen.getByTestId('df11-official-canvas');
      fireEvent.wheel(canvas, { deltaY: -100 });
      fireEvent.wheel(canvas, { deltaY: -100 });
      expect(screen.getByLabelText(/Valor exacto de Zoom/i)).toHaveValue('110');

      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }));
      expect(screen.getByText(/X:0 · Y:-2/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Mover al Sur/i }));
      expect(screen.getByText(/X:0 · Y:0/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Mover al Oeste/i }));
      expect(screen.getByText(/X:-2 · Y:0/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Mover al Este/i }));
      fireEvent.click(screen.getByRole('button', { name: /Mover al Este/i }));
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }), { shiftKey: true });
      fireEvent.keyDown(window, { key: 'ArrowRight' });
      expect(screen.getByText(/X:3 · Y:-8/i)).toBeInTheDocument();

      // Center-pivot zoom: doubling zoom 110% -> 220% scales pan offset (3, -8) -> (6, -16) around DF11 optical center
      const zoomInput = screen.getByLabelText(/Valor exacto de Zoom/i);
      fireEvent.focus(zoomInput);
      fireEvent.change(zoomInput, { target: { value: '220' } });
      fireEvent.blur(zoomInput);
      expect(screen.getByText(/X:6 · Y:-16/i)).toBeInTheDocument();

      // Center reset (0,0) + Undo/Redo
      fireEvent.click(screen.getByRole('button', { name: /Centrar posición/i }));
      expect(screen.getByText(/X:0 · Y:0/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(screen.getByText(/X:6 · Y:-16/i)).toBeInTheDocument();

      // Toggle 'Ajustar a bordes' (clampPan)
      const clampCheckbox = screen.getByRole('checkbox', { name: /Ajustar a bordes/i });
      expect(clampCheckbox).toBeChecked();
      fireEvent.click(clampCheckbox);
      expect(clampCheckbox).not.toBeChecked();

      // Adjust Paso 4 'Calidad óptica' (100% offline WGIF) with coalesced typing + stepper arrow, then export
      const qualInput = screen.getByLabelText(/Valor exacto de Calidad óptica/i);
      fireEvent.focus(qualInput);
      fireEvent.change(qualInput, { target: { value: '6' } });
      fireEvent.change(qualInput, { target: { value: '65' } });
      fireEvent.blur(qualInput);
      expect(qualInput).toHaveValue('65');
      fireEvent.click(screen.getByRole('button', { name: /Deshacer/i }));
      expect(qualInput).toHaveValue('0');
      fireEvent.click(screen.getByRole('button', { name: /Rehacer/i }));
      expect(qualInput).toHaveValue('65');
      fireEvent.click(screen.getByRole('button', { name: /Subir Calidad óptica/i }));
      expect(qualInput).toHaveValue('66');

      // Paso 3 'Extraer de foto' must remain disabled in zero-AI Direct Photo mode
      expect(screen.getByRole('button', { name: /Extraer de foto/i })).toBeDisabled();

      // Switching to Modo Capas via Paso 2 notice and back preserves independent transforms
      fireEvent.click(screen.getByRole('button', { name: /Cambiar a Modo Capas/i }));
      expect(screen.getByText(/X:0 · Y:0/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Valor exacto de Zoom/i)).toHaveValue('100');
      fireEvent.click(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i }));
      expect(screen.getByText(/X:6 · Y:-16/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Valor exacto de Zoom/i)).toHaveValue('220');

      // Reversible Delete clear in Direct Photo mode
      fireEvent.keyDown(window, { key: 'Delete' });
      expect(screen.getByRole('button', { name: /Arrastra foto directa/i })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(screen.getByText(/Activa: 29184012/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11/i }));
      await waitFor(() => expect(calls.some((c) => c.fn === 'export_modular_card')).toBe(true));
      expect(calls.find((c) => c.fn === 'export_modular_card')?.args[0]).toMatchObject({
        uid: '29184012',
        step1Mode: 'direct_photo',
        directPhotoId: 'direct-1',
        scale: 2.2,
        offsetX: 6,
        offsetY: -16,
        clampPan: false,
        enhanceQuality: 0.66,
      });
    } finally {
      delete window.pywebview;
    }
  });

  it('clamps Foto Directa X:/Y: with Ajustar a bordes (zero windup, zero dead reverse clicks, zero duplicate preview IPC)', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [],
        list_saved_faces: async () => [],
        pick_direct_photo_source: async (...args: unknown[]) => {
          calls.push({ fn: 'pick_direct_photo_source', args });
          return {
            directPhotoId: 'direct-clamp-1',
            fileName: '99112233.png',
            label: '99112233',
            detectedUid: '99112233',
            width: 420,
            height: 280,
            isPreCutout: false,
            clampPan: true,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        render_modular_preview: async (payload: unknown) => {
          calls.push({ fn: 'render_modular_preview', args: [payload] });
          return { previewDataUrl: ONE_PX_PNG };
        },
      },
    };

    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);
      fireEvent.click(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i }));
      fireEvent.click(screen.getByRole('button', { name: /Subir foto directa/i }));
      expect(await screen.findByText(/Activa: 99112233/i)).toBeInTheDocument();

      // Wait > 65ms debounce: hydrated previewDataUrl from pick_direct_photo_source must NOT trigger duplicate render_modular_preview
      await new Promise((r) => setTimeout(r, 110));
      expect(calls.filter((c) => c.fn === 'render_modular_preview')).toHaveLength(0);

      // At 100% zoom on 420x280 cover fit: dispH = 278 -> limY = 0, dispW = 417 -> limX = 96.5
      // Vertical N/S clicks and ArrowUp/Down must NOT wind up Y or push no-op Undo snapshots
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }), { shiftKey: true });
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }), { shiftKey: true });
      fireEvent.keyDown(window, { key: 'ArrowUp', shiftKey: true });
      expect(screen.getByText(/X:0 · Y:0/i)).toBeInTheDocument();

      // Push East well past limX = 96.5 (15 * 8px = 120px) -> clamps strictly at 96.5
      const eastBtn = screen.getByRole('button', { name: /Mover al Este/i });
      for (let i = 0; i < 15; i += 1) {
        fireEvent.click(eastBtn, { shiftKey: true });
      }
      expect(screen.getByText(/X:96\.5 · Y:0/i)).toBeInTheDocument();

      // Single normal West click (-2px) responds immediately without dead clicks!
      fireEvent.click(screen.getByRole('button', { name: /Mover al Oeste/i }));
      expect(screen.getByText(/X:94\.5 · Y:0/i)).toBeInTheDocument();

      // Zoom to 200%, pan North (-16px), then zoom back down to 100% -> Y clamps back to 0
      const zoomInput = screen.getByLabelText(/Valor exacto de Zoom/i);
      fireEvent.focus(zoomInput);
      fireEvent.change(zoomInput, { target: { value: '200' } });
      fireEvent.blur(zoomInput);
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }), { shiftKey: true });
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }), { shiftKey: true });
      expect(screen.getByText(/Y:-16/i)).toBeInTheDocument();

      fireEvent.focus(zoomInput);
      fireEvent.change(zoomInput, { target: { value: '100' } });
      fireEvent.blur(zoomInput);
      expect(screen.getByText(/X:94\.5 · Y:0/i)).toBeInTheDocument();

      // Disable 'Ajustar a bordes', move North (-8px), then re-enable -> snaps Y back to 0
      const clampCheckbox = screen.getByRole('checkbox', { name: /Ajustar a bordes/i });
      fireEvent.click(clampCheckbox);
      expect(clampCheckbox).not.toBeChecked();
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }), { shiftKey: true });
      expect(screen.getByText(/X:94\.5 · Y:-8/i)).toBeInTheDocument();
      fireEvent.click(clampCheckbox);
      expect(clampCheckbox).toBeChecked();
      expect(screen.getByText(/X:94\.5 · Y:0/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });

  it('preserves Foto Directa preview & Arrow Undo purity under StrictMode and omits clampPan on load', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    let pickCount = 0;
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [],
        list_saved_faces: async () => [],
        pick_direct_photo_source: async (...args: unknown[]) => {
          calls.push({ fn: 'pick_direct_photo_source', args });
          pickCount += 1;
          if (pickCount === 1) {
            return {
              directPhotoId: 'direct-strict-1',
              fileName: '77001122.png',
              label: '77001122',
              detectedUid: '77001122',
              width: 420,
              height: 280,
              isPreCutout: false,
              clampPan: true,
              autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
              previewDataUrl: ONE_PX_PNG,
            };
          }
          return {
            directPhotoId: 'direct-strict-precut',
            fileName: '77009999.png',
            label: '77009999',
            detectedUid: '77009999',
            width: 224,
            height: 278,
            isPreCutout: true,
            clampPan: false,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        render_modular_preview: async (payload: unknown) => {
          calls.push({ fn: 'render_modular_preview', args: [payload] });
          return { previewDataUrl: ONE_PX_PNG };
        },
      },
    };

    try {
      render(
        <StrictMode>
          <StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />
        </StrictMode>,
      );

      fireEvent.click(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i }));
      fireEvent.click(screen.getByRole('button', { name: /Subir foto directa/i }));
      expect(await screen.findByText(/Activa: 77001122/i)).toBeInTheDocument();
      expect(screen.getByAltText('Previsualización DF11 260x310')).toBeInTheDocument();

      // 1. pick_direct_photo_source must NOT pass forced clampPan so backend applies !isPreCutout default
      const firstPickOpts = calls.find((c) => c.fn === 'pick_direct_photo_source')?.args[0] as Record<string, unknown>;
      expect(firstPickOpts).toBeDefined();
      expect('clampPan' in firstPickOpts).toBe(false);

      // 2. Zero duplicate render_modular_preview calls under StrictMode double-effect mount
      await new Promise((r) => setTimeout(r, 110));
      expect(calls.filter((c) => c.fn === 'render_modular_preview')).toHaveLength(0);

      // 3. Switch to empty Modo Capas (clears preview) -> switch back to Foto Directa -> restores preview via IPC
      fireEvent.click(screen.getByRole('button', { name: /Modo Capas \(Cara \+ Camiseta\)/i }));
      expect(screen.queryByAltText('Previsualización DF11 260x310')).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'render_modular_preview').length).toBeGreaterThanOrEqual(1));
      expect(await screen.findByAltText('Previsualización DF11 260x310')).toBeInTheDocument();

      // 4. Under StrictMode, ArrowRight pushes an Undo entry so Deshacer reverts X:1 -> X:0 instead of wiping the photo
      fireEvent.keyDown(window, { key: 'ArrowRight' });
      expect(screen.getByText(/X:1 · Y:0/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }));
      expect(screen.getByText(/X:0 · Y:0/i)).toBeInTheDocument();
      expect(screen.getByText(/Activa: 77001122/i)).toBeInTheDocument();

      // 5. Undo past empty Modo Capas and Redo back to Foto Directa restores preview image cleanly
      fireEvent.click(screen.getByRole('button', { name: 'Deshacer' })); // back to empty Modo Capas
      expect(screen.queryByAltText('Previsualización DF11 260x310')).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Rehacer' })); // back to Foto Directa
      expect(await screen.findByAltText('Previsualización DF11 260x310')).toBeInTheDocument();

      // 6. Loading a pre-cutout Direct Photo omits clampPan, leaves Ajustar a bordes unchecked, and allows free pan at 100%
      fireEvent.click(screen.getByRole('button', { name: /Subir foto directa/i }));
      expect(await screen.findByText(/Activa: 77009999/i)).toBeInTheDocument();
      const pickCalls = calls.filter((c) => c.fn === 'pick_direct_photo_source');
      expect(pickCalls).toHaveLength(2);
      expect('clampPan' in (pickCalls[1].args[0] as Record<string, unknown>)).toBe(false);

      const clampCheckbox = screen.getByRole('checkbox', { name: /Ajustar a bordes/i });
      expect(clampCheckbox).not.toBeChecked();
      fireEvent.click(screen.getByRole('button', { name: /Mover al Norte/i }));
      expect(screen.getByText(/X:0 · Y:-2/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });

  it('routes hot screen capture independently (direct_photo, raw_face, raw_shirt, save_png, Esc cancel) with DRM/low-res notices, guarded Ctrl+V, and persistent tool history', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    let nextCancelled = false;
    let nextDrm = false;
    let nextLowRes = false;
    let addonPendingPayload: Record<string, unknown> | null = null;

    window.pywebview = {
      api: {
        list_shirt_templates: async () => [],
        list_saved_faces: async () => [],
        capture_screen_region: async (target: unknown, params?: unknown) => {
          calls.push({ fn: 'capture_screen_region', args: [target, params] });
          if (nextCancelled) {
            return { cancelled: true };
          }
          if (target === 'direct_photo') {
            return {
              cancelled: false,
              target: 'direct_photo',
              captureWidth: 120,
              captureHeight: 140,
              drmWarning: nextDrm,
              lowResWarning: nextLowRes,
              directPhotoId: 'direct-cap-1',
              fileName: 'Captura_1.png',
              label: 'Captura_1',
              width: 120,
              height: 140,
              isPreCutout: false,
              clampPan: true,
              autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
              previewDataUrl: ONE_PX_PNG,
            };
          }
          if (target === 'raw_face') {
            return {
              cancelled: false,
              target: 'raw_face',
              captureWidth: 240,
              captureHeight: 290,
              drmWarning: false,
              lowResWarning: false,
              rawDataUrl: ONE_PX_PNG,
              width: 240,
              height: 290,
              isPreCutout: false,
              crownSrcY: 22,
              suggestedViewport: { zoom: 1.0, panX: 0, panY: 0 },
              fileName: 'Captura_Cara_1.png',
            };
          }
          if (target === 'raw_shirt') {
            return {
              cancelled: false,
              target: 'raw_shirt',
              captureWidth: 300,
              captureHeight: 190,
              drmWarning: false,
              lowResWarning: false,
              shirtSourceId: 'shirt-cap-1',
              rawDataUrl: ONE_PX_PNG,
              width: 300,
              height: 190,
              suggestedName: 'Captura_Camiseta_1',
              suggestedViewport: { zoom: 0.75, panX: 0, panY: 77 },
            };
          }
          return {
            cancelled: false,
            target: 'save_png',
            captureWidth: 260,
            captureHeight: 310,
            drmWarning: false,
            lowResWarning: false,
            savedPath: 'D:\\Capturas\\Recorte_DF11.png',
            fileName: 'Recorte_DF11.png',
          };
        },
        load_raw_face_source: async (dataUrl: unknown, fileName: unknown) => {
          calls.push({ fn: 'load_raw_face_source', args: [dataUrl, fileName] });
          return {
            rawDataUrl: ONE_PX_PNG,
            width: 220,
            height: 260,
            isPreCutout: false,
            crownSrcY: 20,
            suggestedViewport: { zoom: 1.0, panX: 0, panY: 0 },
            fileName: String(fileName || 'Pasted.png'),
          };
        },
        open_capture_addon: async (defaultTarget: unknown, theme: unknown) => {
          calls.push({ fn: 'open_capture_addon', args: [defaultTarget, theme] });
          return { addonOpen: true, target: defaultTarget };
        },
        consume_addon_capture: async () => {
          calls.push({ fn: 'consume_addon_capture', args: [] });
          if (!addonPendingPayload) return null;
          const out = addonPendingPayload;
          addonPendingPayload = null;
          return out;
        },
        export_modular_card: async (payload: unknown) => {
          calls.push({ fn: 'export_modular_card', args: [payload] });
          const p = payload as { uid?: string; fileLabel?: string; fmt?: string };
          return { savedPath: `D:\\DF11Studio\\Exports\\${p.uid || p.fileLabel || 'DF11'}.${p.fmt || 'png'}` };
        },
        render_modular_preview: async () => ({ previewDataUrl: ONE_PX_PNG }),
      },
    };

    try {
      render(<StudioView clubs={CLUBS} exportDir="D:\\DF11Studio\\Exports" onExportDirChange={() => {}} initialJump={null} />);

      // 1. Esc cancellation is a clean no-op with zero error banners
      nextCancelled = true;
      fireEvent.click(screen.getByRole('button', { name: /Capturar pantalla/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'capture_screen_region')).toHaveLength(1));
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();

      // 2. Direct Photo capture with lowRes + DRM warnings populates Foto Directa + non-blocking advisory
      nextCancelled = false;
      nextLowRes = true;
      nextDrm = true;
      fireEvent.click(screen.getByRole('button', { name: /Opciones de captura de pantalla/i }));
      fireEvent.click(screen.getByRole('menuitem', { name: /Foto Directa \+ Marco DF11/i }));
      expect(await screen.findByText(/Activa: Captura_1/i)).toBeInTheDocument();
      expect(screen.getByText(/aceleración por hardware/i)).toBeInTheDocument();

      // 3. Guarded Ctrl+V: pasting while focused inside UID <input> MUST NOT hijack image paste onto canvas!
      const uidInput = screen.getByLabelText(/ID Football Manager/i);
      uidInput.focus();
      const fakeImgFile = new File([new Uint8Array([137, 80, 78, 71])], 'clip.png', { type: 'image/png' });
      fireEvent.paste(uidInput, {
        clipboardData: {
          items: [{ type: 'image/png', getAsFile: () => fakeImgFile }],
        },
      });
      await new Promise((r) => setTimeout(r, 40));
      expect(calls.filter((c) => c.fn === 'load_raw_face_source')).toHaveLength(0);

      // 4. Independent Shirt capture routes to Extraer Camiseta with headless auto-framed panY=77 and persists across tab switches!
      fireEvent.click(screen.getByRole('button', { name: /Opciones de captura de pantalla/i }));
      fireEvent.click(screen.getByRole('menuitem', { name: /Extraer Camiseta/i }));
      expect(await screen.findByAltText(/Encuadre previo de camiseta/i)).toBeInTheDocument();
      expect(screen.getByText(/X:0 Y:77/i)).toBeInTheDocument();

      // Switch back to Montaje Paso a Paso -> Captura_1 is STILL mounted, then return to Extraer Camiseta -> X:0 Y:77 is STILL preserved!
      fireEvent.click(screen.getByRole('tab', { name: /Montaje Paso a Paso/i }));
      expect(screen.getByText(/Activa: Captura_1/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('tab', { name: /Extraer Camiseta/i }));
      expect(screen.getByText(/X:0 Y:77/i)).toBeInTheDocument();

      // 5. FaceExtractorTool supports Ctrl+V image paste and independent 'Capturar cara'
      fireEvent.click(screen.getByRole('tab', { name: /Extraer Cara/i }));
      fireEvent.paste(window, {
        clipboardData: {
          items: [{ type: 'image/png', getAsFile: () => fakeImgFile }],
        },
      });
      expect(await screen.findByAltText(/Encuadre previo de cara/i)).toBeInTheDocument();
      expect(calls.filter((c) => c.fn === 'load_raw_face_source')).toHaveLength(1);

      // 6. Save PNG capture writes clean PNG without mutating active Studio composition
      fireEvent.click(screen.getByRole('button', { name: /Opciones de captura de pantalla/i }));
      fireEvent.click(screen.getByRole('menuitem', { name: /Guardar PNG como/i }));
      expect(await screen.findByText(/Recorte guardado: D:\\Capturas\\Recorte_DF11\.png/i)).toBeInTheDocument();

      // 7. Mini-Capturador flotante detaches with active tool target and routes incoming addon captures seamlessly
      fireEvent.click(screen.getByRole('button', { name: /Abrir Mini-Capturador flotante/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'open_capture_addon')).toHaveLength(1));
      expect(calls.find((c) => c.fn === 'open_capture_addon')?.args[0]).toBe('raw_face');

      addonPendingPayload = {
        cancelled: false,
        target: 'direct_photo',
        captureWidth: 260,
        captureHeight: 310,
        drmWarning: false,
        lowResWarning: false,
        directPhotoId: 'direct-addon-99',
        fileName: 'Captura_Flotante_99.png',
        label: 'Captura_Flotante_99',
        width: 260,
        height: 310,
        isPreCutout: false,
        clampPan: true,
        autoFit: { scale: 1.0, offsetX: 0, offsetY: 0 },
        previewDataUrl: ONE_PX_PNG,
      };
      window.dispatchEvent(new CustomEvent('df11:addon-capture'));
      expect(await screen.findByText(/Activa: Captura_Flotante_99/i)).toBeInTheDocument();

      // 8. Exporting captured Direct Photo to '1. Nuestras creaciones' does NOT require an official FM UID!
      expect(screen.getByLabelText(/ID Football Manager/i)).toHaveValue('');
      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'export_modular_card')).toHaveLength(1));
      expect(calls.find((c) => c.fn === 'export_modular_card')?.args[0]).toMatchObject({
        uid: '',
        fileLabel: 'Captura_Flotante_99',
        exportTarget: 'creations',
        step1Mode: 'direct_photo',
        directPhotoId: 'direct-addon-99',
        updateConfigXml: false,
      });
      expect(await screen.findByText(/Guardado: D:\\DF11Studio\\Exports\\Captura_Flotante_99\.png/i)).toBeInTheDocument();

      // Whereas '2. Pack de Faces FM' still requires the official FM UID when empty!
      fireEvent.click(screen.getByRole('button', { name: /Pack de Faces FM/i }));
      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11/i }));
      expect(await screen.findByText(/Introduce el ID asignado al futbolista para el Pack de Faces FM/i)).toBeInTheDocument();
      expect(calls.filter((c) => c.fn === 'export_modular_card')).toHaveLength(1);
    } finally {
      delete window.pywebview;
    }
  });

  it('supports DF11 Pure (220x276), Dual independent folder export, and explicit 1-click Direct Photo cutout without implicit AI', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    window.pywebview = {
      api: {
        list_shirt_templates: async () => [
          {
            templateId: 'Caucasian0',
            filename: 'Caucasian0.png',
            displayName: 'Blanca Real',
            category: 'player',
            clubId: '1736',
            collarWidth: 79,
            apexY: 229,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        list_saved_faces: async () => [
          {
            faceId: 'face_saved_1',
            filename: 'face_saved_1.png',
            name: 'Pedri',
            collarWidth: 78,
            apexY: 228,
            thumbDataUrl: ONE_PX_PNG,
          },
        ],
        load_saved_face: async (...args: unknown[]) => {
          calls.push({ fn: 'load_saved_face', args });
          return {
            headAssetId: 'head-saved-1',
            name: 'Pedri',
            isPreCutout: true,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0, neckFill: 1.0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        set_export_variant: async (...args: unknown[]) => {
          calls.push({ fn: 'set_export_variant', args });
          return { exportVariant: args[0] };
        },
        render_modular_preview: async (...args: unknown[]) => {
          calls.push({ fn: 'render_modular_preview', args });
          return { previewDataUrl: ONE_PX_PNG };
        },
        choose_directory: async (...args: unknown[]) => {
          calls.push({ fn: 'choose_directory', args });
          const kind = args[0];
          if (kind === 'facepack') {
            return {
              path: 'D:\\FM27\\graphics\\DF11_Classic',
              fmFacepackCollision: false,
            };
          }
          if (kind === 'facepack_pure') {
            return {
              path: 'D:\\FM27\\graphics\\DF11_Pure',
              fmFacepackCollision: true,
            };
          }
          return null;
        },
        pick_direct_photo_source: async (...args: unknown[]) => {
          calls.push({ fn: 'pick_direct_photo_source', args });
          return {
            directPhotoId: 'direct-opaque-1',
            fileName: 'Retrato_Opaco.jpg',
            label: 'Retrato_Opaco',
            width: 800,
            height: 600,
            isPreCutout: false,
            clampPan: true,
            autoFit: { scale: 1.0, offsetX: 0, offsetY: 0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        cutout_direct_photo_for_pure: async (...args: unknown[]) => {
          calls.push({ fn: 'cutout_direct_photo_for_pure', args });
          return {
            directPhotoId: 'direct-opaque-1',
            fileName: 'Retrato_Opaco.jpg',
            label: 'Retrato_Opaco',
            width: 800,
            height: 600,
            isPreCutout: true,
            clampPan: false,
            autoFit: { scale: 1.48, offsetX: 0, offsetY: 0 },
            previewDataUrl: ONE_PX_PNG,
          };
        },
        export_modular_card: async (...args: unknown[]) => {
          calls.push({ fn: 'export_modular_card', args });
          const p = (args[0] ?? {}) as Record<string, unknown>;
          if (p.exportVariant === 'dual') {
            return {
              savedPath: 'D:\\FM27\\graphics\\DF11_Classic\\29184012.png',
              savedPurePath: 'D:\\FM27\\graphics\\DF11_Pure\\29184012.png',
              exportVariant: 'dual',
              fmGraphicsCollision: true,
            };
          }
          return {
            savedPurePath: 'D:\\DF11Studio\\Exports\\000_DF11_Pure_Override\\Retrato_Opaco.png',
            exportVariant: 'pure',
            fmGraphicsCollision: false,
          };
        },
      },
    };

    try {
      render(
        <StudioView
          clubs={CLUBS}
          exportDir="D:\\DF11Studio\\Exports"
          exportPureDir="D:\\DF11Studio\\Exports\\000_DF11_Pure_Override"
          onExportDirChange={() => {}}
          initialJump={null}
        />,
      );

      const savedFaceBtn = await screen.findByTitle('Cargar Pedri');
      fireEvent.click(savedFaceBtn);
      expect(await screen.findByAltText('Previsualización DF11 260x310')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^JPG$/i })).toBeInTheDocument();

      // 1. Switch to Pure 220x276: hides JPG, renders 220x276 inset inside 260x310 stage, requests pure preview
      fireEvent.click(screen.getByRole('button', { name: /Pure 220×276/i }));
      expect(screen.queryByRole('button', { name: /^JPG$/i })).not.toBeInTheDocument();
      expect(screen.getByText(/Pure: Alfa = 0 \(sin fondo\)/i)).toBeInTheDocument();
      const pureImg = await screen.findByAltText('Previsualización DF11 Pure 220x276');
      expect(pureImg).toHaveClass('left-[20px]', 'top-[17px]', 'w-[220px]', 'h-[276px]');
      await waitFor(() =>
        expect(
          calls.some(
            (c) =>
              c.fn === 'render_modular_preview' &&
              (c.args[0] as Record<string, unknown>)?.previewVariant === 'pure',
          ),
        ).toBe(true),
      );

      // 2. Switch to Dual (Ambas): exposes Vista Classic | Vista Pure toggle and independent folder pickers
      fireEvent.click(screen.getByRole('button', { name: /Dual \(Ambas\)/i }));
      expect(screen.getByText(/Aplica a Classic · Pure siempre Alfa = 0/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Vista Classic/i }));
      expect(await screen.findByAltText('Previsualización DF11 260x310')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Vista Pure/i }));
      expect(await screen.findByAltText('Previsualización DF11 Pure 220x276')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Pack de Faces FM/i }));
      fireEvent.click(screen.getByRole('button', { name: /Elegir carpeta Pack Faces Classic/i }));
      await waitFor(() => expect(calls.some((c) => c.fn === 'choose_directory' && c.args[0] === 'facepack')).toBe(true));
      fireEvent.click(screen.getByRole('button', { name: /Elegir carpeta Pack Faces Pure/i }));
      await waitFor(() =>
        expect(calls.some((c) => c.fn === 'choose_directory' && c.args[0] === 'facepack_pure')).toBe(true),
      );
      expect(await screen.findByText(/Ambas carpetas cuelgan de/i)).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText(/ID Football Manager/i), { target: { value: '29184012' } });
      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11 Dual/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'export_modular_card')).toHaveLength(1));
      expect(calls.find((c) => c.fn === 'export_modular_card')?.args[0]).toMatchObject({
        uid: '29184012',
        exportTarget: 'facepack',
        exportVariant: 'dual',
        outDir: 'D:\\FM27\\graphics\\DF11_Classic',
        outPureDir: 'D:\\FM27\\graphics\\DF11_Pure',
      });
      expect(
        await screen.findByText(
          /Guardado Dual → Classic: D:\\FM27\\graphics\\DF11_Classic\\29184012\.png · Pure: D:\\FM27\\graphics\\DF11_Pure\\29184012\.png/i,
        ),
      ).toBeInTheDocument();

      // 3. Direct Photo opaque in Pure mode: 0% implicit AI on load, explicit 1-click cached cutout enables Pure export
      fireEvent.click(screen.getByRole('button', { name: /1\. Nuestras creaciones/i }));
      fireEvent.click(screen.getByRole('button', { name: /Pure 220×276/i }));
      fireEvent.change(screen.getByLabelText(/ID Football Manager/i), { target: { value: '' } });
      fireEvent.click(screen.getByRole('button', { name: /Foto Directa \+ Marco DF11/i }));
      fireEvent.click(screen.getByRole('button', { name: /Subir foto directa/i }));

      expect(await screen.findByText(/Activa: Retrato_Opaco/i)).toBeInTheDocument();
      expect(screen.getByAltText('Previsualización DF11 260x310')).toBeInTheDocument();
      expect(calls.filter((c) => c.fn === 'cutout_direct_photo_for_pure')).toHaveLength(0);

      const cutoutBtn = screen.getByRole('button', { name: /Recortar fondo para Pure \(IA · 1 vez\)/i });
      expect(cutoutBtn).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11 Pure/i }));
      expect(await screen.findByText(/En Foto Directa la imagen aún tiene fondo opaco/i)).toBeInTheDocument();
      expect(calls.filter((c) => c.fn === 'export_modular_card')).toHaveLength(1);

      fireEvent.click(cutoutBtn);
      await waitFor(() => expect(calls.filter((c) => c.fn === 'cutout_direct_photo_for_pure')).toHaveLength(1));
      expect(await screen.findByAltText('Previsualización DF11 Pure 220x276')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Recortar fondo para Pure \(IA · 1 vez\)/i })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Exportar DF11 Pure/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'export_modular_card')).toHaveLength(2));
      expect(await screen.findByText(/Guardado Pure: D:\\DF11Studio\\Exports\\000_DF11_Pure_Override\\Retrato_Opaco\.png/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });
});
