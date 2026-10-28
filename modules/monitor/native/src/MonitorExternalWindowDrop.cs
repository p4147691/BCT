using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Threading;
using System.Windows.Forms;

// Owns the external Windows-window-to-thumbnail drop contract. The page
// supplies only current thumbnail rectangles; no wallpaper or browser content
// is read or modified here.
internal static class MonitorExternalWindowDrop
{
    private const int DwmWindowBorderColor = 34;
    private const uint DefaultBorderColor = 0xFFFFFFFFu;
    // COLORREF is 0x00BBGGRR: electric blue.
    private const uint TargetBorderColor = 0x00FF8F18u;
    private const int MaxTargets = 32;
    private static readonly object Gate = new object();
    private static IntPtr monitorHost = IntPtr.Zero;
    private static readonly List<Target> Targets = new List<Target>();
    private static IntPtr activeWindow = IntPtr.Zero;
    private static string activeDesktopId = "";

    [DllImport("user32.dll")] private static extern bool GetCursorPos(out PointNative point);
    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hWnd);
    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(IntPtr hWnd, int attribute, ref uint value, int size);

    [StructLayout(LayoutKind.Sequential)]
    private struct PointNative { public int X, Y; }

    private sealed class Target
    {
        internal string DesktopId;
        internal int Left;
        internal int Top;
        internal int Right;
        internal int Bottom;

        internal bool Contains(PointNative point)
        {
            return point.X >= Left && point.X < Right && point.Y >= Top && point.Y < Bottom;
        }
    }

    internal static object Handle(Dictionary<string, object> request)
    {
        if (request == null || Field(request, "type") != "setExternalWindowDropTargets") return Receipt(false, "INVALID_EXTERNAL_DROP_OPERATION", 0);
        long rawHost;
        if (!long.TryParse(Field(request, "hostWindowHwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out rawHost) || rawHost <= 0) return Receipt(false, "INVALID_MONITOR_HOST", 0);
        double scale;
        if (!double.TryParse(Field(request, "screenScale"), NumberStyles.Float, CultureInfo.InvariantCulture, out scale) || scale < .5 || scale > 4.0) return Receipt(false, "INVALID_SCREEN_SCALE", 0);

        object rawTargets;
        var accepted = new List<Target>();
        if (request.TryGetValue("targets", out rawTargets) && rawTargets is IEnumerable)
        {
            foreach (object item in (IEnumerable)rawTargets)
            {
                if (accepted.Count >= MaxTargets) break;
                var map = item as Dictionary<string, object>;
                if (map == null) continue;
                string desktopId = Field(map, "desktopId").ToLowerInvariant();
                if (!IsGuid(desktopId)) continue;
                double left, top, width, height;
                if (!Number(map, "left", out left) || !Number(map, "top", out top) || !Number(map, "width", out width) || !Number(map, "height", out height)) continue;
                int physicalLeft = (int)Math.Round(left * scale);
                int physicalTop = (int)Math.Round(top * scale);
                int physicalWidth = (int)Math.Round(width * scale);
                int physicalHeight = (int)Math.Round(height * scale);
                if (physicalWidth < 16 || physicalHeight < 16 || physicalWidth > 16384 || physicalHeight > 16384) continue;
                accepted.Add(new Target { DesktopId = desktopId, Left = physicalLeft, Top = physicalTop, Right = physicalLeft + physicalWidth, Bottom = physicalTop + physicalHeight });
            }
        }

        lock (Gate)
        {
            monitorHost = new IntPtr(rawHost);
            Targets.Clear();
            Targets.AddRange(accepted);
            if (activeWindow != IntPtr.Zero) UpdateTargetLocked(activeWindow);
        }
        return Receipt(true, "TARGETS_ACCEPTED", accepted.Count);
    }

    internal static void OnMoveStart(IntPtr hWnd)
    {
        lock (Gate)
        {
            if (hWnd == IntPtr.Zero || hWnd == monitorHost || Targets.Count == 0) return;
            activeWindow = hWnd;
            activeDesktopId = "";
            ExternalGlowOverlay.Hide();
            UpdateTargetLocked(hWnd);
        }
    }

    internal static void OnMoveLocation(IntPtr hWnd)
    {
        lock (Gate) { if (hWnd != IntPtr.Zero && hWnd == activeWindow) UpdateTargetLocked(hWnd); }
    }

    internal static void OnMoveEnd(IntPtr hWnd)
    {
        string targetDesktopId = "";
        lock (Gate)
        {
            if (hWnd == IntPtr.Zero || hWnd != activeWindow) return;
            UpdateTargetLocked(hWnd);
            targetDesktopId = activeDesktopId;
            SetTargetBorder(hWnd, false);
            ExternalGlowOverlay.Hide();
            activeWindow = IntPtr.Zero;
            activeDesktopId = "";
        }
        if (targetDesktopId.Length == 0) return;

        var moved = MonitorDesktopHost.MoveExternalWindowToDesktop(new Dictionary<string, object> {
            { "hwnd", hWnd.ToInt64().ToString(CultureInfo.InvariantCulture) }, { "desktopId", targetDesktopId }
        }) as Dictionary<string, object>;
        bool ok = moved != null && moved.ContainsKey("ok") && Convert.ToBoolean(moved["ok"], CultureInfo.InvariantCulture);
        MonitorDesktopHost.EmitMonitorEvent(new Dictionary<string, object> {
            { "type", "externalWindowDropFinished" }, { "event", true },
            { "hwnd", hWnd.ToInt64().ToString(CultureInfo.InvariantCulture) }, { "desktopId", targetDesktopId }, { "ok", ok }
        });
    }

    private static void UpdateTargetLocked(IntPtr hWnd)
    {
        string nextDesktopId = "";
        PointNative point;
        if (GetCursorPos(out point)) foreach (Target target in Targets) if (target.Contains(point)) { nextDesktopId = target.DesktopId; break; }
        if (nextDesktopId == activeDesktopId) return;
        activeDesktopId = nextDesktopId;
        SetTargetBorder(hWnd, nextDesktopId.Length > 0);
        MonitorDesktopHost.EmitMonitorEvent(new Dictionary<string, object> {
            { "type", "externalWindowDropTargetChanged" }, { "event", true },
            { "hwnd", hWnd.ToInt64().ToString(CultureInfo.InvariantCulture) }, { "desktopId", nextDesktopId }, { "active", nextDesktopId.Length > 0 }
        });
    }

    private static void SetTargetBorder(IntPtr hWnd, bool active)
    {
        if (hWnd == IntPtr.Zero || !IsWindow(hWnd)) return;
        uint color = active ? TargetBorderColor : DefaultBorderColor;
        try { DwmSetWindowAttribute(hWnd, DwmWindowBorderColor, ref color, 4); } catch { }
        if (active) ExternalGlowOverlay.ShowFor(hWnd); else ExternalGlowOverlay.Hide();
    }

    private static bool IsGuid(string value) { Guid parsed; return Guid.TryParse(value, out parsed); }

    private static bool Number(Dictionary<string, object> map, string key, out double value)
    {
        value = 0; object raw;
        return map != null && map.TryGetValue(key, out raw) && raw != null
            && double.TryParse(Convert.ToString(raw, CultureInfo.InvariantCulture), NumberStyles.Float, CultureInfo.InvariantCulture, out value)
            && !double.IsNaN(value) && !double.IsInfinity(value);
    }

    private static string Field(Dictionary<string, object> map, string key)
    {
        object raw;
        return map != null && map.TryGetValue(key, out raw) && raw != null ? Convert.ToString(raw, CultureInfo.InvariantCulture).Trim() : "";
    }

    private static object Receipt(bool ok, string detail, int targets)
    {
        return new Dictionary<string, object> { { "ok", ok }, { "detail", detail }, { "targets", targets } };
    }
}

// Draws outside the real window, so the highlighted app stays interactive and
// visible. The overlay is click-through and exists only while an external
// window drag is over a valid Monitor desktop target.
internal static class ExternalGlowOverlay
{
    private const int WmNcHitTest = 0x0084;
    private const int HtTransparent = -1;
    private static readonly object Gate = new object();
    private static IntPtr targetWindow = IntPtr.Zero;
    private static Thread thread;

    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hWnd, out RectNative rect);
    [DllImport("user32.dll")] private static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);

    [StructLayout(LayoutKind.Sequential)]
    private struct RectNative { internal int Left, Top, Right, Bottom; }

    internal static void ShowFor(IntPtr hWnd)
    {
        lock (Gate)
        {
            targetWindow = hWnd;
            EnsureThread();
        }
    }

    internal static void Hide()
    {
        lock (Gate) { targetWindow = IntPtr.Zero; }
    }

    private static void EnsureThread()
    {
        if (thread != null && thread.IsAlive) return;
        thread = new Thread(Run);
        thread.Name = "MonitorExternalWindowGlow";
        thread.IsBackground = true;
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
    }

    private static void Run()
    {
        try
        {
            try { SetThreadDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }
            using (var context = new ApplicationContext())
            using (var glow = new GlowForm())
            using (var timer = new System.Windows.Forms.Timer())
            {
                timer.Interval = 24;
                timer.Tick += delegate
                {
                    IntPtr hWnd;
                    lock (Gate) { hWnd = targetWindow; }
                    RectNative rect;
                    if (hWnd == IntPtr.Zero || !IsWindow(hWnd) || !GetWindowRect(hWnd, out rect))
                    {
                        if (glow.Visible) glow.Hide();
                        return;
                    }
                    int width = Math.Max(1, rect.Right - rect.Left);
                    int height = Math.Max(1, rect.Bottom - rect.Top);
                    glow.Bounds = new Rectangle(rect.Left, rect.Top, width, height);
                    if (!glow.Visible) glow.Show();
                    glow.Invalidate();
                };
                timer.Start();
                Application.Run(context);
            }
        }
        catch (Exception)
        {
            lock (Gate) { targetWindow = IntPtr.Zero; }
        }
    }

    private sealed class GlowForm : Form
    {
        internal GlowForm()
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            AutoScaleMode = AutoScaleMode.None;
            TopMost = true;
            // A short-lived whole-window tint is substantially easier to see
            // than a thin outline, without taking mouse input from the source.
            BackColor = Color.FromArgb(0, 145, 255);
            Opacity = .16;
            DoubleBuffered = true;
        }

        protected override bool ShowWithoutActivation { get { return true; } }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams parameters = base.CreateParams;
                parameters.ExStyle |= 0x08000000 | 0x00000080 | 0x00000020;
                return parameters;
            }
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == WmNcHitTest) { message.Result = new IntPtr(HtTransparent); return; }
            base.WndProc(ref message);
        }

        protected override void OnPaint(PaintEventArgs paint)
        {
            base.OnPaint(paint);
            // The form itself is the tint; drawing no extra perimeter avoids
            // the purple-looking nested outline produced by color-key forms.
        }
    }
}
