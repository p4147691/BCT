using System;




using System.Collections.Generic;




using System.Diagnostics;




using System.Drawing;




using System.Net;




using System.Drawing.Imaging;




using System.Globalization;
using System.Linq;




using System.Windows.Forms;




using System.Windows.Automation;




using System.IO;




using System.Runtime.InteropServices;




using System.Text;




using System.Threading;




using System.Web.Script.Serialization;




using Microsoft.Win32;









internal static class MonitorDesktopHost




{




    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    private static readonly Semaphore WindowCaptureSlots = new Semaphore(2, 2, @"Local\DesktopWindowMonitorWgcCaptureSlots");
    private const string WgcCaptureHelperName = "DesktopWindowMonitorWgcSnapshot.exe";
    private const int WgcCaptureQueueWaitMs = 6000;
    private const int WgcCaptureProcessWaitMs = 7000;




    private const string VdKey = @"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops";




private const string NaverProfileDirectory = @"D:\AI_TOOLS\CHATGPT-NAVER-PROFILE";









    private const string RdcRoot = @"D:\AI_TOOLS\DesktopCommander";
    private const string RdcManualStartScript = @"D:\AI_TOOLS\DesktopCommander\Start-DesktopCommanderRemote-Manual.ps1";
    private const string RdcStopScript = @"D:\AI_TOOLS\DesktopCommander\Stop-DesktopCommanderRemote.ps1";
    private const string RdcMutexName = @"Local\DesktopCommanderRemoteWatchdog";

    private const string ChatGptUrl = "https://chatgpt.com/";

