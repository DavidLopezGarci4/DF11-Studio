"""Self-contained frameless HTML/CSS/JS for the always-on-top DF11 Floating Capture Add-on (536x52 px)."""

from __future__ import annotations

CAPTURE_ADDON_HTML = """<!doctype html>
<html lang="es" class="dark">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DF11 Mini-Capturador</title>
<style>
  :root {
    --bg: #ffffff;
    --surface: #f1f5f9;
    --border: #cbd5e1;
    --text: #0f172a;
    --muted: #64748b;
    --accent: #059669;
    --accent-hover: #10b981;
  }
  html.dark {
    --bg: #090d16;
    --surface: #0f172a;
    --border: #1e293b;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #059669;
    --accent-hover: #10b981;
  }
  * { box-sizing: border-box; user-select: none; -webkit-user-select: none; }
  html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  }
  .bar {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 5px;
    padding: 6px 8px;
    border: 1px solid var(--border);
    background: var(--bg);
  }
  .drag-grip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 6px 5px;
    border-radius: 6px;
    color: var(--muted);
    cursor: move;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.02em;
    flex-shrink: 0;
  }
  .drag-grip:hover { background: var(--surface); color: var(--text); }
  .cap-btn {
    border: none;
    border-radius: 7px;
    background: var(--accent);
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
    padding: 7px 10px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 120ms ease, opacity 120ms ease;
  }
  .cap-btn:hover:not(:disabled) { background: var(--accent-hover); }
  .cap-btn:disabled { opacity: 0.55; cursor: wait; }
  .seg {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 3px;
    border-radius: 7px;
    background: var(--surface);
    border: 1px solid var(--border);
    flex-shrink: 0;
  }
  .seg button {
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 11px;
    font-weight: 600;
    padding: 4px 6px;
    border-radius: 5px;
    cursor: pointer;
    white-space: nowrap;
    transition: all 120ms ease;
  }
  .seg button:hover { color: var(--text); }
  .seg button.active {
    background: var(--accent);
    color: #ffffff;
  }
  .icon-btn {
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--muted);
    width: 30px;
    height: 30px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 13px;
    flex-shrink: 0;
    transition: all 120ms ease;
  }
  .icon-btn:hover { color: var(--text); border-color: var(--accent); }
  .icon-btn.pinned {
    background: rgba(16, 185, 129, 0.16);
    color: #10b981;
    border-color: rgba(16, 185, 129, 0.45);
  }
</style>
</head>
<body>
  <div class="bar">
    <div class="drag-grip pywebview-drag-region" title="Arrastra esta barra flotante a cualquier rincón de tu pantalla">
      <span aria-hidden="true">⠿</span>
      <span>DF11</span>
    </div>

    <button id="capBtn" type="button" class="cap-btn" title="Recortar región de pantalla ahora (Shift fija proporción 260×310)">
      <span>✂</span>
      <span id="capLabel">Capturar</span>
    </button>

    <div class="seg" role="group" aria-label="Destino del recorte">
      <button type="button" data-target="direct_photo" data-bg="orig" class="active" title="Foto Directa · Mantener fondo original del recorte (0% IA)">Foto</button>
      <button type="button" data-target="direct_photo" data-bg="white" title="Foto Directa · Aplicar Capa Blanca Oficial DF11 (0% IA)">Blanco DF11</button>
      <button type="button" data-target="raw_face" title="Recortar Cara (Extractor)">Cara</button>
      <button type="button" data-target="raw_shirt" title="Extraer Camiseta (2× SSAA)">Camiseta</button>
      <button type="button" data-target="save_png" title="Guardar recorte como PNG">PNG</button>
    </div>

    <button id="pinBtn" type="button" class="icon-btn" title="Fijar barra: si está activo, permanece flotando tras capturar en vez de abrir el Estudio">
      📌
    </button>

    <button id="restoreBtn" type="button" class="icon-btn" title="Desplegar Estudio DF11 completo">
      ↗
    </button>
  </div>

  <script>
    (function () {
      var state = { target: 'direct_photo', directBgReplace: false, pinned: false, busy: false };
      var capBtn = document.getElementById('capBtn');
      var capLabel = document.getElementById('capLabel');
      var pinBtn = document.getElementById('pinBtn');
      var restoreBtn = document.getElementById('restoreBtn');
      var targetBtns = Array.prototype.slice.call(document.querySelectorAll('[data-target]'));

      function syncUI() {
        targetBtns.forEach(function (btn) {
          var btnTarget = btn.getAttribute('data-target');
          var btnBg = btn.getAttribute('data-bg');
          var isActive = false;
          if (btnTarget === 'direct_photo' && state.target === 'direct_photo') {
            isActive = btnBg === 'white' ? Boolean(state.directBgReplace) : !state.directBgReplace;
          } else {
            isActive = btnTarget === state.target;
          }
          btn.classList.toggle('active', isActive);
        });
        pinBtn.classList.toggle('pinned', state.pinned);
        capBtn.disabled = state.busy;
      }

      targetBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          state.target = btn.getAttribute('data-target') || 'direct_photo';
          var btnBg = btn.getAttribute('data-bg');
          if (state.target === 'direct_photo' && btnBg) {
            state.directBgReplace = btnBg === 'white';
          }
          syncUI();
        });
      });

      pinBtn.addEventListener('click', function () {
        state.pinned = !state.pinned;
        syncUI();
      });

      async function triggerCapture() {
        if (state.busy || !window.pywebview || !window.pywebview.api) return;
        state.busy = true;
        capLabel.textContent = '…';
        syncUI();
        try {
          var res = await window.pywebview.api.capture_from_addon(
            state.target,
            state.pinned,
            state.target === 'direct_photo' ? Boolean(state.directBgReplace) : null
          );
          if (res && !res.cancelled) {
            capLabel.textContent = '✓ Listo';
            setTimeout(function () { capLabel.textContent = 'Capturar'; }, 1100);
          } else {
            capLabel.textContent = 'Capturar';
          }
        } catch (_e) {
          capLabel.textContent = 'Capturar';
        } finally {
          state.busy = false;
          syncUI();
        }
      }

      capBtn.addEventListener('click', function () { void triggerCapture(); });

      restoreBtn.addEventListener('click', function () {
        if (window.pywebview && window.pywebview.api) {
          void window.pywebview.api.restore_from_capture_addon();
        }
      });

      window.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && window.pywebview && window.pywebview.api) {
          void window.pywebview.api.restore_from_capture_addon();
        }
      });

      window.__df11SetAddonState = function (target, theme, directBgReplace) {
        if (target) state.target = target;
        if (typeof directBgReplace === 'boolean') state.directBgReplace = directBgReplace;
        document.documentElement.classList.toggle('dark', theme !== 'light');
        syncUI();
      };

      window.__df11TriggerAddonCapture = function () {
        void triggerCapture();
      };

      syncUI();
    })();
  </script>
</body>
</html>
"""
