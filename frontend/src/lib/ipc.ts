export type TemplateCategory = 'player' | 'staff';
export type Step1Mode = 'modular' | 'direct_photo';
export type CaptureTarget = 'direct_photo' | 'raw_face' | 'raw_shirt' | 'save_png';
export interface SaveProfileInfo { saveId: string; displayName: string; isActive: boolean; }
export interface ClubSeed { name: string; pattern: string; primary: string; secondary: string; collar: string; }
export interface StorageHealth { target_path: string; in_onedrive: boolean; free_gb: number; warning: boolean; steam_launch_arg: string; gamepass_guide: string; }
export interface BootstrapState {
  version: string;
  clubs: Record<string, ClubSeed>;
  vaultDir: string;
  exportDir: string;
  facepackDir?: string;
  storageHealth: StorageHealth;
  hasModels: boolean;
  liveWatching?: boolean;
  captureHotkey?: boolean;
  activeSaveId?: string;
  saveProfiles?: SaveProfileInfo[];
  theme?: 'dark' | 'light';
}

export interface ScreenCaptureMeta {
  cancelled: boolean;
  target?: CaptureTarget;
  captureWidth?: number;
  captureHeight?: number;
  drmWarning?: boolean;
  lowResWarning?: boolean;
  savedPath?: string;
  fileName?: string;
}

export type ScreenCapturePayload = ScreenCaptureMeta &
  Partial<DirectPhotoResponse> &
  Partial<StagedFaceResponse> &
  Partial<StagedShirtResponse>;

const NON_TEXT_INPUT_TYPES = new Set(['range', 'checkbox', 'radio', 'button', 'color', 'file']);

export function isTextEntryTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.tagName !== 'string') return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName.toLowerCase();
  if (tag === 'textarea' || tag === 'select') return true;
  if (tag === 'input') {
    const inpType = ((el as HTMLInputElement).type || 'text').toLowerCase();
    return !NON_TEXT_INPUT_TYPES.has(inpType);
  }
  return false;
}

export function dataUrlToFile(dataUrl: string, fallbackName = 'DragBrowser.png'): File | null {
  const comma = dataUrl.indexOf(',');
  if (!dataUrl.startsWith('data:image/') || comma < 0) return null;
  try {
    const mimeMatch = /^data:(image\/[a-zA-Z0-9.+-]+);base64$/i.exec(dataUrl.slice(0, comma));
    const mime = mimeMatch ? mimeMatch[1] : 'image/png';
    const bin = atob(dataUrl.slice(comma + 1));
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) arr[i] = bin.charCodeAt(i);
    return new File([arr], fallbackName, { type: mime });
  } catch {
    return null;
  }
}

export function resolveDroppedImageTransfer(dt: DataTransfer | null): { file: File | null; blockedRemoteUrl: boolean } {
  if (!dt) return { file: null, blockedRemoteUrl: false };
  const direct = dt.files?.[0];
  if (direct) return { file: direct, blockedRemoteUrl: false };
  const uri = (dt.getData?.('text/uri-list') || '').trim().split(/\r?\n/)[0]?.trim() || '';
  if (uri.startsWith('data:image/')) {
    return { file: dataUrlToFile(uri), blockedRemoteUrl: false };
  }
  const html = dt.getData?.('text/html') || '';
  const srcMatch = /<img[^>]+src=["']([^"']+)["']/i.exec(html);
  const src = srcMatch?.[1]?.trim() || uri;
  if (src.startsWith('data:image/')) {
    return { file: dataUrlToFile(src), blockedRemoteUrl: false };
  }
  if (/^https?:\/\//i.test(src)) {
    return { file: null, blockedRemoteUrl: true };
  }
  return { file: null, blockedRemoteUrl: false };
}

export interface ShirtTemplateInfo {
  templateId: string;
  filename: string;
  displayName: string;
  clubId: string;
  clubName?: string;
  season?: string;
  category?: TemplateCategory;
  isActiveForClub?: boolean;
  collarWidth: number;
  apexY: number;
  thumbDataUrl: string;
}

export interface SavedFaceInfo {
  faceId: string;
  name: string;
  kind: string;
  thumbDataUrl: string;
}

export interface CropViewportDTO {
  zoom: number;
  panX: number;
  panY: number;
}

export interface StagedFaceResponse {
  rawDataUrl: string;
  width: number;
  height: number;
  isPreCutout: boolean;
  crownSrcY: number;
  suggestedViewport: CropViewportDTO;
  fileName?: string;
}

export interface StagedShirtResponse {
  shirtSourceId?: string;
  rawDataUrl: string;
  width: number;
  height: number;
  suggestedName: string;
  suggestedViewport: CropViewportDTO;
}

