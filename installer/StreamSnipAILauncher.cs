using System;
using System.Diagnostics;
using System.IO;

internal static class StreamSnipAILauncher
{
    private static int Main()
    {
        string appDir = AppDomain.CurrentDomain.BaseDirectory;
        string runtimePython = Path.Combine(appDir, "runtime", "Scripts", "python.exe");
        string main = Path.Combine(appDir, "source", "autoclip.py");

        if (!File.Exists(runtimePython) || !File.Exists(main))
        {
            Console.Error.WriteLine("StreamSnip AI has not been initialized correctly.");
            Console.Error.WriteLine("Run the StreamSnip AI installer again to repair the installation.");
            Console.ReadKey();
            return 1;
        }

        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = runtimePython;
        start.Arguments = "\"" + main + "\"";
        start.WorkingDirectory = Path.GetDirectoryName(main);
        start.UseShellExecute = false;
        start.CreateNoWindow = false;

        try
        {
            using (Process app = Process.Start(start))
            {
                if (app == null)
                {
                    Console.Error.WriteLine("StreamSnip AI could not be started.");
                    Console.ReadKey();
                    return 1;
                }

                // Keep this console process alive as the app's supervisor.
                // The console closes automatically when the Python app exits.
                app.WaitForExit();
                return app.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("StreamSnip AI could not be started: " + error.Message);
            Console.ReadKey();
            return 1;
        }
    }
}
