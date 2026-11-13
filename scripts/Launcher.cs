using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("DF11 Face Studio")]
[assembly: AssemblyDescription("Estudio Modular DF11 por Capas y Sincronizador NG_Regens / FM27")]
[assembly: AssemblyCompany("DF11 Face Studio Local")]
[assembly: AssemblyProduct("DF11 Face Studio")]
[assembly: AssemblyVersion("1.6.1.0")]
[assembly: AssemblyFileVersion("1.6.1.0")]

namespace DF11FaceStudio
{
    internal static class Launcher
    {
        [STAThread]
        private static int Main()
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            string studioRoot = Environment.GetEnvironmentVariable("DF11_STUDIO_ROOT");
            if (string.IsNullOrWhiteSpace(studioRoot))
            {
                studioRoot = @"D:\DF11Studio";
            }

            string pythonw = Path.Combine(studioRoot, "venv", "Scripts", "pythonw.exe");
            string entryScript = Path.Combine(appDir, "run_desktop.py");

            if (!File.Exists(pythonw) || !File.Exists(entryScript))
            {
                MessageBox.Show(
                    "No se encontró el entorno aislado en " + studioRoot + ".\n\n" +
                    "Ejecuta primero: powershell -ExecutionPolicy Bypass -File scripts\\bootstrap_d_drive.ps1",
                    "DF11 Face Studio v1.6.1",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
                return 1;
            }

            string profileDir = Path.Combine(studioRoot, "webview_profile");
            Directory.CreateDirectory(profileDir);

            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = pythonw,
                Arguments = "\"" + entryScript + "\"",
                WorkingDirectory = appDir,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            psi.EnvironmentVariables["DF11_STUDIO_ROOT"] = studioRoot;
            psi.EnvironmentVariables["WEBVIEW2_USER_DATA_FOLDER"] = profileDir;

            try
            {
                Process.Start(psi);
                return 0;
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "Error al iniciar DF11 Face Studio:\n" + ex.Message,
                    "DF11 Face Studio v1.6.1",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return 2;
            }
        }
    }
}
