using System;
using System.Globalization;
using System.Runtime.InteropServices;

// Reads the one global Windows background mode and base color. Per-desktop
// picture assignment remains owned by DesktopVisualSnapshot. This adapter uses
// only official read methods and never guesses from pixels or writes settings.
internal sealed class DesktopGlobalBackgroundState
{
    internal bool IsSolid;
    internal string BaseColor = "";
    internal string Proof = "";
}

internal static class DesktopBackgroundStateSource
{
    [ComImport, Guid("B92B56A9-8B55-4E14-9A89-0199BBB6F93B"),
      InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IDesktopWallpaperReadOnly
    {
        // Setter slots are declared only to preserve the official COM vtable.
        // This class never invokes either setter.
        [PreserveSig] int SetWallpaper([MarshalAs(UnmanagedType.LPWStr)] string monitor, [MarshalAs(UnmanagedType.LPWStr)] string wallpaper);
        [PreserveSig] int GetWallpaper([MarshalAs(UnmanagedType.LPWStr)] string monitor, [MarshalAs(UnmanagedType.LPWStr)] out string wallpaper);
        [PreserveSig] int GetMonitorDevicePathAt(uint index, [MarshalAs(UnmanagedType.LPWStr)] out string monitor);
        [PreserveSig] int GetMonitorDevicePathCount(out uint count);
        [PreserveSig] int GetMonitorRECT([MarshalAs(UnmanagedType.LPWStr)] string monitor, out RECT bounds);
        [PreserveSig] int SetBackgroundColor(uint color);
        [PreserveSig] int GetBackgroundColor(out uint color);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int left, top, right, bottom; }

    internal static bool ShouldUseSolid(uint monitorCount, uint emptyWallpaperCount, bool backgroundColorAvailable)
    {
        return monitorCount > 0 && emptyWallpaperCount == monitorCount && backgroundColorAvailable;
    }

    internal static bool TryGet(out DesktopGlobalBackgroundState state)
    {
        state = null;
        object instance = null;
        try
        {
            Type clsid = Type.GetTypeFromCLSID(new Guid("C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD"), true);
            instance = Activator.CreateInstance(clsid);
            IDesktopWallpaperReadOnly api = (IDesktopWallpaperReadOnly)instance;

            uint monitorCount;
            if (api.GetMonitorDevicePathCount(out monitorCount) != 0 || monitorCount < 1 || monitorCount > 8) return false;
            uint emptyWallpaperCount = 0;
            for (uint index = 0; index < monitorCount; index++)
            {
                string monitor;
                string wallpaper;
                if (api.GetMonitorDevicePathAt(index, out monitor) != 0 || string.IsNullOrWhiteSpace(monitor)) return false;
                if (api.GetWallpaper(monitor, out wallpaper) != 0) return false;
                if (string.IsNullOrEmpty(wallpaper)) emptyWallpaperCount++;
            }

            uint color;
            bool colorAvailable = api.GetBackgroundColor(out color) == 0;
            if (!colorAvailable) return false;

            state = new DesktopGlobalBackgroundState
            {
                IsSolid = ShouldUseSolid(monitorCount, emptyWallpaperCount, colorAvailable),
                BaseColor = string.Format(
                    CultureInfo.InvariantCulture,
                    "#{0:X2}{1:X2}{2:X2}",
                    color & 255,
                    (color >> 8) & 255,
                    (color >> 16) & 255),
                Proof = "windows-desktopwallpaper-global-state"
            };
            return true;
        }
        catch { return false; }
        finally
        {
            if (instance != null) try { Marshal.FinalReleaseComObject(instance); } catch { }
        }
    }
}
