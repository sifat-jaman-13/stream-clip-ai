using System;
using System.Diagnostics;
using System.IO;

internal static class StreamSnipAILauncher
{
    private static int Main()
    {
        string appDir = AppDomain.CurrentDomain.BaseDirectory;
        string setup = Path.Combine(appDir, "setup_windows.ps1");
        if (!File.Exists(setup))
        {
            Console.Error.WriteLine("StreamSnip AI setup script was not found.");
            Console.ReadKey();
            return 1;
        }

        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = "powershell.exe";
        start.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + setup + "\" -AppDir \"" + appDir.TrimEnd('\\') + "\"";
        start.WorkingDirectory = appDir;
        start.UseShellExecute = true;
        start.Verb = "open";
        return Process.Start(start) == null ? 1 : 0;
    }
}
