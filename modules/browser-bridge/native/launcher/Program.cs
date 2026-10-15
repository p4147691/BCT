using System.Diagnostics;
using System.Security.Cryptography;

class Program {
  internal const string ApprovedOrigin = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/";
  static async Task<int> Main(string[] args) {
    // Neither a PATH search nor a caller-supplied origin may choose the host runtime.
    if (args.Length != 1 || !string.Equals(args[0], ApprovedOrigin, StringComparison.Ordinal)) return 4;
    if (!string.Equals(Environment.GetEnvironmentVariable("BCT_BRIDGE_EXTENSION_ORIGIN"), ApprovedOrigin, StringComparison.Ordinal)) return 4;
    var python = Environment.GetEnvironmentVariable("BCT_BRIDGE_PYTHON_EXE");
    if (string.IsNullOrWhiteSpace(python) || !Path.IsPathFullyQualified(python) ||
        !string.Equals(Path.GetFullPath(python), python, StringComparison.OrdinalIgnoreCase) ||
        !File.Exists(python) || Path.GetExtension(python).ToLowerInvariant() != ".exe") return 5;
    var expectedSha = Environment.GetEnvironmentVariable("BCT_BRIDGE_PYTHON_SHA256");
    if (string.IsNullOrEmpty(expectedSha) || expectedSha.Length != 64 || !expectedSha.All(Uri.IsHexDigit)) return 5;
    try { using var runtime = File.OpenRead(python); if (!string.Equals(Convert.ToHexString(SHA256.HashData(runtime)), expectedSha, StringComparison.OrdinalIgnoreCase)) return 5; }
    catch (IOException) { return 5; }
    catch (UnauthorizedAccessException) { return 5; }
    var host = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "persistent_host.py"));
    if (!File.Exists(host)) return 5;
    var psi = new ProcessStartInfo(python) {
      UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true,
      RedirectStandardError = false, CreateNoWindow = true
    };
    psi.ArgumentList.Add(host); psi.ArgumentList.Add(args[0]);
    Process? started;
    try { started = Process.Start(psi); } catch { return 5; }
    using var process = started;
    if (process is null) return 5;
    var input = Console.OpenStandardInput(); var output = Console.OpenStandardOutput();
    var up = input.CopyToAsync(process.StandardInput.BaseStream).ContinueWith(_ => { try { process.StandardInput.Close(); } catch { } });
    var down = process.StandardOutput.BaseStream.CopyToAsync(output);
    await Task.WhenAll(up, down); await process.WaitForExitAsync(); return process.ExitCode;
  }
}
