using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Windowing;

namespace StreamSnip_Desktop;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        Title = "StreamSnip AI";

        var frame = new Frame();
        Content = new Grid
        {
            Background = Application.Current.Resources["AppBackgroundBrush"] as Brush,
            Children = { frame }
        };
        frame.Navigate(typeof(MainPage));
        AppWindow.SetIcon("Assets/AppIcon.ico");

        // The studio is a media workspace; use the available desktop area by default.
        if (AppWindow.Presenter is OverlappedPresenter presenter)
            presenter.Maximize();
    }
}