    private static readonly string SharedNotePath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DesktopWindowMonitor", "shared-note.txt");




    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);




    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);




    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);




    [DllImport("user32.dll")] private static extern int GetWindowTextLength(IntPtr hWnd);




    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);




    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hWnd);




    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hWnd);




    [DllImport("user32.dll")] private static extern IntPtr GetAncestor(IntPtr hWnd, uint gaFlags);




    [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr hWnd);




    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();




    [DllImport("user32.dll")] private static extern bool GetCursorPos(out POINT point);




    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int virtualKey);




    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hWnd, int command);




    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint flags);




    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);




    [DllImport("user32.dll")] private static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);




    private const int VK_SHIFT = 0x10;




    private const uint SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010, WM_CLOSE = 0x0010;




    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr hWnd, StringBuilder className, int maxCount);

    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);









    private delegate void WinEventDelegate(IntPtr hWinEventHook, uint eventType, IntPtr hWnd, int idObject, int idChild, uint eventThread, uint eventTime);




    [DllImport("user32.dll")] private static extern IntPtr SetWinEventHook(uint eventMin, uint eventMax, IntPtr hmodWinEventProc, WinEventDelegate callback, uint processId, uint threadId, uint flags);




    private const uint EVENT_SYSTEM_FOREGROUND = 0x0003, EVENT_SYSTEM_MOVESIZESTART = 0x000A, EVENT_SYSTEM_MOVESIZEEND = 0x000B, EVENT_SYSTEM_MINIMIZESTART = 0x0016, EVENT_SYSTEM_MINIMIZEEND = 0x0017;




    private const uint EVENT_OBJECT_SHOW = 0x8002, EVENT_OBJECT_HIDE = 0x8003, EVENT_OBJECT_LOCATIONCHANGE = 0x800B, EVENT_OBJECT_CLOAKED = 0x8017, EVENT_OBJECT_UNCLOAKED = 0x8018;




    private const uint WINEVENT_OUTOFCONTEXT = 0x0000, WINEVENT_SKIPOWNPROCESS = 0x0002;




    private static readonly object NativeWriteLock = new object();




    private static Stream NativeOutput;




    private static WinEventDelegate MoveSizeEndCallback;




    private static WinEventDelegate LocationChangeCallback;




    private static WinEventDelegate CloakChangeCallback;




    private static WinEventDelegate LifecycleChangeCallback;

    private static WinEventDelegate ForegroundChangeCallback;




    private static readonly object WindowEventLock = new object();




    private static readonly HashSet<long> ActiveMoveSizeWindows = new HashSet<long>();




    private static readonly Dictionary<long, System.Threading.Timer> WindowSettleTimers = new Dictionary<long, System.Threading.Timer>();




    [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(IntPtr hWnd, int attribute, out int value, int size);




    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(IntPtr hWnd, int attribute, ref uint value, int size);




    [StructLayout(LayoutKind.Sequential)] private struct RECT { public int Left, Top, Right, Bottom; }




    [StructLayout(LayoutKind.Sequential)] private struct POINT { public int X, Y; }




    [StructLayout(LayoutKind.Sequential)] private struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }




    [ComImport, Guid("A5CD92FF-29BE-454C-8D04-D82879FB3F1B"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]




    private interface IVirtualDesktopManager { bool IsWindowOnCurrentVirtualDesktop(IntPtr topLevelWindow); Guid GetWindowDesktopId(IntPtr topLevelWindow); void MoveWindowToDesktop(IntPtr topLevelWindow, [MarshalAs(UnmanagedType.LPStruct)] Guid desktopId); }




    [ComImport, Guid("AA509086-5CA9-4C25-8F95-589D3C07B48A")] private class VirtualDesktopManagerCom { }




    [DllImport("VirtualDesktopAccessor.dll", CallingConvention = CallingConvention.Cdecl, EntryPoint = "GetDesktopCount")]




    private static extern int VdaGetDesktopCount();




    [DllImport("VirtualDesktopAccessor.dll", CallingConvention = CallingConvention.Cdecl, EntryPoint = "CreateDesktop")]




    private static extern int VdaCreateDesktop();




    [DllImport("VirtualDesktopAccessor.dll", CallingConvention = CallingConvention.Cdecl, EntryPoint = "RemoveDesktop")]




    private static extern int VdaRemoveDesktop(int removeDesktopNumber, int fallbackDesktopNumber);




    [DllImport("VirtualDesktopAccessor.dll", CallingConvention = CallingConvention.Cdecl, EntryPoint = "MoveWindowToDesktopNumber")]




    private static extern int VdaMoveWindowToDesktopNumber(IntPtr hWnd, int desktopNumber);




    [DllImport("VirtualDesktopAccessor.dll", CallingConvention = CallingConvention.Cdecl, EntryPoint = "GoToDesktopNumber")]




    private static extern int VdaGoToDesktopNumber(int desktopNumber);









    private static long NativeParentWindowHwnd()




    {




        foreach (string arg in Environment.GetCommandLineArgs())




        {




            if (!arg.StartsWith("--parent-window=", StringComparison.OrdinalIgnoreCase)) continue;




            long value; if (long.TryParse(arg.Substring("--parent-window=".Length), NumberStyles.Integer, CultureInfo.InvariantCulture, out value) && value > 0) return value;




        }




        return 0;




    }









    private static string NativeHostProfileId()




    {




        long raw = NativeParentWindowHwnd(); if (raw <= 0) return "UNKNOWN";




        IntPtr hWnd = new IntPtr(raw); if (!IsWindow(hWnd)) return "UNKNOWN";




        IntPtr root = GetAncestor(hWnd, 2); if (root != IntPtr.Zero && IsWindow(root)) hWnd = root;




        int length = GetWindowTextLength(hWnd); if (length <= 0) return "UNKNOWN";




        var buffer = new StringBuilder(length + 1); GetWindowText(hWnd, buffer, buffer.Capacity);




        string title = buffer.ToString().Trim();




        int i = title.Length - 1;




        while (i >= 0 && char.IsDigit(title[i])) i--;




        if (i >= 0 && i < title.Length - 1)




        {




            char marker = char.ToUpperInvariant(title[i]);




            if (marker == 'G') return "GOOGLE";




            if (marker == 'N') return "NAVER";




        }




        return "UNKNOWN";




    }









    public static int Main()




    {




        Stream input = Console.OpenStandardInput();




        Stream output = Console.OpenStandardOutput();




        NativeOutput = output;




        StartMoveSizeEndEvents();




        while (true)




        {




            byte[] header = ReadExact(input, 4);




            if (header == null) return 0;




            int length = BitConverter.ToInt32(header, 0);




            byte[] payload = ReadExact(input, length);




            if (payload == null) return 1;




            object response;




            try




            {




                var request = Json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(payload));




                response = DesktopVisualSnapshot.CanHandle(request)
                    ? DesktopVisualSnapshot.Handle(request)
                    : Handle(request);




            }




            catch (Exception ex) { response = Error(ex.Message); }




            Write(output, response);




        }




    }









    private static void StartMoveSizeEndEvents()




    {




        var thread = new Thread(() => {




            MoveSizeEndCallback = OnWindowMoveEvent;




            LocationChangeCallback = OnWindowLocationChange;




            CloakChangeCallback = OnWindowCloakChange;




            LifecycleChangeCallback = OnWindowLifecycleChange;

            ForegroundChangeCallback = OnWindowForegroundChange;

            IntPtr foregroundHook = SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, IntPtr.Zero, ForegroundChangeCallback, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);




            IntPtr moveHook = SetWinEventHook(EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND, IntPtr.Zero, MoveSizeEndCallback, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);




            IntPtr minimizeHook = SetWinEventHook(EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND, IntPtr.Zero, LifecycleChangeCallback, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);




            IntPtr showHideHook = SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE, IntPtr.Zero, LifecycleChangeCallback, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);




            IntPtr locationHook = SetWinEventHook(EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE, IntPtr.Zero, LocationChangeCallback, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);




            IntPtr cloakHook = SetWinEventHook(EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED, IntPtr.Zero, CloakChangeCallback, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);




            if (foregroundHook != IntPtr.Zero || moveHook != IntPtr.Zero || minimizeHook != IntPtr.Zero || showHideHook != IntPtr.Zero || locationHook != IntPtr.Zero || cloakHook != IntPtr.Zero) Application.Run();




        });




        thread.IsBackground = true;




        thread.SetApartmentState(ApartmentState.STA);




        thread.Start();




    }









    private static bool IsObservedTopLevelWindow(IntPtr hWnd)




    {




        if (hWnd == IntPtr.Zero || !IsWindow(hWnd)) return false;




        IntPtr root = GetAncestor(hWnd, 2); if (root != IntPtr.Zero && root != hWnd) return false;




        var classBuffer = new StringBuilder(128); GetClassName(hWnd, classBuffer, classBuffer.Capacity);




        string className = classBuffer.ToString();




        if (className == "Progman" || className == "WorkerW" || className == "Shell_TrayWnd") return false;




        int length = GetWindowTextLength(hWnd); if (length <= 0) return false;




        var titleBuffer = new StringBuilder(length + 1); GetWindowText(hWnd, titleBuffer, titleBuffer.Capacity);




        string title = titleBuffer.ToString().Trim();




        return title.Length > 0 && !title.StartsWith("DesktopWindow Monitor", StringComparison.OrdinalIgnoreCase) && !title.StartsWith("DWM ·", StringComparison.OrdinalIgnoreCase);




    }









    private static void OnWindowMoveEvent(IntPtr hook, uint eventType, IntPtr hWnd, int idObject, int idChild, uint eventThread, uint eventTime)




    {




        try {




            if (!IsObservedTopLevelWindow(hWnd)) return;




            long key = hWnd.ToInt64();




            if (eventType == EVENT_SYSTEM_MOVESIZESTART) { lock (WindowEventLock) ActiveMoveSizeWindows.Add(key); return; }




            lock (WindowEventLock) ActiveMoveSizeWindows.Remove(key);




            EmitWindowSettled(hWnd, "movesizeend");




        } catch { }




    }









    private static void OnWindowLocationChange(IntPtr hook, uint eventType, IntPtr hWnd, int idObject, int idChild, uint eventThread, uint eventTime)




    {




        try {




            if (idObject != 0 || !IsObservedTopLevelWindow(hWnd)) return;




            lock (WindowEventLock) if (ActiveMoveSizeWindows.Contains(hWnd.ToInt64())) return;




            ScheduleWindowSettled(hWnd, "locationchange", 85);




        } catch { }




    }









    private static void OnWindowCloakChange(IntPtr hook, uint eventType, IntPtr hWnd, int idObject, int idChild, uint eventThread, uint eventTime)




    {




        try {




            if (idObject != 0 || !IsObservedTopLevelWindow(hWnd)) return;




            ScheduleWindowSettled(hWnd, eventType == EVENT_OBJECT_CLOAKED ? "cloaked" : "uncloaked", 55);




        } catch { }




    }









    private static void OnWindowLifecycleChange(IntPtr hook, uint eventType, IntPtr hWnd, int idObject, int idChild, uint eventThread, uint eventTime)




    {




        try {




            if (!IsObservedTopLevelWindow(hWnd)) return;




            if ((eventType == EVENT_OBJECT_SHOW || eventType == EVENT_OBJECT_HIDE) && idObject != 0) return;




            string reason = eventType == EVENT_SYSTEM_MINIMIZESTART ? "minimized" : eventType == EVENT_SYSTEM_MINIMIZEEND ? "restored" : eventType == EVENT_OBJECT_SHOW ? "shown" : "hidden";




            ScheduleWindowSettled(hWnd, reason, reason == "restored" || reason == "shown" ? 90 : 35);




        } catch { }




    }




    private static void ScheduleWindowSettled(IntPtr hWnd, string reason, int delayMs)




    {




        long key = hWnd.ToInt64();




        lock (WindowEventLock) {




            System.Threading.Timer oldTimer;




            if (WindowSettleTimers.TryGetValue(key, out oldTimer)) { try { oldTimer.Dispose(); } catch { } }




            System.Threading.Timer timer = null;




            timer = new System.Threading.Timer(_ => {




                lock (WindowEventLock) { WindowSettleTimers.Remove(key); try { timer.Dispose(); } catch { } }




                EmitWindowSettled(hWnd, reason);




            }, null, delayMs, System.Threading.Timeout.Infinite);




            WindowSettleTimers[key] = timer;




        }




    }









    private static void EmitWindowSettled(IntPtr hWnd, string reason)




    {




        try {




            if (!IsObservedTopLevelWindow(hWnd)) return;




            var classBuffer = new StringBuilder(128); GetClassName(hWnd, classBuffer, classBuffer.Capacity);




            int length = GetWindowTextLength(hWnd); var titleBuffer = new StringBuilder(Math.Max(2, length + 1)); GetWindowText(hWnd, titleBuffer, titleBuffer.Capacity);




            string title = titleBuffer.ToString();




            RECT rect; if (!GetWindowRect(hWnd, out rect)) return;




            int width = rect.Right - rect.Left, height = rect.Bottom - rect.Top; if (width < 2 || height < 2) return;




            Guid desktopId = ((IVirtualDesktopManager)new VirtualDesktopManagerCom()).GetWindowDesktopId(hWnd);




            Rectangle virtualScreen = SystemInformation.VirtualScreen; Rectangle previewScreen = Screen.AllScreens.Length == 1 ? Screen.PrimaryScreen.WorkingArea : virtualScreen;




            var message = new Dictionary<string, object> { { "type", "windowMoveSizeEnd" }, { "event", true }, { "reason", reason }, { "hwnd", hWnd.ToInt64().ToString(CultureInfo.InvariantCulture) }, { "desktopId", desktopId.ToString() }, { "title", title }, { "className", classBuffer.ToString() }, { "left", rect.Left }, { "top", rect.Top }, { "width", width }, { "height", height }, { "visible", IsWindowVisible(hWnd) }, { "iconic", IsIconic(hWnd) }, { "previewVirtualLeft", previewScreen.Left }, { "previewVirtualTop", previewScreen.Top }, { "previewVirtualWidth", previewScreen.Width }, { "previewVirtualHeight", previewScreen.Height }, { "at", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() } };




            Stream output = NativeOutput; if (output != null) Write(output, message);




        } catch { }




    }









    internal static void EmitMonitorEvent(Dictionary<string, object> message)
    {
        Stream output = NativeOutput;
        if (output != null) Write(output, message);
    }

    private static object Handle(Dictionary<string, object> request)




    {




        string type = GetString(request, "type");

        if (type == "monitorDragPreviewStart" || type == "monitorDragPreviewStop") return MonitorDragPreviewOverlay.Handle(request);




        if (type == "getVirtualDesktops") return GetState(request);




        if (type == "getDeploymentInfo") return GetDeploymentInfo();

        if (type == "recoverBctCore") return RecoverBoundedService("BCT Core Supervisor", true);

        if (type == "recoverMcpTunnel") return RecoverBoundedService("BCT Tunnel Supervisor", false);
        if (type == "getRdcRemoteStatus") return GetRdcRemoteStatus();
        if (type == "startRdcRemote") return StartRdcRemote();
        if (type == "stopRdcRemote") return StopRdcRemote();




    if (type == "getSharedMonitorSelection") return GetSharedMonitorSelection();




    if (type == "setSharedMonitorSelection") return SetSharedMonitorSelection(request);




if (type == "getSharedMonitorRuntime") return GetSharedMonitorRuntime();




    if (type == "setSharedMonitorRuntime") return SetSharedMonitorRuntime(request);




        if (type == "ackExtensionReload") return AckExtensionReload(request);




        if (type == "getDesktopWindows") return GetDesktopWindows(request);




        if (type == "getDesktopWindowHandles") return GetDesktopWindowHandles(request);




        if (type == "getAllChromeWindowHandles") return GetAllChromeWindowHandles();




        if (type == "getForegroundWindow") return GetForegroundWindowInfo();




        if (type == "setWindowBorderHighlight") return SetWindowBorderHighlight(request);




        if (type == "getChromeConversationIdentity") return GetChromeConversationIdentity(request);




        if (type == "getDesktopWallpaperInfo") return GetDesktopWallpaperInfo(request);




        if (type == "captureWindow") return CaptureWindow(request);
        if (type == "captureCurrentDesktopWallpaper") return CaptureCurrentDesktopWallpaper(request);




        if (type == "createVirtualDesktop") return CreateVirtualDesktop();




        if (type == "removeVirtualDesktop") return RemoveVirtualDesktop(request);




        if (type == "restoreVirtualDesktop") return RestoreVirtualDesktop(request);




        if (type == "moveWindowToDesktop") return MoveWindowToDesktop(request);




if (type == "launchChatGptWindowCopy") return LaunchChatGptWindowCopy(request);




        if (type == "setWindowBoundsNoActivate") return SetWindowBoundsNoActivate(request);




        if (type == "restoreForegroundWindow") return RestoreForegroundWindow(request);


        if (type == "getCodexRuntimeStatus") return GetCodexRuntimeStatus(request);




        if (type == "closeWindow") return CloseWindow(request);




        if (type == "switchVirtualDesktop") return SwitchVirtualDesktop(request);




if (type == "launchNaverChatGpt") return LaunchNaverChatGpt(request);




        if (type == "launchGoogleChatGpt") return LaunchGoogleChatGpt(request);




        if (type == "restoreChatGptConversation") return RestoreChatGptConversation(request);




        if (type == "getSharedNote") return GetSharedNote();




        if (type == "setSharedNote") return SetSharedNote(request);




    if (type == "getSharedMonitorNoteView") return GetSharedMonitorNoteView();




    if (type == "setSharedMonitorNoteView") return SetSharedMonitorNoteView(request);




        return Error("癲ル슣????誘⑦←뵳?異?堉온 ????낆툗 ??釉먯뒜?????낇돲??");

    }

    private static bool ProbeHttp(string url, string expectedFragment)
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Timeout = 1500;
            request.ReadWriteTimeout = 1500;
            request.Proxy = null;
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            {
                if ((int)response.StatusCode != 200) return false;
                string body = reader.ReadToEnd();
                return body.IndexOf(expectedFragment, StringComparison.OrdinalIgnoreCase) >= 0;
            }
        }
        catch { return false; }
    }

    private static bool BctCoreReady()
    {
        return ProbeHttp("http://127.0.0.1:18790/health", "\"service\":\"bct-core\"")
            && ProbeHttp("http://127.0.0.1:18790/health", "\"ready\":true");
    }

    private static string TunnelHealthBaseUrl()
    {
        try
        {
            string path = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                @".local\state\tunnel-client\health\act-control.url");
            if (!File.Exists(path)) return "";
            string raw = File.ReadAllText(path, Encoding.UTF8).Trim();
            Uri uri;
            if (!Uri.TryCreate(raw, UriKind.Absolute, out uri) || uri.Scheme != "http" ||
                uri.Host != "127.0.0.1" || !string.IsNullOrEmpty(uri.UserInfo) || uri.Port <= 0)
                return "";
            return uri.GetLeftPart(UriPartial.Authority);
        }
        catch { return ""; }
    }

    private static bool McpTunnelReady()
    {
        string baseUrl = TunnelHealthBaseUrl();
        return !string.IsNullOrEmpty(baseUrl)
            && ProbeHttp(baseUrl + "/healthz", "live")
            && ProbeHttp(baseUrl + "/readyz", "ready");
    }

    private static Dictionary<string, object> RunScheduledTask(string taskName)
    {
        string executable = Path.Combine(Environment.SystemDirectory, "schtasks.exe");
        if (!File.Exists(executable)) throw new FileNotFoundException("BCT_RECOVERY_SCHTASKS_MISSING");
        var start = new ProcessStartInfo {
            FileName = executable,
            Arguments = "/Run /TN \"" + taskName + "\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        using (var process = Process.Start(start))
        {
            if (process == null) throw new InvalidOperationException("BCT_RECOVERY_TASK_START_FAILED");
            string stdout = process.StandardOutput.ReadToEnd();
            string stderr = process.StandardError.ReadToEnd();
            if (!process.WaitForExit(10000)) {
                try { process.Kill(); } catch { }
                throw new TimeoutException("BCT_RECOVERY_TASK_REQUEST_TIMEOUT");
            }
            if (process.ExitCode != 0) {
                throw new InvalidOperationException(
                    "BCT_RECOVERY_TASK_REJECTED:" + process.ExitCode + ":" + (stderr + stdout).Trim());
            }
            return new Dictionary<string, object> {
                { "task", taskName }, { "accepted", true }, { "exitCode", process.ExitCode }
            };
        }
    }

    private static object RecoverBoundedService(string taskName, bool core)
    {
        try
        {
            Func<bool> ready = core ? (Func<bool>)BctCoreReady : McpTunnelReady;
            if (ready()) return new Dictionary<string, object> {
                { "ok", true }, { "task", taskName }, { "alreadyReady", true }, { "verified", true }
            };
            Dictionary<string, object> receipt = RunScheduledTask(taskName);
            DateTime deadline = DateTime.UtcNow.AddSeconds(18);
            while (DateTime.UtcNow < deadline)
            {
                if (ready()) {
                    receipt["ok"] = true;
                    receipt["alreadyReady"] = false;
                    receipt["verified"] = true;
                    return receipt;
                }
                Thread.Sleep(300);
            }
            receipt["ok"] = false;
            receipt["verified"] = false;
            receipt["error"] = core ? "BCT_CORE_RECOVERY_NOT_READY" : "BCT_TUNNEL_RECOVERY_NOT_READY";
            return receipt;
        }
        catch (Exception ex) { return Error(ex.Message); }
    }




    private static bool IsRdcRemoteRunning()
    {
        bool createdNew = false;
        Mutex mutex = null;
        try
        {
            mutex = new Mutex(true, RdcMutexName, out createdNew);
            if (createdNew)
            {
                try { mutex.ReleaseMutex(); } catch { }
                return false;
            }
            return true;
        }
        finally { if (mutex != null) mutex.Dispose(); }
    }

    private static object GetRdcRemoteStatus()
    {
        try
        {
            bool running = IsRdcRemoteRunning();
            bool authRequired = false;
            if (running)
            {
                string err = Path.Combine(RdcRoot, "logs", "remote-agent.err.log");
                string output = Path.Combine(RdcRoot, "logs", "remote-agent.out.log");
                try
                {
                    if (File.Exists(err) && File.ReadAllText(err, Encoding.UTF8).IndexOf("Invalid Refresh Token", StringComparison.OrdinalIgnoreCase) >= 0) authRequired = true;
                    if (File.Exists(output) && File.ReadAllText(output, Encoding.UTF8).IndexOf("Starting device authorization flow", StringComparison.OrdinalIgnoreCase) >= 0) authRequired = true;
                }
                catch { }
            }
            return new Dictionary<string, object> { { "ok", true }, { "running", running }, { "authRequired", authRequired }, { "mode", "manual" } };
        }
        catch (Exception ex) { return Error(ex.Message); }
    }

    private static object StartRdcRemote()
    {
        try
        {
            if (IsRdcRemoteRunning()) return GetRdcRemoteStatus();
            if (!File.Exists(RdcManualStartScript)) return Error("RDC manual start script missing");
            var info = new ProcessStartInfo();
            info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            info.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + RdcManualStartScript + "\"";
            info.WorkingDirectory = RdcRoot;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process.Start(info);
            Thread.Sleep(350);
            return GetRdcRemoteStatus();
        }
        catch (Exception ex) { return Error(ex.Message); }
    }

    private static object StopRdcRemote()
    {
        try
        {
            if (!File.Exists(RdcStopScript)) return Error("RDC stop script missing");
            var info = new ProcessStartInfo();
            info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            info.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + RdcStopScript + "\"";
            info.WorkingDirectory = RdcRoot;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            using (Process process = Process.Start(info))
            {
                if (process != null) process.WaitForExit(8000);
            }
            Thread.Sleep(300);
            return GetRdcRemoteStatus();
        }
        catch (Exception ex) { return Error(ex.Message); }
    }

    private static object GetSharedNote()




    {




        try




        {




            bool exists = File.Exists(SharedNotePath);




            string text = exists ? File.ReadAllText(SharedNotePath, Encoding.UTF8) : "";




            long updated = exists ? File.GetLastWriteTimeUtc(SharedNotePath).Ticks : 0;




            return new Dictionary<string, object> { { "ok", true }, { "exists", exists }, { "text", text }, { "updated", updated } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object SetSharedNote(Dictionary<string, object> request)




    {




        try




        {




            string text = GetString(request, "text") ?? "";




            string dir = Path.GetDirectoryName(SharedNotePath); if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);




            File.WriteAllText(SharedNotePath, text, new UTF8Encoding(false));




            return GetSharedNote();




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static string SharedMonitorNoteViewPath()




    {




        string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DesktopWindowMonitor");




        Directory.CreateDirectory(dir);




        return Path.Combine(dir, "shared-note-view.json");




    }









    private static object GetSharedMonitorNoteView()




    {




        try




        {




            string path = SharedMonitorNoteViewPath();




            if (!File.Exists(path)) return new Dictionary<string, object> { { "ok", true }, { "ratio", 0.0 }, { "revision", "0" } };            var row = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));




            double ratio = 0.0;




            if (row != null && row.ContainsKey("ratio")) double.TryParse(Convert.ToString(row["ratio"]), NumberStyles.Float, CultureInfo.InvariantCulture, out ratio);




            ratio = Math.Max(0.0, Math.Min(1.0, ratio));




            string revision = row != null && row.ContainsKey("revision") ? Convert.ToString(row["revision"]) : "0";




            return new Dictionary<string, object> { { "ok", true }, { "ratio", ratio }, { "revision", revision } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object SetSharedMonitorNoteView(Dictionary<string, object> request)




    {




        try




        {




            double ratio = 0.0;




            double.TryParse(GetString(request, "ratio"), NumberStyles.Float, CultureInfo.InvariantCulture, out ratio);




            ratio = Math.Max(0.0, Math.Min(1.0, ratio));




            string revision = DateTime.UtcNow.Ticks.ToString(CultureInfo.InvariantCulture);




            var row = new Dictionary<string, object> { { "ratio", ratio }, { "revision", revision } };




            File.WriteAllText(SharedMonitorNoteViewPath(), Json.Serialize(row), Encoding.UTF8);




            return new Dictionary<string, object> { { "ok", true }, { "ratio", ratio }, { "revision", revision } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }




    private static object GetState(Dictionary<string, object> request = null)




    {




        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(VdKey))




        {




            if (key == null) return Error("??좊읈??????Β?レ릇???????????덉쉐?域? 癲ル슓??젆???????⑤８?????덊렡.");




            byte[] ids = key.GetValue("VirtualDesktopIDs") as byte[];




            byte[] current = key.GetValue("CurrentVirtualDesktop") as byte[];




            if (ids == null || ids.Length < 16) return Error("??좊읈??????Β?レ릇????癲ル슢?꾤땟戮⑤뭄??????援??????⑤８?????덊렡.");




            int count = ids.Length / 16;




            int currentIndex = 0;




            var desktopIds = new List<string>();




            for (int i = 0; i < count; i++) { var bytes = new byte[16]; Array.Copy(ids, i * 16, bytes, 0, 16); desktopIds.Add(new Guid(bytes).ToString()); }




            if (current != null && current.Length >= 16)




            {




                for (int i = 0; i < count; i++)




                {




                    bool same = true;




                    for (int j = 0; j < 16; j++) if (ids[i * 16 + j] != current[j]) { same = false; break; }




                    if (same) { currentIndex = i; break; }




                }




            }




            var state = new Dictionary<string, object> { { "ok", true }, { "count", count }, { "currentIndex", currentIndex }, { "desktopIds", desktopIds } };




            AppendMonitorHostState(state, request, desktopIds);




            return state;




        }




    }














    private static void AppendMonitorHostState(Dictionary<string, object> state, Dictionary<string, object> request, List<string> desktopIds)




    {




        int left = 0, top = 0, width = 0, height = 0;




        bool hasBounds = TryGetInt(request, "left", out left) && TryGetInt(request, "top", out top)




            && TryGetInt(request, "width", out width) && TryGetInt(request, "height", out height);




        string requestedHostTitle = GetString(request, "hostTitle");




        var manager = (IVirtualDesktopManager)new VirtualDesktopManagerCom();




        Guid bestDesktopId = Guid.Empty; long bestHwnd = 0; int bestScore = int.MaxValue, bestTies = 0, matchCount = 0; string bestTitle = "";




        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)




        {




            try




            {




                int length = GetWindowTextLength(hWnd); if (length <= 0) return true;




                var titleBuffer = new StringBuilder(length + 1); GetWindowText(hWnd, titleBuffer, titleBuffer.Capacity);




                string candidateTitle = titleBuffer.ToString();




                if (!candidateTitle.StartsWith("DesktopWindow Monitor", StringComparison.OrdinalIgnoreCase) && !candidateTitle.StartsWith("DWM ·", StringComparison.OrdinalIgnoreCase)) return true;




                if (!string.IsNullOrWhiteSpace(requestedHostTitle) && !candidateTitle.StartsWith(requestedHostTitle, StringComparison.OrdinalIgnoreCase)) return true;




                RECT rect; if (!GetWindowRect(hWnd, out rect)) return true;




                int score = hasBounds ? Math.Abs(rect.Left - left) + Math.Abs(rect.Top - top)




                    + Math.Abs((rect.Right - rect.Left) - width) + Math.Abs((rect.Bottom - rect.Top) - height) : 0;




                if (hasBounds && score > 96) return true;




                Guid id = manager.GetWindowDesktopId(hWnd); matchCount++;




                if (score < bestScore) { bestScore = score; bestDesktopId = id; bestHwnd = hWnd.ToInt64(); bestTitle = candidateTitle; bestTies = 1; }




                else if (score == bestScore) { bestTies++; }




            }




            catch { }




            return true;




        }, IntPtr.Zero);




        state["hostWindowMatchCount"] = matchCount;




        state["hostWindowAmbiguous"] = bestTies > 1;




        if (bestDesktopId != Guid.Empty && bestTies == 1)




        {




            string hostId = bestDesktopId.ToString();




            state["hostDesktopId"] = hostId; state["hostIndex"] = desktopIds.IndexOf(hostId);




            state["hostWindowHwnd"] = bestHwnd.ToString(CultureInfo.InvariantCulture); state["hostWindowMatchScore"] = bestScore; state["hostWindowTitle"] = bestTitle;




        }




    }









    private static object GetDesktopWindows(Dictionary<string, object> request)




    {




        Guid target;




        if (!Guid.TryParse(GetString(request, "desktopId"), out target)) return Error("desktopId??좊읈? ????筌?? ?????????덊렡.");




        var manager = (IVirtualDesktopManager)new VirtualDesktopManagerCom();




        long hostWindowHwnd = 0; long.TryParse(GetString(request, "hostWindowHwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out hostWindowHwnd);




        var windows = new List<Dictionary<string, object>>();




        Rectangle virtualScreen = SystemInformation.VirtualScreen;




        Rectangle previewScreen = virtualScreen;




        if (Screen.AllScreens.Length == 1) previewScreen = Screen.PrimaryScreen.WorkingArea;




        int zOrder = 0;




        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)




        {




            try




            {




                Guid desktopId = manager.GetWindowDesktopId(hWnd);




                if (desktopId != target) return true;




                bool visible = IsWindowVisible(hWnd), iconic = IsIconic(hWnd);




                if (!visible) return true;




                RECT rect; if (!GetWindowRect(hWnd, out rect)) return true;




                int width = rect.Right - rect.Left, height = rect.Bottom - rect.Top;




                if (!iconic && (width < 120 || height < 80 || rect.Left < -20000 || rect.Top < -20000)) return true;




                int length = GetWindowTextLength(hWnd);




                var titleBuffer = new StringBuilder(Math.Max(2, length + 1)); GetWindowText(hWnd, titleBuffer, titleBuffer.Capacity);




                string title = titleBuffer.ToString();




                if (string.IsNullOrWhiteSpace(title) || title.StartsWith("DesktopWindow Monitor", StringComparison.OrdinalIgnoreCase) || title.StartsWith("DWM ·", StringComparison.OrdinalIgnoreCase)) return true;




                var classBuffer = new StringBuilder(256); GetClassName(hWnd, classBuffer, classBuffer.Capacity);




                string className = classBuffer.ToString();




                if (className == "Progman" || className == "WorkerW" || className == "Shell_TrayWnd") return true;




                int cloaked = 0; try { DwmGetWindowAttribute(hWnd, 14, out cloaked, 4); } catch { }




                windows.Add(new Dictionary<string, object> { { "hwnd", hWnd.ToInt64().ToString(CultureInfo.InvariantCulture) }, { "title", title }, { "className", className }, { "left", rect.Left }, { "top", rect.Top }, { "width", width }, { "height", height }, { "visible", visible }, { "iconic", iconic }, { "z", zOrder++ }, { "cloaked", cloaked } });




            }




            catch { }




            return true;




        }, IntPtr.Zero);




        return new Dictionary<string, object> { { "ok", true }, { "desktopId", target.ToString() }, { "virtualLeft", virtualScreen.Left }, { "virtualTop", virtualScreen.Top }, { "virtualWidth", virtualScreen.Width }, { "virtualHeight", virtualScreen.Height }, { "previewVirtualLeft", previewScreen.Left }, { "previewVirtualTop", previewScreen.Top }, { "previewVirtualWidth", previewScreen.Width }, { "previewVirtualHeight", previewScreen.Height }, { "windows", windows } };




    }














    private static object GetForegroundWindowInfo()




    {




        IntPtr hWnd = GetForegroundWindow();




        long raw = hWnd.ToInt64();




        string desktopId = "";




        try { if (hWnd != IntPtr.Zero) desktopId = ((IVirtualDesktopManager)new VirtualDesktopManagerCom()).GetWindowDesktopId(hWnd).ToString(); } catch { }




        var input = new LASTINPUTINFO { cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO)) };




        uint lastInputTick = GetLastInputInfo(ref input) ? input.dwTime : 0;




        var classBuffer = new StringBuilder(256); if (hWnd != IntPtr.Zero) GetClassName(hWnd, classBuffer, classBuffer.Capacity);




        RECT rect = new RECT(); bool hasRect = hWnd != IntPtr.Zero && GetWindowRect(hWnd, out rect);




        POINT cursor = new POINT(); bool hasCursor = GetCursorPos(out cursor);




        short leftState = GetAsyncKeyState(0x01);




        bool leftDown = (leftState & 0x8000) != 0;




        bool leftPressed = (leftState & 0x0001) != 0;




        var response = new Dictionary<string, object> {




            { "ok", true }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) }, { "desktopId", desktopId },




            { "lastInputTick", lastInputTick.ToString(CultureInfo.InvariantCulture) }, { "className", classBuffer.ToString() },




            { "leftDown", leftDown }, { "leftPressed", leftPressed }, { "shiftDown", (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0 }




        };




        if (hasCursor) { response["cursorX"] = cursor.X; response["cursorY"] = cursor.Y; }




        if (hasRect) { response["left"] = rect.Left; response["top"] = rect.Top; response["width"] = rect.Right - rect.Left; response["height"] = rect.Bottom - rect.Top; }




        return response;




    }









    private static object SetWindowBorderHighlight(Dictionary<string, object> request)




    {




        long raw;




        if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0) return Error("hwnd揶쎛 ??而?몴?? ??녿뮸??덈뼄.");




        IntPtr hWnd = new IntPtr(raw);




        if (!IsWindow(hWnd)) return Error("筌≪럩??筌≪뼚??????곷뮸??덈뼄.");




        string mode = GetString(request, "mode").ToLowerInvariant();




        // COLORREF is 0x00BBGGRR. Use a saturated electric blue while targeting so the




        // disappearing Chrome window, not the Monitor surface, carries the strongest cue.




        uint color = mode == "clear" ? 0xFFFFFFFFu : (mode == "success" ? 0x00FFF6D8u : 0x00FF8F18u);




        int hr = DwmSetWindowAttribute(hWnd, 34, ref color, 4);




        return new Dictionary<string, object> { { "ok", hr == 0 }, { "hresult", hr }, { "mode", mode } };




    }









    private static object GetAllChromeWindowHandles()




    {




        var handles = new List<string>();




        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {




            var classBuffer = new StringBuilder(128); GetClassName(hWnd, classBuffer, classBuffer.Capacity);




            if (classBuffer.ToString() == "Chrome_WidgetWin_1") handles.Add(hWnd.ToInt64().ToString(CultureInfo.InvariantCulture));




            return true;




        }, IntPtr.Zero);




        return new Dictionary<string, object> { { "ok", true }, { "hwnds", handles } };




    }









    private static object GetDesktopWindowHandles(Dictionary<string, object> request)




    {




        Guid target; if (!Guid.TryParse(GetString(request, "desktopId"), out target)) return Error("desktopId??좊읈? ????筌?? ?????????덊렡.");




        var manager = (IVirtualDesktopManager)new VirtualDesktopManagerCom();




        long hostWindowHwnd = 0; long.TryParse(GetString(request, "hostWindowHwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out hostWindowHwnd);




        bool includeMonitorWindows = string.Equals(GetString(request, "includeMonitorWindows"), "true", StringComparison.OrdinalIgnoreCase);




        var handles = new List<string>();




        var windows = new List<Dictionary<string, object>>();




        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)




        {




            try




            {




                if (manager.GetWindowDesktopId(hWnd) != target) return true;




                var classBuffer = new StringBuilder(256); GetClassName(hWnd, classBuffer, classBuffer.Capacity);




                string className = classBuffer.ToString();




                if (className == "Progman" || className == "WorkerW" || className == "Shell_TrayWnd") return true;




                int length = GetWindowTextLength(hWnd); var titleBuffer = new StringBuilder(Math.Max(2, length + 1)); GetWindowText(hWnd, titleBuffer, titleBuffer.Capacity);




                string title = titleBuffer.ToString();




                if (!includeMonitorWindows && (title.StartsWith("DesktopWindow Monitor", StringComparison.OrdinalIgnoreCase) || title.StartsWith("DWM ·", StringComparison.OrdinalIgnoreCase))) return true;




                if (!string.IsNullOrWhiteSpace(title) || IsWindowVisible(hWnd) || IsIconic(hWnd))




                {




                    string hwnd = hWnd.ToInt64().ToString(CultureInfo.InvariantCulture);




                    handles.Add(hwnd);




                    windows.Add(new Dictionary<string, object> { { "hwnd", hwnd }, { "title", title }, { "className", className }, { "visible", IsWindowVisible(hWnd) }, { "iconic", IsIconic(hWnd) } });




                }




            }




            catch { }




            return true;




        }, IntPtr.Zero);




        return new Dictionary<string, object> { { "ok", true }, { "desktopId", target.ToString() }, { "hwnds", handles }, { "windows", windows } };




    }









    private static object GetChromeConversationIdentity(Dictionary<string, object> request)




    {




        long raw; if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0) return Error("hwnd??좊읈? ????筌?? ?????????덊렡.");




        IntPtr hWnd = new IntPtr(raw);




        var classBuffer = new StringBuilder(256); GetClassName(hWnd, classBuffer, classBuffer.Capacity);




        if (classBuffer.ToString() != "Chrome_WidgetWin_1") return Error("Chrome 癲ル슓??????ш끽維筌????덊렡.");




        try




        {




            AutomationElement root = AutomationElement.FromHandle(hWnd);




            if (root == null) return Error("Chrome UI??????援??????⑤８?????덊렡.");




            var condition = new PropertyCondition(AutomationElement.AutomationIdProperty, "view_1012");




            AutomationElement address = root.FindFirst(TreeScope.Descendants, condition);




            object pattern; string value = "";




            if (address != null && address.TryGetCurrentPattern(ValuePattern.Pattern, out pattern)) value = ((ValuePattern)pattern).Current.Value ?? "";




            string normalized = value.Trim(); if (!normalized.Contains("://")) normalized = "https://" + normalized;




            Uri uri; string key = "";




            if (Uri.TryCreate(normalized, UriKind.Absolute, out uri) && (uri.Host.Equals("chatgpt.com", StringComparison.OrdinalIgnoreCase) || uri.Host.Equals("chat.openai.com", StringComparison.OrdinalIgnoreCase)))




            { var parts = uri.AbsolutePath.Split(new[]{'/'}, StringSplitOptions.RemoveEmptyEntries); if (parts.Length >= 2 && parts[0].Equals("c", StringComparison.OrdinalIgnoreCase)) key = parts[1]; }




            return new Dictionary<string, object> { { "ok", true }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) }, { "conversationKey", key }, { "url", value } };




        }




        catch (Exception ex) { return Error("Chrome identity lookup failed: " + ex.Message); }




    }









    private static string GetDesktopWallpaperPath(Guid desktopId)




    {




        string keyPath = VdKey + @"\Desktops\{" + desktopId.ToString("D").ToUpperInvariant() + "}";




        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(keyPath))




        {




            string raw = key == null ? null : Convert.ToString(key.GetValue("Wallpaper"));




            return string.IsNullOrWhiteSpace(raw) ? "" : Environment.ExpandEnvironmentVariables(raw);




        }




    }









    private static void SetDesktopWallpaperPath(Guid desktopId, string wallpaperPath)




    {




        if (string.IsNullOrWhiteSpace(wallpaperPath)) return;




        string keyPath = VdKey + @"\Desktops\{" + desktopId.ToString("D").ToUpperInvariant() + "}";




        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(keyPath))




        {




            if (key != null) key.SetValue("Wallpaper", wallpaperPath, RegistryValueKind.String);




        }




    }









    private static object GetDesktopWallpaperInfo(Dictionary<string, object> request)




    {




        Guid desktopId; if (!Guid.TryParse(GetString(request, "desktopId"), out desktopId)) return Error("desktopId??좊읈? ????筌?? ?????????덊렡.");




        string keyPath = VdKey + @"\Desktops\{" + desktopId.ToString("D").ToUpperInvariant() + "}";




        try




        {




            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(keyPath))




            {




                string raw = key == null ? null : Convert.ToString(key.GetValue("Wallpaper"));




                string path = string.IsNullOrWhiteSpace(raw) ? "" : Environment.ExpandEnvironmentVariables(raw);




                bool ready = !string.IsNullOrWhiteSpace(path) && File.Exists(path);




                return new Dictionary<string, object> { { "ok", true }, { "desktopId", desktopId.ToString() }, { "ready", ready }, { "path", path } };




            }




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object CaptureWindow(Dictionary<string, object> request)
    {
        long raw;
        if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw))
            return Error("Invalid hwnd.");

        IntPtr hWnd = new IntPtr(raw);
        RECT rect;
        if (!GetWindowRect(hWnd, out rect))
            return Error("Window rect unavailable.");

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 2 || height < 2 || width > 10000 || height > 10000)
            return Error("Invalid window bounds.");

        int maxWidth = GetInt(request, "maxWidth", 700, 160, 2200);
        int maxHeight = GetInt(request, "maxHeight", 480, 120, 1600);
        int quality = GetInt(request, "quality", 58, 35, 90);

        string helperPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, WgcCaptureHelperName);
        if (!File.Exists(helperPath))
            return Error("WGC capture helper missing.");

        bool slotHeld = false;
        string tempPath = null;
        try
        {
            slotHeld = WindowCaptureSlots.WaitOne(WgcCaptureQueueWaitMs);
            if (!slotHeld)
                return Error("WGC capture queue busy.");

            tempPath = Path.Combine(Path.GetTempPath(), "dwm-wgc-" + Guid.NewGuid().ToString("N") + ".jpg");
            string quality01 = ((double)quality / 100.0).ToString("0.00", CultureInfo.InvariantCulture);

            var info = new ProcessStartInfo();
            info.FileName = helperPath;
            info.Arguments =
                "--hwnd " + raw.ToString(CultureInfo.InvariantCulture) +
                " --repeat 1" +
                " --max-width " + maxWidth.ToString(CultureInfo.InvariantCulture) +
                " --max-height " + maxHeight.ToString(CultureInfo.InvariantCulture) +
                " --timeout-ms 3000" +
                " --quality " + quality01 +
                " --save-first \"" + tempPath + "\"";
            info.WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;

            using (Process process = Process.Start(info))
            {
                if (process == null)
                    return Error("WGC helper start failed.");

                if (!process.WaitForExit(WgcCaptureProcessWaitMs))
                {
                    try { process.Kill(); } catch { }
                    return Error("WGC helper timed out.");
                }

                string helperStdout;
                string helperStderr;
                using (StreamReader helperOutput = process.StandardOutput)
                using (StreamReader helperError = process.StandardError)
                {
                    helperStdout = helperOutput.ReadToEnd();
                    helperStderr = helperError.ReadToEnd();
                }

                if (process.ExitCode != 0)
                {
                    string detail = string.IsNullOrWhiteSpace(helperStderr) ? helperStdout : helperStderr;
                    if (detail == null) detail = "";
                    detail = detail.Trim();
                    if (detail.Length > 240) detail = detail.Substring(0, 240);
                    return Error("WGC helper failed (" + process.ExitCode.ToString(CultureInfo.InvariantCulture) + "): " + detail);
                }
            }

            if (!File.Exists(tempPath))
                return Error("WGC helper produced no image.");

            byte[] jpeg = File.ReadAllBytes(tempPath);
            if (jpeg.Length < 256)
                return Error("WGC helper produced an empty image.");

            return new Dictionary<string, object>
            {
                { "ok", true },
                { "dataUri", "data:image/jpeg;base64," + Convert.ToBase64String(jpeg) },
                { "width", width },
                { "height", height },
                { "captureEngine", "wgc-oneshot" }
            };
        }
        catch (Exception ex)
        {
            return Error("WGC capture failed: " + ex.Message);
        }
        finally
        {
            if (!string.IsNullOrEmpty(tempPath))
            {
                try { if (File.Exists(tempPath)) File.Delete(tempPath); } catch { }
            }
            if (slotHeld) WindowCaptureSlots.Release();
        }
    }

    private static object CaptureCurrentDesktopWallpaper(Dictionary<string, object> request)
    {
        var state = GetState() as Dictionary<string, object>;
        if (state == null || !Convert.ToBoolean(state["ok"])) return state ?? Error("Virtual desktop state unavailable.");

        var desktopIds = state["desktopIds"] as List<string>;
        int currentIndex = Convert.ToInt32(state["currentIndex"], CultureInfo.InvariantCulture);
        if (desktopIds == null || currentIndex < 0 || currentIndex >= desktopIds.Count)
            return Error("Current virtual desktop unavailable.");

        IntPtr progman = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hWnd)) return true;
            var className = new StringBuilder(128);
            GetClassName(hWnd, className, className.Capacity);
            if (!String.Equals(className.ToString(), "Progman", StringComparison.Ordinal)) return true;
            progman = hWnd;
            return false;
        }, IntPtr.Zero);

        if (progman == IntPtr.Zero) return Error("Progman wallpaper window unavailable.");

        var captureRequest = request == null
            ? new Dictionary<string, object>()
            : new Dictionary<string, object>(request);
        captureRequest["hwnd"] = progman.ToInt64().ToString(CultureInfo.InvariantCulture);

        var captured = CaptureWindow(captureRequest) as Dictionary<string, object>;
        if (captured == null) return Error("Wallpaper capture failed.");
        object rawOk;
        if (!captured.TryGetValue("ok", out rawOk) || !Convert.ToBoolean(rawOk)) return captured;

        captured["desktopId"] = desktopIds[currentIndex];
        captured["hwnd"] = progman.ToInt64().ToString(CultureInfo.InvariantCulture);
        captured["visualSource"] = "progman-wgc-oneshot";
        return captured;
    }

    private static void OnWindowForegroundChange(IntPtr hook, uint eventType, IntPtr hWnd, int idObject, int idChild, uint eventThread, uint eventTime)
    {
        try {
            if (!IsObservedTopLevelWindow(hWnd)) return;
            Guid desktopId = ((IVirtualDesktopManager)new VirtualDesktopManagerCom()).GetWindowDesktopId(hWnd);
            var message = new Dictionary<string, object> {
                { "type", "windowForegroundChanged" }, { "event", true },
                { "hwnd", hWnd.ToInt64().ToString(CultureInfo.InvariantCulture) },
                { "desktopId", desktopId.ToString() },
                { "at", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() }
            };
            Stream output = NativeOutput; if (output != null) Write(output, message);
        } catch { }
    }

    private static object CreateVirtualDesktop()




    {




        try




        {




            var beforeState = GetState() as Dictionary<string, object>;




            if (beforeState == null || !Convert.ToBoolean(beforeState["ok"])) return beforeState;




            var beforeIds = beforeState["desktopIds"] as List<string>;




            int currentIndex = Convert.ToInt32(beforeState["currentIndex"]);




            Guid currentId; string currentWallpaper = "";




            if (beforeIds != null && currentIndex >= 0 && currentIndex < beforeIds.Count && Guid.TryParse(beforeIds[currentIndex], out currentId)) currentWallpaper = GetDesktopWallpaperPath(currentId);




            int before = VdaGetDesktopCount(); int rawIndex = VdaCreateDesktop();




            if (rawIndex < 0) return Error("????좊읈??????Β?レ릇??????獄쏅똻???????됰꽡???怨?????덊렡.");




            Thread.Sleep(180); int after = VdaGetDesktopCount();




            if (after <= before) return Error("????좊읈??????Β?レ릇???????獄쏅똻???? ????⒱봼??????");




            var state = GetState() as Dictionary<string, object>;




            if (state == null || !Convert.ToBoolean(state["ok"])) return state;




            var afterIds = state["desktopIds"] as List<string>; string createdId = null;




            if (afterIds != null) foreach (string id in afterIds) if (beforeIds == null || !beforeIds.Contains(id)) { createdId = id; break; }




            Guid createdGuid; if (!string.IsNullOrEmpty(createdId) && Guid.TryParse(createdId, out createdGuid)) SetDesktopWallpaperPath(createdGuid, currentWallpaper);




            state["created"] = true; state["createdDesktopId"] = createdId; state["index"] = afterIds != null && createdId != null ? afterIds.IndexOf(createdId) : rawIndex; state["count"] = after; state["wallpaperPath"] = currentWallpaper;




            return state;




        }




        catch (DllNotFoundException) { return Error("VirtualDesktopAccessor.dll??癲ル슓??젆???????⑤８?????덊렡."); }




        catch (EntryPointNotFoundException) { return Error("VirtualDesktopAccessor CreateDesktop ??縕???癲ル슓??젆???????⑤８?????덊렡."); }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object RemoveVirtualDesktop(Dictionary<string, object> request)




    {




        try




        {




            int before = VdaGetDesktopCount();




            if (before <= 1) return Error("癲ル슢???癲???좊읈??????Β?レ릇????? ??????????⑤８?????덊렡.");




            int removeIndex = GetInt(request, "index", -1, -1, before - 1);




            int fallbackIndex = GetInt(request, "fallbackIndex", -1, -1, before - 1);




            if (removeIndex < 0 || fallbackIndex < 0 || removeIndex == fallbackIndex) return Error("??????癲????Β?レ릇?????類????癒?씀? ????筌?? ?????????덊렡.");




            int result = VdaRemoveDesktop(removeIndex, fallbackIndex);




            if (result < 0) return Error("??좊읈??????Β?レ릇?????????????됰꽡???怨?????덊렡.");




            Thread.Sleep(180);




            int after = VdaGetDesktopCount();




            if (after != before - 1) return Error("??좊읈??????Β?レ릇?????????濡ろ뜏???醫듽걫??嶺뚮Ĳ?됮??? 癲ル슢履뉑쾮?彛??????");




            var state = GetState() as Dictionary<string, object>;




            if (state == null || !Convert.ToBoolean(state["ok"])) return state;




            state["removed"] = true; state["removedIndex"] = removeIndex; state["fallbackIndex"] = fallbackIndex;




            return state;




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object RestoreVirtualDesktop(Dictionary<string, object> request)




    {




        try




        {




            var beforeState = GetState() as Dictionary<string, object>;




            if (beforeState == null || !Convert.ToBoolean(beforeState["ok"])) return beforeState;




            var beforeIds = beforeState["desktopIds"] as List<string>;




            string wallpaperPath = GetString(request, "wallpaperPath");




            int before = VdaGetDesktopCount(); int rawIndex = VdaCreateDesktop();




            if (rawIndex < 0) return Error("?怨뚮옖甕걔?????좊읈??????Β?レ릇??????獄쏅똻???????됰꽡???怨?????덊렡.");




            Thread.Sleep(180); int after = VdaGetDesktopCount();




            if (after <= before) return Error("?怨뚮옖甕걔?????좊읈??????Β?レ릇???????獄쏅똻???? ????⒱봼??????");




            var state = GetState() as Dictionary<string, object>;




            if (state == null || !Convert.ToBoolean(state["ok"])) return state;




            var afterIds = state["desktopIds"] as List<string>; string restoredId = null;




            if (afterIds != null) foreach (string id in afterIds) if (beforeIds == null || !beforeIds.Contains(id)) { restoredId = id; break; }




            int index = afterIds != null && restoredId != null ? afterIds.IndexOf(restoredId) : rawIndex;




            Guid restoredGuid; if (!string.IsNullOrEmpty(restoredId) && Guid.TryParse(restoredId, out restoredGuid)) SetDesktopWallpaperPath(restoredGuid, wallpaperPath);




            int restored = 0; object raw;




            if (request != null && request.TryGetValue("hwnds", out raw) && raw is System.Collections.IEnumerable)




            {




                foreach (object item in (System.Collections.IEnumerable)raw)




                {




                    long hwndValue; if (!long.TryParse(Convert.ToString(item), NumberStyles.Integer, CultureInfo.InvariantCulture, out hwndValue)) continue;




                    if (VdaMoveWindowToDesktopNumber(new IntPtr(hwndValue), index) >= 0) restored++;




                }




            }




            state["restored"] = true; state["restoredDesktopId"] = restoredId; state["index"] = index; state["restoredWindows"] = restored; state["wallpaperPath"] = wallpaperPath;




            return state;




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object SwitchVirtualDesktop(Dictionary<string, object> request)




    {




        try




        {




            int count = VdaGetDesktopCount();




            int index = GetInt(request, "index", -1, -1, Math.Max(0, count - 1));




            if (index < 0 || index >= count) return Error("Invalid desktop index.");




            int result = VdaGoToDesktopNumber(index);




            if (result < 0) return Error("VirtualDesktopAccessor switch failed.");




            Thread.Sleep(140);




            var state = GetState() as Dictionary<string, object>;




            if (state == null || !Convert.ToBoolean(state["ok"])) return state;




            int actual = Convert.ToInt32(state["currentIndex"], CultureInfo.InvariantCulture);




            if (actual != index) return Error("Virtual desktop switch verification failed.");




            state["switched"] = true; state["index"] = index;




            return state;




        }




        catch (DllNotFoundException) { return Error("VirtualDesktopAccessor.dll missing."); }




        catch (EntryPointNotFoundException) { return Error("VirtualDesktopAccessor GoToDesktopNumber missing."); }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object MoveWindowToDesktop(Dictionary<string, object> request)




    {




        try




        {




            long raw;




            if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0)




                return Error("Invalid hwnd.");




            Guid target;




            if (!Guid.TryParse(GetString(request, "desktopId"), out target))




                return Error("Invalid desktopId.");




            IntPtr hWnd = new IntPtr(raw);




            var manager = (IVirtualDesktopManager)new VirtualDesktopManagerCom();




            Guid source = manager.GetWindowDesktopId(hWnd);




            if (source == target)




                return new Dictionary<string, object> { { "ok", true }, { "moved", false }, { "alreadyThere", true }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) }, { "sourceDesktopId", source.ToString() }, { "desktopId", target.ToString() } };




            var state = GetState() as Dictionary<string, object>;




            var desktopIds = state == null ? null : state["desktopIds"] as List<string>;




            int targetIndex = desktopIds == null ? -1 : desktopIds.FindIndex(id => String.Equals(id, target.ToString(), StringComparison.OrdinalIgnoreCase));




            if (targetIndex < 0) return Error("Target desktop not found.");




            int moveResult = VdaMoveWindowToDesktopNumber(hWnd, targetIndex);




            if (moveResult < 0) return Error("VirtualDesktopAccessor move failed.");




            Thread.Sleep(120);




            Guid actual = manager.GetWindowDesktopId(hWnd);




            if (actual != target) return Error("Window move verification failed.");




            return new Dictionary<string, object> { { "ok", true }, { "moved", true }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) }, { "sourceDesktopId", source.ToString() }, { "desktopId", target.ToString() }, { "targetIndex", targetIndex } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static string ChromeAddressValue(IntPtr hWnd)




    {




        try {




            AutomationElement root = AutomationElement.FromHandle(hWnd); if (root == null) return "";




            AutomationElement address = root.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.AutomationIdProperty, "view_1012"));




            object pattern; if (address != null && address.TryGetCurrentPattern(ValuePattern.Pattern, out pattern)) return ((ValuePattern)pattern).Current.Value ?? "";




        } catch { }




        return "";




    }




    private static object LaunchChatGptWindowCopy(Dictionary<string, object> request)




    {




        try {




            long raw; if (!long.TryParse(GetString(request, "sourceHwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0) return Error("Invalid sourceHwnd.");




            string profileId = GetString(request, "profileId").Trim().ToUpperInvariant();




            if (profileId != "GOOGLE" && profileId != "NAVER") return Error("Unsupported ChatGPT profile.");




            IntPtr source = new IntPtr(raw); RECT rect; if (!GetWindowRect(source, out rect)) return Error("Source window geometry unavailable.");




            string chrome = FindChromeExecutable(); if (string.IsNullOrEmpty(chrome)) return Error("Chrome executable not found.");




            string url = "https://chatgpt.com/";




            string args = profileId == "NAVER" ? "--user-data-dir=\"" + NaverProfileDirectory + "\" --new-window \"" + url + "\"" : "--new-window \"" + url + "\"";




            Process.Start(new ProcessStartInfo(chrome, args) { UseShellExecute = false });




            return new Dictionary<string, object> { { "ok", true }, { "launched", true }, { "profileId", profileId }, { "left", rect.Left }, { "top", rect.Top }, { "width", rect.Right-rect.Left }, { "height", rect.Bottom-rect.Top } };




        } catch (Exception ex) { return Error(ex.Message); }




    }









    private static object SetWindowBoundsNoActivate(Dictionary<string, object> request)




    {




        long raw; if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0) return Error("Invalid hwnd.");




        int left, top, width, height;




        if (!TryGetInt(request, "left", out left) || !TryGetInt(request, "top", out top) || !TryGetInt(request, "width", out width) || !TryGetInt(request, "height", out height)) return Error("Invalid bounds.");




        bool ok = SetWindowPos(new IntPtr(raw), IntPtr.Zero, left, top, Math.Max(120,width), Math.Max(80,height), SWP_NOZORDER | SWP_NOACTIVATE);




        return new Dictionary<string, object> { { "ok", ok }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) } };




    }









    private static object RestoreForegroundWindow(Dictionary<string, object> request)




    {




        long raw; if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0) return Error("Invalid hwnd.");




        return new Dictionary<string, object> { { "ok", SetForegroundWindow(new IntPtr(raw)) }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) } };




    }

    private static object GetCodexRuntimeStatus(Dictionary<string, object> request)
    {
        string profileId = GetString(request, "profileId").Trim().ToUpperInvariant();
        if (profileId != "GOOGLE") return Error("Unsupported Codex profile.");

        IntPtr window = FindGCodexAppWindow();
        uint processId = 0;
        if (window != IntPtr.Zero) GetWindowThreadProcessId(window, out processId);
        return new Dictionary<string, object> {
            { "ok", true },
            { "profileId", profileId },
            { "connected", window != IntPtr.Zero },
            { "detail", window != IntPtr.Zero ? "Codex 사용 준비됨" : "Codex 미실행" },
            { "hwnd", window.ToInt64().ToString(CultureInfo.InvariantCulture) },
            { "pid", (int)processId }
        };
    }

    private static IntPtr FindGCodexAppWindow()
    {
        try
        {
            foreach (Process process in Process.GetProcesses()
                .Where(item => string.Equals(item.ProcessName, "ChatGPT", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(item.ProcessName, "Codex", StringComparison.OrdinalIgnoreCase)))
            {
                try
                {
                    IntPtr window = process.MainWindowHandle;
                    if (window == IntPtr.Zero) continue;

                    string executable = "";
                    try
                    {
                        executable = process.MainModule == null ? "" : process.MainModule.FileName;
                    }
                    catch { }

                    if (executable.IndexOf(@"\WindowsApps\OpenAI.Codex_", StringComparison.OrdinalIgnoreCase) >= 0
                        || executable.IndexOf(@"\WindowsApps\OpenAI.ChatGPT_", StringComparison.OrdinalIgnoreCase) >= 0)
                        return window;
                }
                finally
                {
                    process.Dispose();
                }
            }
        }
        catch { }
        return IntPtr.Zero;
    }

    private static object CloseWindow(Dictionary<string, object> request)




    {




        long raw; if (!long.TryParse(GetString(request, "hwnd"), NumberStyles.Integer, CultureInfo.InvariantCulture, out raw) || raw == 0) return Error("Invalid hwnd.");




        IntPtr hWnd = new IntPtr(raw); var className = new StringBuilder(128); GetClassName(hWnd, className, className.Capacity);




        if (className.ToString() != "Chrome_WidgetWin_1") return Error("Only Chrome windows may be closed by window-copy undo.");




        return new Dictionary<string, object> { { "ok", PostMessage(hWnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero) }, { "hwnd", raw.ToString(CultureInfo.InvariantCulture) } };




    }









    private static string FindChromeExecutable()




    {




        string[] candidates = new[] {




            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Google\Chrome\Application\chrome.exe"),




            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), @"Google\Chrome\Application\chrome.exe"),




            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Google\Chrome\Application\chrome.exe")




        };




        foreach (string candidate in candidates) if (File.Exists(candidate)) return candidate;




        return "";




    }









    private static object RestoreChatGptConversation(Dictionary<string, object> request)




    {




        try




        {




            string profileId = GetString(request, "profileId").Trim().ToUpperInvariant();




            string conversationKey = GetString(request, "conversationKey").Trim();




            Guid parsed;




            if (profileId != "GOOGLE" && profileId != "NAVER") return Error("Unsupported ChatGPT profile.");




            if (!Guid.TryParse(conversationKey, out parsed)) return Error("Invalid conversation key.");




            string chrome = FindChromeExecutable(); if (string.IsNullOrEmpty(chrome)) return Error("Chrome executable not found.");




            string url = "https://chatgpt.com/c/" + Uri.EscapeDataString(conversationKey);




            string args;




            if (profileId == "NAVER")




            {




                Directory.CreateDirectory(NaverProfileDirectory);




                args = "--user-data-dir=\"" + NaverProfileDirectory + "\" --new-window \"" + url + "\"";




            }




            else args = "--new-window \"" + url + "\"";




            Process.Start(new ProcessStartInfo(chrome, args) { UseShellExecute = false });




            return new Dictionary<string, object> { { "ok", true }, { "launched", true }, { "profileId", profileId }, { "conversationKey", conversationKey }, { "url", url } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }









    private static object LaunchGoogleChatGpt(Dictionary<string, object> request)
    {
        try
        {
            string chrome = FindChromeExecutable();
            if (string.IsNullOrEmpty(chrome)) return Error("Chrome executable not found.");

            string launchUrl = ChatGptUrl;
            Process process = Process.Start(new ProcessStartInfo(chrome, "--new-window \"" + launchUrl + "\"") { UseShellExecute = false });
            return new Dictionary<string, object>
            {
                { "ok", true },
                { "launched", true },
                { "profileId", "GOOGLE" },
                { "url", launchUrl },
                { "pid", process == null ? 0 : process.Id }
            };
        }
        catch (Exception ex)
        {
            return Error(ex.Message);
        }
    }

    private static object LaunchNaverChatGpt(Dictionary<string, object> request)
    {
        try
        {
            string chrome = FindChromeExecutable();
            if (string.IsNullOrEmpty(chrome)) return Error("Chrome executable not found.");

            Directory.CreateDirectory(NaverProfileDirectory);
            string launchUrl = ChatGptUrl;
            string args = "--user-data-dir=\"" + NaverProfileDirectory + "\" --new-window \"" + launchUrl + "\"";
            Process process = Process.Start(new ProcessStartInfo(chrome, args) { UseShellExecute = false });
            return new Dictionary<string, object>
            {
                { "ok", true },
                { "launched", true },
                { "profileId", "NAVER" },
                { "profilePath", NaverProfileDirectory },
                { "url", launchUrl },
                { "pid", process == null ? 0 : process.Id }
            };
        }
        catch (Exception ex)
        {
            return Error(ex.Message);
        }
    }

    private static object GetDeploymentInfo()




    {




        try




        {




            DirectoryInfo cursor = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);




            string manifestPath = null;




            for (int depth = 0; depth < 5 && cursor != null; depth++, cursor = cursor.Parent)




            {




                string candidate = Path.Combine(cursor.FullName, "extension", "manifest.json");




                if (File.Exists(candidate)) { manifestPath = candidate; break; }




            }




            if (string.IsNullOrEmpty(manifestPath)) return Error("Monitor ?袁⑸즲????manifest??癲ル슓??젆???????⑤８?????덊렡.");




            var manifest = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(manifestPath, Encoding.UTF8));




            object version;




            if (manifest == null || !manifest.TryGetValue("version", out version)) return Error("Monitor ?類?????????援??????⑤８?????덊렡.");




            string reloadTokenPath = Path.Combine(Path.GetDirectoryName(manifestPath), ".reload-token");




            string reloadToken = File.Exists(reloadTokenPath) ? File.ReadAllText(reloadTokenPath, Encoding.UTF8).Trim() : "";




            return new Dictionary<string, object> { { "ok", true }, { "version", Convert.ToString(version) }, { "manifestPath", manifestPath }, { "reloadToken", reloadToken } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }














    private static string SharedMonitorSelectionPath()




    {




        string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DesktopWindowMonitor");




        Directory.CreateDirectory(dir);




        return Path.Combine(dir, "shared-selection.json");




    }









    private static object WithSharedMonitorSelectionLock(Func<object> action)




    {




        using (var mutex = new Mutex(false, @"Local\DesktopWindowMonitor.SharedSelection"))




        {




            bool held = false;




            try




            {




                try { held = mutex.WaitOne(1500); }




                catch (AbandonedMutexException) { held = true; }




                if (!held) return Error("shared selection lock timeout");




                return action();




            }




            finally { if (held) mutex.ReleaseMutex(); }




        }




    }









    private static string NormalizeSelectionCsv(string csv)




    {




        var kept = new List<string>();




        foreach (string raw in (csv ?? "").Split(','))




        {




            string value = (raw ?? "").Trim();




            long hwndValue;




            if (!long.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out hwndValue) || hwndValue <= 0) continue;




            if (!IsWindow(new IntPtr(hwndValue))) continue;




            if (!kept.Contains(value)) kept.Add(value);




        }




        return string.Join(",", kept.ToArray());




    }









    private static object GetSharedMonitorSelection()




    {




        return WithSharedMonitorSelectionLock(() =>




        {




            string path = SharedMonitorSelectionPath();




            if (!File.Exists(path))




                return new Dictionary<string, object> { { "ok", true }, { "highlightedHwnd", "" }, { "hwndsCsv", "" }, { "selectedDesktopId", "" }, { "revision", "0" } };




            var row = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));




            string csv = NormalizeSelectionCsv(row != null && row.ContainsKey("hwndsCsv") ? Convert.ToString(row["hwndsCsv"]) : "");




            string highlighted = row != null && row.ContainsKey("highlightedHwnd") ? Convert.ToString(row["highlightedHwnd"]) : "";




            if (!("," + csv + ",").Contains("," + highlighted + ",")) highlighted = csv.Split(',')[0];




            string selectedDesktopId = row != null && row.ContainsKey("selectedDesktopId") ? Convert.ToString(row["selectedDesktopId"]) : "";




            string revision = row != null && row.ContainsKey("revision") ? Convert.ToString(row["revision"]) : "0";




            return new Dictionary<string, object> { { "ok", true }, { "highlightedHwnd", highlighted }, { "hwndsCsv", csv }, { "selectedDesktopId", selectedDesktopId }, { "revision", revision } };




        });




    }









    private static object SetSharedMonitorSelection(Dictionary<string, object> request)




    {




        return WithSharedMonitorSelectionLock(() =>




        {




            string csv = NormalizeSelectionCsv(GetString(request, "hwndsCsv"));




            string highlighted = GetString(request, "highlightedHwnd").Trim();




            if (!("," + csv + ",").Contains("," + highlighted + ",")) highlighted = csv.Split(',')[0];




            string selectedDesktopId = GetString(request, "selectedDesktopId").Trim();




            string revision = DateTime.UtcNow.Ticks.ToString(CultureInfo.InvariantCulture);




            var row = new Dictionary<string, object> { { "highlightedHwnd", highlighted }, { "hwndsCsv", csv }, { "selectedDesktopId", selectedDesktopId }, { "revision", revision } };




            File.WriteAllText(SharedMonitorSelectionPath(), Json.Serialize(row), Encoding.UTF8);




            return new Dictionary<string, object> { { "ok", true }, { "highlightedHwnd", highlighted }, { "hwndsCsv", csv }, { "selectedDesktopId", selectedDesktopId }, { "revision", revision } };




        });




    }









    private static string SharedMonitorRuntimePath()




    {




        string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DesktopWindowMonitor");




        Directory.CreateDirectory(dir);




        return Path.Combine(dir, "shared-runtime.json");




    }









    private static T WithSharedMonitorRuntimeLock<T>(Func<T> action)




    {




        using (var mutex = new Mutex(false, @"Local\DesktopWindowMonitor.SharedRuntime"))




        {




            bool held = false;




            try { held = mutex.WaitOne(3000); if (!held) throw new TimeoutException("Shared runtime lock timeout"); return action(); }




            finally { if (held) mutex.ReleaseMutex(); }




        }




    }









    private static Dictionary<string, object> ReadSharedMonitorRuntimeRow()




    {




        string path = SharedMonitorRuntimePath();




        if (!File.Exists(path)) return new Dictionary<string, object>();




        try { return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8)) ?? new Dictionary<string, object>(); }




        catch { return new Dictionary<string, object>(); }




    }









    private static object GetSharedMonitorRuntime()




    {




        return WithSharedMonitorRuntimeLock(() => {




            var root = ReadSharedMonitorRuntimeRow();




            return new Dictionary<string, object> { { "ok", true }, { "runtimeJson", Json.Serialize(root) }, { "hostProfile", NativeHostProfileId() } };




        });




    }









    private static object SetSharedMonitorRuntime(Dictionary<string, object> request)




    {




        return WithSharedMonitorRuntimeLock(() => {




            string key = GetString(request, "conversationKey").Trim();




            if (string.IsNullOrEmpty(key)) return Error("conversationKey required");




            long at = 0; long.TryParse(GetString(request, "at"), NumberStyles.Integer, CultureInfo.InvariantCulture, out at); if (at <= 0) at = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();




            var root = ReadSharedMonitorRuntimeRow();




            Dictionary<string, object> row = null;




            if (root.ContainsKey(key)) row = root[key] as Dictionary<string, object>;




            if (row == null) row = new Dictionary<string, object>();




            string kind = GetString(request, "kind").Trim().ToLowerInvariant();




            long prior = 0;




            if (kind == "generation") {




                if (row.ContainsKey("generationAt")) long.TryParse(Convert.ToString(row["generationAt"]), out prior);




                if (at >= prior) { row["generationAt"] = at.ToString(CultureInfo.InvariantCulture); row["generating"] = string.Equals(GetString(request,"generating"), "true", StringComparison.OrdinalIgnoreCase); row["attentionCue"] = GetString(request,"attentionCue"); row["completionCue"] = GetString(request,"completionCue"); }




            } else if (kind == "alert") {




                if (row.ContainsKey("alertAt")) long.TryParse(Convert.ToString(row["alertAt"]), out prior);




                if (at >= prior) { row["alertAt"] = at.ToString(CultureInfo.InvariantCulture); row["symbol"] = GetString(request,"symbol"); row["tone"] = GetString(request,"tone"); row["label"] = GetString(request,"label"); }




            } else if (kind == "ack") {




                if (row.ContainsKey("ackAt")) long.TryParse(Convert.ToString(row["ackAt"]), out prior);




                if (at >= prior) row["ackAt"] = at.ToString(CultureInfo.InvariantCulture);




            } else return Error("unsupported runtime kind");




            root[key] = row;




            File.WriteAllText(SharedMonitorRuntimePath(), Json.Serialize(root), new UTF8Encoding(false));




            return new Dictionary<string, object> { { "ok", true }, { "conversationKey", key }, { "at", at.ToString(CultureInfo.InvariantCulture) } };




        });




    }









    private static object AckExtensionReload(Dictionary<string, object> request)




    {




        try




        {




            string token = GetString(request, "token").Trim();




            if (string.IsNullOrEmpty(token)) return Error("reload token missing");




            DirectoryInfo cursor = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);




            string extensionDir = null;




            for (int depth = 0; depth < 5 && cursor != null; depth++, cursor = cursor.Parent)




            {




                string candidate = Path.Combine(cursor.FullName, "extension");




                if (File.Exists(Path.Combine(candidate, "manifest.json"))) { extensionDir = candidate; break; }




            }




            if (string.IsNullOrEmpty(extensionDir)) return Error("Monitor extension directory missing");




            File.WriteAllText(Path.Combine(extensionDir, ".reload-ack"), token, Encoding.UTF8);




            return new Dictionary<string, object> { { "ok", true }, { "token", token } };




        }




        catch (Exception ex) { return Error(ex.Message); }




    }














    private static bool TryGetInt(Dictionary<string, object> request, string key, out int value)




    {




        value = 0; object raw;




        return request != null && request.TryGetValue(key, out raw) && raw != null




            && int.TryParse(Convert.ToString(raw, CultureInfo.InvariantCulture), NumberStyles.Integer, CultureInfo.InvariantCulture, out value);




    }









    private static int GetInt(Dictionary<string, object> request, string key, int fallback, int min, int max)




    {




        object value; int parsed;




        if (request != null && request.TryGetValue(key, out value) && value != null && int.TryParse(Convert.ToString(value), out parsed))




            return Math.Max(min, Math.Min(max, parsed));




        return fallback;




    }









    private static string GetString(Dictionary<string, object> request, string key)




    {




        object value;




        return request != null && request.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : "";




    }









    private static Dictionary<string, object> Error(string message)




    {




        return new Dictionary<string, object> { { "ok", false }, { "error", message } };




    }




    private static byte[] ReadExact(Stream stream, int count)




    {




        if (count <= 0 || count > 1024 * 1024) return null;




        byte[] buffer = new byte[count];




        int offset = 0;




        while (offset < count)




        {




            int read = stream.Read(buffer, offset, count - offset);




            if (read <= 0) return null;




            offset += read;




        }




        return buffer;




    }









    private static void Write(Stream output, object value)




    {




        lock (NativeWriteLock)




        {




            byte[] payload = Encoding.UTF8.GetBytes(Json.Serialize(value));




            byte[] header = BitConverter.GetBytes(payload.Length);




            output.Write(header, 0, header.Length); output.Write(payload, 0, payload.Length); output.Flush();




        }




    }




}




