$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    & "D:\DF11Studio\venv\Scripts\python.exe" "scripts\generate_icons.py"
    node --preserve-symlinks "D:\DF11Studio\web_toolchain\node_modules\vite\bin\vite.js" build --config "frontend/vite.config.ts"
    $csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    & $csc /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll "/win32icon:assets\icons\app.ico" "/out:DF11FaceStudio.exe" "scripts\Launcher.cs"
    Write-Host "Compilado DF11FaceStudio.exe v1.5.0 correctamente."
} finally {
    Pop-Location
}
