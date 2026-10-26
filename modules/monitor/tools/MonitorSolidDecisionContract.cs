using System;
internal static class NativeColorDecisionTest {
    private static void Check(bool value, bool expected, string name) {
        if (value != expected) throw new Exception(name);
        Console.WriteLine("PASS "+name);
    }
    public static int Main() {
        Check(DesktopSolidColorSource.ShouldUseGlobalSolid(false,true,false),false,"historical GUID cannot receive global COM solid");
        Check(DesktopSolidColorSource.ShouldUseGlobalSolid(false,false,true),false,"historical GUID cannot receive global registry solid");
        Check(DesktopSolidColorSource.ShouldUseGlobalSolid(true,true,false),true,"active GUID receives global COM solid");
        Check(DesktopSolidColorSource.ShouldUseGlobalSolid(true,false,true),true,"active GUID receives global registry solid");
        Check(DesktopSolidColorSource.ShouldUseGlobalSolid(true,false,false),false,"picture mode remains picture");
        Check(DesktopSolidColorSource.ShouldUseSampledSolid(false,true),false,"screen sample cannot describe another GUID");
        Check(DesktopSolidColorSource.ShouldUseSampledSolid(true,true),true,"screen sample may prove exact current GUID");
        Check(DesktopSolidColorSource.ShouldUseSampledSolid(true,false),false,"unmatched screen sample is rejected");
        Check(DesktopSolidColorSource.ShouldUseGlobalSolid(true,true,true),true,"global solid ignores dormant photo registry path");
        return 0;
    }
}
