using System.Diagnostics;
using System.Security.Cryptography;

class Program {
  internal const string ApprovedOrigin = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/";
  // Windows Chrome may provide a second, decimal --parent-window=HANDLE argument.
  // It is metadata only, never used as authority or forwarded to Python.
  private static bool ValidChromeNativeMessagingArgs(string[] args) {
    if ((args.Length != 1 && args.Length != 2) ||
        !string.Equals(args[0], ApprovedOrigin, StringComparison.Ordinal)) return false;
    if (args.Length == 1) return true;
    const string prefix = "--parent-window=";
    string arg = args[1];
    if (!arg.StartsWith(prefix, StringComparison.Ordinal)) return false;
    var digits = arg.AsSpan(prefix.Length);
    if (digits.Length == 0 || digits.Length > 20) return false;
    foreach (char digit in digits)
      if (digit < '0' || digit > '9') return false;
    return ulong.TryParse(digits, out _);
  }

  static async Task<int> Main(string[] args) {
    // This has no Native Messaging authority and is reachable only through
    // explicit test arguments.  It keeps the future IPC acceptance mechanics
    // isolated from the production launcher path below.
    if (args.Length == 3 && args[0] == "--bridge-pipe-probe-server")
      return await BridgePipeProbe.RunServer(args[1], args[2]);
    if (args.Length == 2 && args[0] == "--bridge-pipe-probe-client")
      return await BridgePipeProbe.RunClient(args[1]);
    if (args.Length == 3 && args[0] == "--bridge-pipe-relay-server")
      return await BridgePipeRelayFixture.RunServer(args[1], args[2]);
    if (args.Length == 4 && args[0] == "--bridge-pipe-relay-client")
      return await BridgePipeRelayFixture.RunClient(args[1], args[2], args[3]);
    if (args.Length == 4 && args[0] == "--bridge-activation-policy-server")
      return await BridgeActivationPolicyFixture.RunServer(args[1], args[2], args[3]);
    if (args.Length == 2 && args[0] == "--bridge-activation-policy-client")
      return await BridgeActivationPolicyFixture.RunClient(args[1]);
    // Neither a PATH search nor a caller-supplied origin may choose the host runtime.
    if (!ValidChromeNativeMessagingArgs(args)) return 4;
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
