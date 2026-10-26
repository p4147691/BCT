using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using System.Windows.Forms;

// Read-only Windows desktop background proof. No screenshot pixels leave process.
// An old registry Wallpaper file path is not proof that it is currently displayed.
internal static class DesktopSolidColorSource
{
    private const string DesktopRegistry = @"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops";
    private const string WallpapersRegistry = @"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers";
    [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr window);
    [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window, IntPtr dc);
    [DllImport("gdi32.dll")] private static extern uint GetPixel(IntPtr dc, int x, int y);
    internal static bool TryGet(Guid desktopId, out string rgb, out string proof)
    {
        rgb = ""; proof = "";
        int r,g,b;
        if (!GetBackgroundRgb(out r,out g,out b)) return false;
        string color = string.Format(CultureInfo.InvariantCulture,"#{0:X2}{1:X2}{2:X2}",r,g,b);
        try {
            using (RegistryKey key=Registry.CurrentUser.OpenSubKey(WallpapersRegistry)) {
                object mode=key==null ? null : key.GetValue("BackgroundType");
                if (mode!=null && Convert.ToInt32(mode,CultureInfo.InvariantCulture)==1) {
                    rgb=color;proof="windows-solid-mode";return true;
                }
            }
        } catch { /* only an explicit, trusted mode may bypass screen evidence */ }
        if (!IsCurrentDesktop(desktopId)) return false;
        if (!CurrentScreenShowsBackgroundColor(r,g,b)) return false;
        rgb=color; proof="current-desktop-screen-color";return true;
    }
    private static bool GetBackgroundRgb(out int r, out int g, out int b)
    {
        r=g=b=0;
        try {
            using(RegistryKey key=Registry.CurrentUser.OpenSubKey(@"Control Panel\Colors")) {
                string raw=Convert.ToString(key==null?null:key.GetValue("Background"));
                string[] parts=raw==null?new string[0]:raw.Split(new []{' ','\t'},StringSplitOptions.RemoveEmptyEntries);
                int a,c,d;
                if(parts.Length!=3 || !int.TryParse(parts[0],out a) || !int.TryParse(parts[1],out c) || !int.TryParse(parts[2],out d) ||
                   a<0||a>255||c<0||c>255||d<0||d>255) return false;
                r=a;g=c;b=d;return true;
            }
        } catch {return false;}
    }
    private static bool IsCurrentDesktop(Guid id)
    {
        try {
            using(RegistryKey key=Registry.CurrentUser.OpenSubKey(DesktopRegistry)) {
                byte[] raw=key==null?null:key.GetValue("CurrentVirtualDesktop") as byte[];
                return raw!=null && raw.Length==16 && new Guid(raw)==id;
            }
        } catch {return false;}
    }
    private static bool CurrentScreenShowsBackgroundColor(int r, int g, int b)
    {
        System.Drawing.Rectangle screen=SystemInformation.VirtualScreen;
        if(screen.Width<100 || screen.Height<100) return false;
        IntPtr dc=GetDC(IntPtr.Zero);
        if(dc==IntPtr.Zero) return false;
        try {
            int hits=0, columns=0, rows=0;
            bool[] hitCols=new bool[16],hitRows=new bool[12];
            for(int y=0;y<12;y++) for(int x=0;x<16;x++) {
                int px=screen.Left+(screen.Width*(2*x+1))/32;
                int py=screen.Top+(screen.Height*(2*y+1))/24;
                uint pixel=GetPixel(dc,px,py);
                if(pixel==0xFFFFFFFF) continue;
                if((pixel&255)==r && ((pixel>>8)&255)==g && ((pixel>>16)&255)==b) {
                    hits++;hitCols[x]=true;hitRows[y]=true;
                }
            }
            foreach(bool hit in hitCols) if(hit)columns++;
            foreach(bool hit in hitRows) if(hit)rows++;
            return hits>=8 && columns>=3 && rows>=2;
        } finally {ReleaseDC(IntPtr.Zero,dc);}
    }
}
