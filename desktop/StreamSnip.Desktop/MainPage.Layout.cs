using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace StreamSnip_Desktop;

public sealed partial class MainPage
{
    private static Grid AdaptiveColumns(
        FrameworkElement left,
        FrameworkElement right,
        double leftWeight = 1.0,
        double rightWeight = 1.0)
    {
        var grid = new Grid { ColumnSpacing = 20 };
        grid.ColumnDefinitions.Add(new ColumnDefinition
        {
            Width = new GridLength(leftWeight, GridUnitType.Star)
        });
        grid.ColumnDefinitions.Add(new ColumnDefinition
        {
            Width = new GridLength(rightWeight, GridUnitType.Star)
        });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        grid.Children.Add(left);
        grid.Children.Add(right);

        void ApplyBreakpoint(double width)
        {
            var stacked = width < 900;
            grid.ColumnSpacing = stacked ? 0 : 20;
            grid.RowSpacing = stacked ? 20 : 0;

            Grid.SetColumn(left, 0);
            Grid.SetRow(left, 0);
            Grid.SetColumnSpan(left, stacked ? 2 : 1);

            Grid.SetColumn(right, stacked ? 0 : 1);
            Grid.SetRow(right, stacked ? 1 : 0);
            Grid.SetColumnSpan(right, stacked ? 2 : 1);
        }

        grid.SizeChanged += (_, args) => ApplyBreakpoint(args.NewSize.Width);
        grid.Loaded += (_, _) => ApplyBreakpoint(grid.ActualWidth);
        return grid;
    }
}
