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
});
