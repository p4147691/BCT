using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using Microsoft.Win32;

// Read-only desktop visual source for Monitor. Window geometry and pixels remain
// owned by MonitorDesktopHost/WGC; this module owns wallpaper pixels only.
internal static class DesktopVisualSnapshot
{
    private const string VirtualDesktopKey = @"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops";

    internal static bool CanHandle(Dictionary<string, object> request)
    {
        return string.Equals(GetString(request, "type"), "getDesktopVisualSnapshot", StringComparison.OrdinalIgnoreCase);
    }

    internal static object Handle(Dictionary<string, object> request)
    {
        Guid desktopId;
        if (!Guid.TryParse(GetString(request, "desktopId"), out desktopId)) return Error("Invalid desktopId.");
        int maxWidth = GetInt(request, "maxWidth", 960, 160, 1920);
        int maxHeight = GetInt(request, "maxHeight", 600, 100, 1080);
        int quality = GetInt(request, "quality", 68, 40, 90);
        string solidColor, solidProof;
        if (DesktopSolidColorSource.TryGet(desktopId, out solidColor, out solidProof))
        {
            return new Dictionary<string, object>
            {
                { "ok", true }, { "desktopId", desktopId.ToString("D") },
                { "wallpaperPath", "" },
                { "wallpaper", new Dictionary<string, object> {
                    { "mode", "solid" }, { "color", solidColor }, { "proof", solidProof }
                } }
            };
        }
        string path = ResolveWallpaperPath(desktopId);
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return new Dictionary<string, object>
            {
                { "ok", true }, { "desktopId", desktopId.ToString("D") },
                { "wallpaper", null }, { "wallpaperPath", path ?? string.Empty }
            };
        }

        try
        {
            byte[] bytes = File.ReadAllBytes(path);
            using (MemoryStream input = new MemoryStream(bytes))
            using (Image source = Image.FromStream(input))
            {
                Rectangle screen = SystemInformation.VirtualScreen;
                int screenWidth = Math.Max(1, screen.Width);
                int screenHeight = Math.Max(1, screen.Height);
                double scale = Math.Min(1.0, Math.Min((double)maxWidth / screenWidth, (double)maxHeight / screenHeight));
                int width = Math.Max(1, (int)Math.Round(screenWidth * scale));
                int height = Math.Max(1, (int)Math.Round(screenHeight * scale));
                WallpaperMode mode = ReadWallpaperMode();
                using (Bitmap resized = new Bitmap(width, height, PixelFormat.Format24bppRgb))
                using (Graphics graphics = Graphics.FromImage(resized))
                using (MemoryStream output = new MemoryStream())
                {
                    graphics.Clear(Color.Black);
                    graphics.CompositingQuality = CompositingQuality.HighQuality;
                    graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
                    graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
                    DrawWallpaper(graphics, source, width, height, scale, mode);
                    ImageCodecInfo jpeg = ImageCodecInfo.GetImageEncoders().First(codec => codec.MimeType == "image/jpeg");
                    using (EncoderParameters parameters = new EncoderParameters(1))
                    {
                        parameters.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, (long)quality);
                        resized.Save(output, jpeg, parameters);
                    }
                    return new Dictionary<string, object>
                    {
                        { "ok", true }, { "desktopId", desktopId.ToString("D") },
                        { "wallpaperPath", path },
                        { "wallpaper", new Dictionary<string, object>
                            {
                                { "dataUri", "data:image/jpeg;base64," + Convert.ToBase64String(output.ToArray()) },
                                { "originalWidth", screenWidth }, { "originalHeight", screenHeight },
                                { "width", width }, { "height", height }, { "mode", mode.ToString().ToLowerInvariant() }
                            }
                        }
                    };
                }
            }
        }
        catch (Exception ex) { return Error("Wallpaper snapshot failed: " + ex.Message); }
    }

    private enum WallpaperMode { Center, Tile, Stretch, Fit, Fill, Span }

    private static WallpaperMode ReadWallpaperMode()
    {
        try
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Control Panel\Desktop"))
            {
                string tile = Convert.ToString(key == null ? null : key.GetValue("TileWallpaper"));
                string style = Convert.ToString(key == null ? null : key.GetValue("WallpaperStyle"));
                if (tile == "1") return WallpaperMode.Tile;
                if (style == "2") return WallpaperMode.Stretch;
                if (style == "6") return WallpaperMode.Fit;
                if (style == "10") return WallpaperMode.Fill;
                if (style == "22") return WallpaperMode.Span;
                return WallpaperMode.Center;
            }
        }
        catch { return WallpaperMode.Fill; }
    }

    private static void DrawWallpaper(Graphics graphics, Image image, int width, int height, double desktopScale, WallpaperMode mode)
    {
        if (mode == WallpaperMode.Stretch)
        {
            graphics.DrawImage(image, 0, 0, width, height);
            return;
        }
        if (mode == WallpaperMode.Tile)
        {
            int tileWidth = Math.Max(1, (int)Math.Round(image.Width * desktopScale));
            int tileHeight = Math.Max(1, (int)Math.Round(image.Height * desktopScale));
            for (int y = 0; y < height; y += tileHeight)
                for (int x = 0; x < width; x += tileWidth)
                    graphics.DrawImage(image, x, y, tileWidth, tileHeight);
            return;
        }
        if (mode == WallpaperMode.Center)
        {
            int drawWidth = Math.Max(1, (int)Math.Round(image.Width * desktopScale));
            int drawHeight = Math.Max(1, (int)Math.Round(image.Height * desktopScale));
            graphics.DrawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
            return;
        }

        double imageScale = mode == WallpaperMode.Fit
            ? Math.Min((double)width / image.Width, (double)height / image.Height)
            : Math.Max((double)width / image.Width, (double)height / image.Height);
        int fittedWidth = Math.Max(1, (int)Math.Round(image.Width * imageScale));
        int fittedHeight = Math.Max(1, (int)Math.Round(image.Height * imageScale));
        graphics.DrawImage(image, (width - fittedWidth) / 2, (height - fittedHeight) / 2, fittedWidth, fittedHeight);
    }

    private static string ResolveWallpaperPath(Guid desktopId)
    {
        string id = "{" + desktopId.ToString("D").ToUpperInvariant() + "}";
        string path = ReadRegistryWallpaper(VirtualDesktopKey + @"\Desktops\" + id);
        return !string.IsNullOrWhiteSpace(path) ? path : ReadRegistryWallpaper(@"Control Panel\Desktop");
    }

    private static string ReadRegistryWallpaper(string keyPath)
    {
        try
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(keyPath))
            {
                string raw = key == null ? null : Convert.ToString(key.GetValue("Wallpaper"));
                return string.IsNullOrWhiteSpace(raw) ? string.Empty : Environment.ExpandEnvironmentVariables(raw);
            }
        }
        catch { return string.Empty; }
    }

    private static string GetString(Dictionary<string, object> request, string key)
    {
        object value;
        return request != null && request.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : string.Empty;
    }

    private static int GetInt(Dictionary<string, object> request, string key, int fallback, int min, int max)
    {
        object value;
        int parsed;
        if (request == null || !request.TryGetValue(key, out value) || value == null || !int.TryParse(Convert.ToString(value), out parsed)) return fallback;
        return Math.Max(min, Math.Min(max, parsed));
    }

    private static object Error(string message)
    {
        return new Dictionary<string, object> { { "ok", false }, { "error", message } };
    }
}
