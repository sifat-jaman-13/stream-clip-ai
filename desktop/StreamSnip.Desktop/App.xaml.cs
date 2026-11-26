using Windows.ApplicationModel;
using Windows.ApplicationModel.Activation;
using Windows.Foundation;
using Windows.Foundation.Collections;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using Microsoft.UI.Xaml.Shapes;
using System.Runtime.InteropServices;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace StreamSnip_Desktop;

/// <summary>
/// Provides application-specific behavior to supplement the default Application class.
/// </summary>
public partial class App : Application
{
    private Window? _window;
    private static string NativeDiagnosticsPath => System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "StreamSnip AI", "native-desktop-diagnostics.log");

    private static void WriteNativeDiagnostic(string message)
    {
        try
        {
            var directory = System.IO.Path.GetDirectoryName(NativeDiagnosticsPath);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);
            File.AppendAllText(NativeDiagnosticsPath,
                $"[{DateTimeOffset.Now:O}] {message}{Environment.NewLine}{Environment.NewLine}");
        }
        catch
        {
            // Diagnostics must never prevent startup or shutdown.
        }
    }
    private Mutex? _singleInstanceMutex;
    public static MainWindow? MainWindowInstance { get; private set; }

    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "MessageBoxW")]
    private static extern int ShowNativeMessage(IntPtr owner, string text, string caption, uint type);

    /// <summary>
    /// Initializes the singleton application object.  This is the first line of authored code
    /// executed, and as such is the logical equivalent of main() or WinMain().
    /// </summary>
    public App()
    {
        InitializeComponent();
        UnhandledException += (_, args) =>
        {
            WriteNativeDiagnostic("WinUI unhandled exception: " + args.Message +
                Environment.NewLine + args.Exception);
        };
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            WriteNativeDiagnostic("AppDomain unhandled exception: " + args.ExceptionObject);
        };
        TaskScheduler.UnobservedTaskException += (_, args) =>
        {
            WriteNativeDiagnostic("Unobserved task exception: " + args.Exception);
        };
    }

    /// <summary>
    /// Invoked when the application is launched.
    /// </summary>
    /// <param name="args">Details about the launch request and process.</param>
    protected override void OnLaunched(Microsoft.UI.Xaml.LaunchActivatedEventArgs args)
    {
        _singleInstanceMutex = new Mutex(true, @"Local\StreamSnipAI.NativeDesktop", out var isFirstInstance);
        if (!isFirstInstance)
        {
            ShowNativeMessage(IntPtr.Zero,
                "StreamSnip AI is already running. Use the existing window to continue.",
                "StreamSnip AI", 0x40);
            Exit();
            return;
        }

        try
        {
            var mainWindow = new MainWindow();
            MainWindowInstance = mainWindow;
            _window = mainWindow;
            _window.Activate();
        }
        catch (Exception ex)
        {
            WriteNativeDiagnostic("Native window construction failed: " + ex);
            ShowNativeMessage(IntPtr.Zero,
                "StreamSnip AI could not initialize its native desktop window.\n\n" +
                ex.GetType().Name + ": " + ex.Message +
                "\n\nDiagnostics: " + NativeDiagnosticsPath,
                "StreamSnip AI startup error", 0x10);
            Exit();
        }
    }
}
