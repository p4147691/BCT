using System;
using System.Threading;
using Microsoft.Win32;
internal static class WallpaperRegistryWatcherFixture
{
    private const string Fixture = @"Software\BCTMonitorWallpaperWatchFixture_20261026";
    public static int Main()
    {
        using (RegistryKey existing = Registry.CurrentUser.OpenSubKey(Fixture))
          if (existing != null) throw new InvalidOperationException("REFUSE_EXISTING_FIXTURE");
        int events = 0;
        string from = "";
        var received = new ManualResetEvent(false);
        try
        {
            using (RegistryKey created = Registry.CurrentUser.CreateSubKey(Fixture))
            {
                if (created == null) throw new Exception("FIXTURE_CREATION_FAILED");
                MonitorWallpaperRegistryWatcher.Start(path => {from=path;Interlocked.Increment(ref events);received.Set();},Fixture);
                Thread.Sleep(350); // Test-only watcher registration barrier, never used by production.
                created.SetValue("Wallpaper", "BCT_E2E_"+Guid.NewGuid().ToString("N"),RegistryValueKind.String);
                if (!received.WaitOne(3500)) throw new Exception("REGISTRY_NOTIFICATION_NOT_RECEIVED");
                if (events != 1) throw new Exception("UNEXPECTED_WATCH_NOTIFICATION_COUNT:"+events);
                if (from != Fixture) throw new Exception("WATCHED_KEY_IDENTITY_MISMATCH");
                received.Reset();
                Thread.Sleep(50); // Test-only: registration should be armed; below previous 150ms window.
                created.SetValue("Wallpaper", "BCT_E2E_SECOND_"+Guid.NewGuid().ToString("N"),RegistryValueKind.String);
                if (!received.WaitOne(3500)) throw new Exception("SECOND_NOTIFICATION_NOT_RECEIVED");
                if (events != 2) throw new Exception("SEQUENTIAL_WALLPAPER_EVENTS_DROPPED:"+events);
                Console.WriteLine("PASS Native Registry notification delivered on exact owned fixture key; notifications="+events);
            }
        }
        finally { Registry.CurrentUser.DeleteSubKeyTree(Fixture, false); received.Dispose(); }
        return 0;
    }
}
