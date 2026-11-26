using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

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
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 40, 44, 52)),
            Children = { frame }
        };
        frame.Navigate(typeof(MainPage));
        AppWindow.SetIcon("Assets/AppIcon.ico");
    }
}
