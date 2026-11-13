import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { describe, expect, it, vi } from 'vitest';
import RegensSyncView from '../components/RegensSyncView';

const CLUBS = {
  '1736': { name: 'Real Madrid', pattern: 'solid', primary: '#F7F8FA', secondary: '#1E293B', collar: '#D4AF37' },
};

describe('RegensSyncView FM27 & NG_Regens contract', () => {
  it('renders OneDrive Steam/Epic vs Game Pass guidance when warning is active', async () => {
    render(
      <RegensSyncView
        clubs={CLUBS}
        vaultDir="D:\\DF11Studio\\NG_Regens_Vault"
        exportDir="C:\\Users\\user\\OneDrive\\Sports Interactive\\FM27"
        storageHealth={{
          target_path: 'C:\\Users\\user\\OneDrive\\Sports Interactive\\FM27',
          in_onedrive: true,
          free_gb: 40.0,
          warning: true,
          steam_launch_arg: '--user_data_location="D:\\FM27 Data"',
          gamepass_guide: 'En Xbox / Microsoft Store Game Pass desmarca Sports Interactive en OneDrive.',
        }}
        onVaultChange={() => {}}
        onExportChange={() => {}}
        onJumpToStudio={() => {}}
      />
    );
    expect(screen.getByText(/--user_data_location="D:\\FM27 Data"/i)).toBeInTheDocument();
    expect(screen.getByText(/Game Pass/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Bóveda sin regens/i)).toBeInTheDocument());
  });

  it('triggers 1-click jump into Studio when editing a discovered regen', async () => {
    const onJump = vi.fn();
    window.pywebview = {
      api: {
        scan_vault_summary: async () => ({ totalFound: 1, sample: [{ uid: 'r-2002049102', clubId: '1736' }] }),
        load_regen_into_studio: async (uid: unknown) => ({ uid, previewDataUrl: 'data:image/png;base64,AAA' }),
      },
    };
    render(
      <RegensSyncView
        clubs={CLUBS}
        vaultDir="D:\\DF11Studio\\NG_Regens_Vault"
        exportDir="D:\\FM27\\graphics"
        storageHealth={{
          target_path: 'D:\\FM27\\graphics',
          in_onedrive: false,
          free_gb: 654.0,
          warning: false,
          steam_launch_arg: '--user_data_location="D:\\FM27 Data"',
          gamepass_guide: 'Guía Game Pass',
        }}
        onVaultChange={() => {}}
        onExportChange={() => {}}
        onJumpToStudio={onJump}
      />
    );

    await waitFor(() => expect(screen.getByText('r-2002049102')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Editar en Estudio/i }));
    await waitFor(() => expect(onJump).toHaveBeenCalledWith(expect.objectContaining({ uid: 'r-2002049102' })));
    delete window.pywebview;
  });

  it('supports DF11 Pure & Dual NG_Regens batch sync with independent Pure folder and FM graphics collision warning', async () => {
    const calls: Array<{ fn: string; args: unknown[] }> = [];
    window.pywebview = {
      api: {
        scan_vault_summary: async () => ({
          totalFound: 2,
          sample: [
            { uid: 'r-2002049102', clubId: '1736' },
            { uid: 'r-2002049103', clubId: '' },
          ],
        }),
        set_export_variant: async (...args: unknown[]) => {
          calls.push({ fn: 'set_export_variant', args });
          return { exportVariant: args[0] };
        },
        choose_directory: async (...args: unknown[]) => {
          calls.push({ fn: 'choose_directory', args });
          return {
            path: 'D:\\FM27\\graphics\\000_DF11_Pure_Override',
            storageHealth: {
              target_path: 'D:\\FM27\\graphics\\000_DF11_Pure_Override',
              in_onedrive: false,
              free_gb: 640.0,
              warning: false,
              steam_launch_arg: '--user_data_location="D:\\FM27 Data"',
              gamepass_guide: 'Guía Game Pass',
            },
            fmGraphicsCollision: true,
          };
        },
        start_regens_sync: async (...args: unknown[]) => {
          calls.push({ fn: 'start_regens_sync', args });
          return {
            total_found: 2,
            processed: 2,
            skipped: 0,
            cancelled: false,
            aborted_by_shrink_guard: false,
          };
        },
      },
    };

    try {
      render(
        <RegensSyncView
          clubs={CLUBS}
          vaultDir="D:\\DF11Studio\\NG_Regens_Vault"
          exportDir="D:\\FM27\\graphics\\000_DF11_Regens_Override"
          exportPureDir="D:\\DF11Studio\\Exports\\000_DF11_Pure_Override"
          storageHealth={null}
          onVaultChange={() => {}}
          onExportChange={() => {}}
          onJumpToStudio={() => {}}
        />,
      );

      await waitFor(() => expect(screen.getByText('r-2002049102')).toBeInTheDocument());
      expect(screen.getByRole('button', { name: /Aplicar a selección \(0\)/i })).toBeDisabled();
      fireEvent.click(screen.getByRole('button', { name: /Dual \(Ambas\)/i }));
      await waitFor(() => expect(calls.some((c) => c.fn === 'set_export_variant' && c.args[0] === 'dual')).toBe(true));

      expect(screen.getByText(/2A\. Salida FM Classic/i)).toBeInTheDocument();
      expect(screen.getByText(/2B\. Salida FM Pure/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Elegir carpeta de salida Pure NG_Regens/i }));
      await waitFor(() =>
        expect(calls.some((c) => c.fn === 'choose_directory' && c.args[0] === 'export_pure')).toBe(true),
      );
      expect(await screen.findByText(/Ambas salidas cuelgan de/i)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /Convertir 2 regens \(Dual\)/i }));
      await waitFor(() => expect(calls.filter((c) => c.fn === 'start_regens_sync')).toHaveLength(1));
      expect(calls.find((c) => c.fn === 'start_regens_sync')?.args[0]).toMatchObject({
        variant: 'dual',
      });
      expect(await screen.findByText(/Sincronizados: 2 nuevos/i)).toBeInTheDocument();
    } finally {
      delete window.pywebview;
    }
  });
});
