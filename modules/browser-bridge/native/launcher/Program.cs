using System.Diagnostics;

class Program {
  static async Task<int> Main(string[] args) {
    if (args.Length != 1 || !args[0].StartsWith("chrome-extension://", StringComparison.Ordinal)) return 4;
    var host = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "persistent_host.py"));
    if (!File.Exists(host)) return 5;
    var psi = new ProcessStartInfo("python") {
      UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true,
      RedirectStandardError = true, CreateNoWindow = true
    };
    psi.ArgumentList.Add(host); psi.ArgumentList.Add(args[0]);
    using var process = Process.Start(psi);
    if (process is null) return 5;
    var input = Console.OpenStandardInput(); var output = Console.OpenStandardOutput();
    var up = input.CopyToAsync(process.StandardInput.BaseStream).ContinueWith(_ => { try { process.StandardInput.Close(); } catch { } });
    var down = process.StandardOutput.BaseStream.CopyToAsync(output);
    await Task.WhenAll(up, down); await process.WaitForExitAsync(); return process.ExitCode;
  }
}
