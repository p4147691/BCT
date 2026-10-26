using System;
internal static class NativeColorDecisionTest {
    private static void Check(bool value, bool expected, string name) {
        if (value != expected) throw new Exception(name);
        Console.WriteLine("PASS "+name);
    }
    public static int Main() {
        Check(DesktopSolidColorSource.ShouldUseSolid(false,true,false,false),false,"wrong GUID cannot inherit COM solid color");
        Check(DesktopSolidColorSource.ShouldUseSolid(false,false,true,false),false,"wrong GUID cannot inherit registry solid mode");
        Check(DesktopSolidColorSource.ShouldUseSolid(true,true,false,false),true,"active GUID COM says no wallpaper");
        Check(DesktopSolidColorSource.ShouldUseSolid(true,false,true,false),true,"active GUID Windows solid-mode setting");
        Check(DesktopSolidColorSource.ShouldUseSolid(true,false,false,true),true,"active GUID physical color proof");
        Check(DesktopSolidColorSource.ShouldUseSolid(true,false,false,false),false,"picture remains picture");
        Check(DesktopSolidColorSource.ShouldUseInheritedSolid(true,false,true),true,"unconfigured active desktop inherits current COM solid");
        Check(DesktopSolidColorSource.ShouldUseInheritedSolid(true,true,true),false,"configured photo desktop never inherits solid");
        Check(DesktopSolidColorSource.ShouldUseInheritedSolid(false,false,true),false,"inactive historical GUID never inherits solid");
        return 0;
    }
}
