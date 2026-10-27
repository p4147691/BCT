using System;

internal static class MonitorBackgroundStateDecisionContract
{
    private static void Check(bool value, bool expected, string name)
    {
        if (value != expected) throw new Exception(name);
        Console.WriteLine("PASS " + name);
    }

    public static int Main()
    {
        Check(DesktopBackgroundStateSource.ShouldUseSolid(1, 1, true), true, "one empty monitor path proves solid mode");
        Check(DesktopBackgroundStateSource.ShouldUseSolid(2, 2, true), true, "all empty monitor paths prove solid mode");
        Check(DesktopBackgroundStateSource.ShouldUseSolid(2, 1, true), false, "any displayed wallpaper keeps picture mode");
        Check(DesktopBackgroundStateSource.ShouldUseSolid(1, 1, false), false, "missing color evidence fails closed");
        Check(DesktopBackgroundStateSource.ShouldUseSolid(0, 0, true), false, "missing monitor evidence fails closed");
        return 0;
    }
}
