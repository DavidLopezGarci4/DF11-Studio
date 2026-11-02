export interface ClubSeed { name: string; pattern: string; primary: string; secondary: string; collar: string; }
export interface StorageHealth { target_path: string; in_onedrive: boolean; free_gb: number; warning: boolean; steam_launch_arg: string; gamepass_guide: string; }
export interface BootstrapState { version: string; clubs: Record<string, ClubSeed>; vaultDir: string; exportDir: string; storageHealth: StorageHealth; hasModels: boolean; liveWatching?: boolean; }

declare global {
  interface Window { pywebview?: { api: Record<string, (...args: unknown[]) => Promise<unknown>> }; }
}

const FALLBACK_BOOT: BootstrapState = {
  version: '1.0.0',
  clubs: {
    '1736': { name: 'Real Madrid', pattern: 'solid', primary: '#F7F8FA', secondary: '#1E293B', collar: '#D4AF37' },
    '1708': { name: 'FC Barcelona', pattern: 'stripes', primary: '#004D98', secondary: '#A50044', collar: '#EDBB00' },
  },
  vaultDir: 'D:\\DF11Studio\\NG_Regens_Vault',
  exportDir: 'D:\\DF11Studio\\Exports\\000_DF11_Regens_Override',
  storageHealth: { target_path: 'D:\\DF11Studio\\Exports\\000_DF11_Regens_Override', in_onedrive: false, free_gb: 654.0, warning: false, steam_launch_arg: '--user_data_location="D:\\FM27 Data"', gamepass_guide: 'Desmarca Sports Interactive en Ajustes de OneDrive.' },
  hasModels: true,
};

export async function callBridge<T>(method: string, ...args: unknown[]): Promise<T> {
  if (window.pywebview?.api?.[method]) return (await window.pywebview.api[method](...args)) as T;
  if (method === 'get_bootstrap_state') return FALLBACK_BOOT as unknown as T;
  if (method === 'probe_architecture_health') return null as unknown as T;
  return {} as T;
}
