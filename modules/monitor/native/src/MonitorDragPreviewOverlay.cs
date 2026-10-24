using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

internal static class MonitorDragPreviewOverlay
{
    private const int VkLeftButton = 0x01;
    private const int WmNcHitTest = 0x0084;
    private const int HtTransparent = -1;
    private static readonly object Gate = new object();
    private static string tokenActive = "";
    private static string labelActive = "";
    private static IntPtr sourceHwnd = IntPtr.Zero;
    private static Thread thread;

    [DllImport("user32.dll")] private static extern bool GetCursorPos(out PointNative point);
    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int virtualKey);
    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hWnd, out RectNative rect);
    [DllImport("user32.dll")] private static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);

    [StructLayout(LayoutKind.Sequential)]
    private struct PointNative { public int X, Y; }

    [StructLayout(LayoutKind.Sequential)]
    private struct RectNative { public int Left, Top, Right, Bottom; }

    internal static object Handle(Dictionary<string, object> request)
    {
        string operation = Field(request, "type");
        string token = Field(request, "token");
        if (string.IsNullOrWhiteSpace(token) || token.Length > 100) return Receipt(false, "INVALID_PREVIEW_TOKEN");

        lock (Gate)
        {
            if (operation == "monitorDragPreviewStop")
            {
                if (tokenActive == token) tokenActive = "";
                return Receipt(true, "STOP_ACCEPTED");
            }
            if (operation != "monitorDragPreviewStart") return Receipt(false, "INVALID_PREVIEW_OPERATION");

            labelActive = Field(request, "label").Replace('\r', ' ').Replace('\n', ' ').Trim();
            if (labelActive.Length > 90) labelActive = labelActive.Substring(0, 90);
            if (labelActive.Length == 0) labelActive = "노드 이동 중";
            long rawHwnd;
            sourceHwnd = long.TryParse(Field(request, "sourceHwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out rawHwnd) && rawHwnd > 0
                ? new IntPtr(rawHwnd)
                : IntPtr.Zero;
            tokenActive = token;
            EnsureThread();
            return Receipt(true, "START_ACCEPTED");
        }
    }

    private static void EnsureThread()
    {
        if (thread != null && thread.IsAlive) return;
        thread = new Thread(Run);
        thread.Name = "MonitorDragPreview";
        thread.IsBackground = true;
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
    }

    private static void Run()
    {
        try
        {
            try { SetThreadDpiAwarenessContext(new IntPtr(-4)); }
            catch (EntryPointNotFoundException) { }

            using (var context = new ApplicationContext())
            using (var popup = new PreviewForm())
            using (var timer = new System.Windows.Forms.Timer())
            {
                timer.Interval = 16;
                timer.Tick += delegate
                {
                    string token;
                    string label;
                    IntPtr hWnd;
                    lock (Gate) { token = tokenActive; label = labelActive; hWnd = sourceHwnd; }
                    if (token.Length == 0)
                    {
                        if (popup.Visible) popup.Hide();
                        timer.Interval = 250;
                        return;
                    }
                    timer.Interval = 16;
                    if ((GetAsyncKeyState(VkLeftButton) & 0x8000) == 0)
                    {
                        lock (Gate) { if (tokenActive == token) tokenActive = ""; }
                        if (popup.Visible) popup.Hide();
                        MonitorDesktopHost.EmitMonitorEvent(new Dictionary<string, object> {
                            { "type", "monitorDragPreviewReleased" }, { "event", true }, { "token", token }
                        });
                        return;
                    }

                    PointNative cursor;
                    if (!GetCursorPos(out cursor))
                    {
                        if (popup.Visible) popup.Hide();
                        return;
                    }

                    RectNative sourceRect;
                    if (hWnd != IntPtr.Zero && IsWindow(hWnd) && GetWindowRect(hWnd, out sourceRect) &&
                        cursor.X >= sourceRect.Left && cursor.X < sourceRect.Right &&
                        cursor.Y >= sourceRect.Top && cursor.Y < sourceRect.Bottom)
                    {
                        if (popup.Visible) popup.Hide();
                        return;
                    }

                    Rectangle screen = Screen.FromPoint(new Point(cursor.X, cursor.Y)).Bounds;
                    int width = Math.Min(270, Math.Max(110, screen.Width - 12));
                    int height = Math.Min(42, Math.Max(24, screen.Height - 12));
                    int x = Math.Max(screen.Left, Math.Min(screen.Right - width, cursor.X + 16));
                    int y = Math.Max(screen.Top, Math.Min(screen.Bottom - height, cursor.Y + 18));
                    popup.Label = label;
                    popup.Bounds = new Rectangle(x, y, width, height);
                    if (!popup.Visible) popup.Show();
                    popup.Invalidate();
                };
                timer.Start();
                Application.Run(context);
            }
        }
        catch (Exception)
        {
            lock (Gate) { tokenActive = ""; }
        }
    }

    private static string Field(Dictionary<string, object> request, string key)
    {
        object value;
        return request != null && request.TryGetValue(key, out value) && value != null
            ? Convert.ToString(value, CultureInfo.InvariantCulture)
            : "";
    }

    private static object Receipt(bool ok, string detail)
    {
        return new Dictionary<string, object> { { "ok", ok }, { "detail", detail } };
    }

    private sealed class PreviewForm : Form
    {
        internal string Label = "";

        internal PreviewForm()
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            AutoScaleMode = AutoScaleMode.None;
            TopMost = true;
            BackColor = Color.FromArgb(18, 32, 48);
            Opacity = .88;
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
            if (message.Msg == WmNcHitTest)
            {
                message.Result = new IntPtr(HtTransparent);
                return;
            }
            base.WndProc(ref message);
        }

        protected override void OnPaint(PaintEventArgs paint)
        {
            base.OnPaint(paint);
            Rectangle border = ClientRectangle;
            border.Width -= 1;
            border.Height -= 1;
            using (var pen = new Pen(Color.FromArgb(159, 231, 255), 2f))
                paint.Graphics.DrawRectangle(pen, border);
            using (var font = new Font("Malgun Gothic", 9f, FontStyle.Bold))
            using (var brush = new SolidBrush(Color.White))
                paint.Graphics.DrawString(Label, font, brush,
                    new RectangleF(8, 6, Math.Max(1, Width - 16), Math.Max(1, Height - 12)));
        }
    }
}