export interface ExtractedFaceResponse {
  headAssetId: string;
  suggestedName: string;
  headPreviewDataUrl: string;
  autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
  previewDataUrl: string;
}

export interface DirectPhotoResponse {
  directPhotoId: string;
  fileName?: string;
  label: string;
  detectedUid?: string;
  width: number;
  height: number;
  isPreCutout: boolean;
  clampPan: boolean;
  autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
  previewDataUrl: string;
}

export interface FacepackRemixResponse {
  remixMode: 'swap_shirt' | 'swap_face';
  detectedUid?: string;
  cardLabel: string;
  facepackDir?: string;
  headAssetId?: string;
  templateId?: string;
  isPreCutout?: boolean;
  adhocShirtId?: string;
  adhocShirtLabel?: string;
  adhocShirtThumbDataUrl?: string;
  collarWidth?: number;
  apexY?: number;
  autoFit: { scale: number; offsetX: number; offsetY: number; neckFill: number };
  previewDataUrl: string;
}

declare global {
  interface Window {
    pywebview?: { api: Record<string, (...args: unknown[]) => Promise<unknown>> };
    chrome?: { webview?: unknown };
  }
}

const FALLBACK_BOOT: BootstrapState = {
  version: '1.5.0',
  clubs: {
    '1736': { name: 'Real Madrid', pattern: 'solid', primary: '#F7F8FA', secondary: '#1E293B', collar: '#D4AF37' },
    '1708': { name: 'FC Barcelona', pattern: 'stripes', primary: '#004D98', secondary: '#A50044', collar: '#EDBB00' },
    '1744': { name: 'Rayo Vallecano', pattern: 'sash', primary: '#F8FAFC', secondary: '#D91A2A', collar: '#D91A2A' },
  },
  vaultDir: 'D:\\DF11Studio\\NG_Regens_Vault',
  exportDir: 'D:\\DF11Studio\\Exports\\000_DF11_Regens_Override',
  storageHealth: { target_path: 'D:\\DF11Studio\\Exports\\000_DF11_Regens_Override', in_onedrive: false, free_gb: 654.0, warning: false, steam_launch_arg: '--user_data_location="D:\\FM27 Data"', gamepass_guide: 'Desmarca Sports Interactive en Ajustes de OneDrive.' },
  hasModels: true,
};

let pywebviewWaitPromise: Promise<void> | null = null;

function isNativeWebViewHost(): boolean {
  if (typeof window === 'undefined') return false;
  return Boolean(window.chrome?.webview) || window.location?.protocol === 'file:';
}

function waitForPywebviewApi(timeoutMs = 1800): Promise<void> {
  if (typeof window === 'undefined' || window.pywebview?.api || !isNativeWebViewHost()) {
    return Promise.resolve();
  }
  if (pywebviewWaitPromise) return pywebviewWaitPromise;
  pywebviewWaitPromise = new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      pywebviewWaitPromise = null;
      window.removeEventListener('pywebviewready', finish);
      window.clearInterval(pollId);
      window.clearTimeout(timerId);
      resolve();
    };
    window.addEventListener('pywebviewready', finish, { once: true });
    const pollId = window.setInterval(() => {
      if (window.pywebview?.api) finish();
    }, 15);
    const timerId = window.setTimeout(finish, timeoutMs);
  });
  return pywebviewWaitPromise;
}

export async function callBridge<T>(method: string, ...args: unknown[]): Promise<T> {
  if (!window.pywebview?.api) {
    await waitForPywebviewApi();
  }
  if (window.pywebview?.api?.[method]) return (await window.pywebview.api[method](...args)) as T;
  if (method === 'get_bootstrap_state') return FALLBACK_BOOT as unknown as T;
  if (method === 'probe_architecture_health') return null as unknown as T;
  if (method === 'list_shirt_templates' || method === 'list_saved_faces') return [] as unknown as T;
  if (
    !window.pywebview?.api &&
    (method.startsWith('load_raw_') ||
      method.startsWith('load_direct_') ||
      method.startsWith('pick_direct_') ||
      method.startsWith('load_facepack_') ||
      method.startsWith('pick_facepack_') ||
      method.startsWith('preview_shirt_') ||
      method.startsWith('save_shirt_') ||
      method === 'save_adhoc_shirt_template' ||
      method === 'switch_facepack_remix_mode' ||
      method.startsWith('delete_shirt_') ||
      method.startsWith('set_active_club_') ||
      method.startsWith('upsert_custom_club') ||
      method === 'update_shirt_template_meta' ||
      method === 'import_clubs_from_fm_graphics' ||
      method === 'capture_screen_region' ||
      method.startsWith('extract_face_'))
  ) {
    throw new Error('Ejecuta DF11FaceStudio.exe para procesar imágenes con el motor nativo.');
  }
  return {} as T;
}
