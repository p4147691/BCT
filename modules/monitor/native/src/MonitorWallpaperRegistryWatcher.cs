using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

// Native wallpaper event watcher: no message pump requirement and no timer polling.
// Keep the Windows wallpaper registry inputs read-only; only report a change.
internal static class MonitorWallpaperRegistryWatcher
{
    private static readonly IntPtr CurrentUser = new IntPtr(unchecked((int)0x80000001));
    private const int KeyNotify = 0x0010;
    private const uint NameChanged = 0x00000001;
    private const uint ValueChanged = 0x00000004;
    private const int Success = 0;
    private static long lastObservedEventTicks;

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, EntryPoint = "RegOpenKeyExW")]
    private static extern int RegOpenKeyEx(IntPtr key, string path, int options, int access, out IntPtr opened);
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern int RegNotifyChangeKeyValue(IntPtr key, bool subtree, uint filter, IntPtr signalEvent, bool asynchronous);
    [DllImport("advapi32.dll")]
    private static extern int RegCloseKey(IntPtr key);

    internal static void Start(Action<string> changed, params string[] watchedPaths)
    {
        if (changed == null) throw new ArgumentNullException("changed");
        string[] paths = watchedPaths != null && watchedPaths.Length > 0
            ? watchedPaths
            : new [] {
                @"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops\Desktops",
                @"Control Panel\Desktop"
              };
        foreach (string rawPath in paths)
        {
            string keyPath = rawPath;
            if (string.IsNullOrWhiteSpace(keyPath)) continue;
            var thread = new Thread(() => Watch(keyPath, changed));
            thread.IsBackground = true;
            thread.Name = "BCTWallpaperRegistry:" + (keyPath.EndsWith("Desktops", StringComparison.OrdinalIgnoreCase) ? "virtual" : "global");
            thread.Start();
        }
    }

    private static void Watch(string keyPath, Action<string> changed)
    {
        IntPtr key = IntPtr.Zero;
        if (RegOpenKeyEx(CurrentUser, keyPath, 0, KeyNotify, out key) != Success || key == IntPtr.Zero)
            return; // No registry writes, no synthetic notification.
        try
        {
            while (true)
            {
                // Synchronously block on the OS registry notification. Rearm exactly
                // once AFTER the previous change; no periodic reads, sleeps or retries.
                int result = RegNotifyChangeKeyValue(key, true, NameChanged | ValueChanged, IntPtr.Zero, false);
                if (result != Success) return;
                long now = DateTime.UtcNow.Ticks;
                long previous = Interlocked.Read(ref lastObservedEventTicks);
                // Windows may change several theme values together. Coalesce duplicate
                // native signals only; the next distinct change is still observed.
                if (now - previous > TimeSpan.TicksPerMillisecond * 150 &&
                    Interlocked.CompareExchange(ref lastObservedEventTicks, now, previous) == previous)
                {
                    try { changed(keyPath); } catch { /* do not crash Native host */ }
                }
            }
        }
        finally { RegCloseKey(key); }
    }
}
