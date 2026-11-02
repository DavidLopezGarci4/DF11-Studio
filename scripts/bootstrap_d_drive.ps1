$ErrorActionPreference = "Stop"

$StudioRoot = if ($env:DF11_STUDIO_ROOT) { $env:DF11_STUDIO_ROOT } else { "D:\DF11Studio" }
$Dirs = @(
    $StudioRoot,
    "$StudioRoot\python",
    "$StudioRoot\venv",
    "$StudioRoot\cache\uv",
    "$StudioRoot\cache\npm",
    "$StudioRoot\cache\vite",
    "$StudioRoot\models",
    "$StudioRoot\webview_profile",
    "$StudioRoot\web_toolchain",
    "$StudioRoot\NG_Regens_Vault"
)

foreach ($Dir in $Dirs) {
    if (-not (Test-Path $Dir)) {
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    }
}

$env:UV_PYTHON_INSTALL_DIR = "$StudioRoot\python"
$env:UV_CACHE_DIR = "$StudioRoot\cache\uv"

Write-Host "[1/3] Provisioning Python 3.12 in $StudioRoot\python ..."
uv python install 3.12

if (-not (Test-Path "$StudioRoot\venv\Scripts\python.exe")) {
    Write-Host "[2/3] Creating isolated venv in $StudioRoot\venv ..."
    uv venv "$StudioRoot\venv" --python 3.12
}

Write-Host "[2/3] Installing Python runtime + DirectML dependencies ..."
uv pip install --python "$StudioRoot\venv\Scripts\python.exe" `
    "pillow>=11.0.0" `
    "pillow-avif-plugin>=1.4.6" `
    "numpy>=1.26.4" `
    "onnxruntime-directml>=1.19.0" `
    "defusedxml>=0.7.1" `
    "pywebview>=5.3.0" `
    "pytest>=8.3.0"

$WebPkgPath = "$StudioRoot\web_toolchain\package.json"
$WebPkgJson = @'
{
  "name": "df11-studio-web-toolchain",
  "private": true,
  "type": "module",
  "dependencies": {
    "lucide-react": "^0.475.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.0.9",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.2.0",
    "@types/node": "^22.13.5",
    "@types/react": "^19.0.10",
    "@types/react-dom": "^19.0.4",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^26.0.0",
    "tailwindcss": "^4.0.9",
    "typescript": "^5.7.3",
    "vite": "^6.2.0",
    "vitest": "^3.0.7"
  }
}
'@
Set-Content -Path $WebPkgPath -Value $WebPkgJson -Encoding UTF8

if (-not (Test-Path "$StudioRoot\web_toolchain\node_modules\vite")) {
    Write-Host "[3/3] Installing isolated Web toolchain in $StudioRoot\web_toolchain ..."
    $env:npm_config_cache = "$StudioRoot\cache\npm"
    Push-Location "$StudioRoot\web_toolchain"
    try {
        npm install --no-audit --no-fund
    } finally {
        Pop-Location
    }
}

Write-Host "Bootstrap complete: $StudioRoot"
