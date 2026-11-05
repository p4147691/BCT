using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

class Program {
  internal const string ApprovedOrigin = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/";
  const string RuntimeConfigName = "bridge-runtime.json";

  sealed record RuntimeConfig(
    string ExtensionOrigin,
    string PythonExe,
    string PythonSha256,
    string McpUrl,
    string TokenPath,
    bool AllowLiveCore,
    string WorkId);

  static string? ReadString(JsonElement root, string name, bool allowEmpty = false) {
    if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String) return null;
    var text = value.GetString();
    return text is not null && (allowEmpty || !string.IsNullOrWhiteSpace(text)) ? text : null;
  }

  static RuntimeConfig? LoadRuntimeConfig() {
    var path = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", RuntimeConfigName));
    if (!File.Exists(path)) return null;
    try {
      using var document = JsonDocument.Parse(File.ReadAllBytes(path), new JsonDocumentOptions {
        AllowTrailingCommas = false,
        CommentHandling = JsonCommentHandling.Disallow
      });
      var root = document.RootElement;
      if (root.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
      var allowed = new HashSet<string>(StringComparer.Ordinal) {
        "extension_origin", "python_exe", "python_sha256", "mcp_url",
        "token_path", "allow_live_core", "work_id"
      };
      var seen = new HashSet<string>(StringComparer.Ordinal);
      foreach (var property in root.EnumerateObject())
        if (!allowed.Contains(property.Name) || !seen.Add(property.Name)) throw new InvalidDataException();
      var extensionOrigin = ReadString(root, "extension_origin");
      var pythonExe = ReadString(root, "python_exe");
      var pythonSha256 = ReadString(root, "python_sha256");
      var mcpUrl = ReadString(root, "mcp_url");
      var tokenPath = ReadString(root, "token_path");
      var workId = root.TryGetProperty("work_id", out _) ? ReadString(root, "work_id", allowEmpty: true) : "";
      if (!root.TryGetProperty("allow_live_core", out var allowLiveCore) ||
          allowLiveCore.ValueKind is not (JsonValueKind.True or JsonValueKind.False) ||
          extensionOrigin is null || pythonExe is null || pythonSha256 is null ||
          mcpUrl is null || tokenPath is null || workId is null) throw new InvalidDataException();
      return new RuntimeConfig(extensionOrigin, pythonExe, pythonSha256, mcpUrl,
                               tokenPath, allowLiveCore.GetBoolean(), workId);
    } catch (JsonException) { throw new InvalidDataException(); }
      catch (IOException) { throw new InvalidDataException(); }
      catch (UnauthorizedAccessException) { throw new InvalidDataException(); }
  }

  static RuntimeConfig LoadEnvironmentConfig() {
    var allowLiveCore = Environment.GetEnvironmentVariable("BCT_BRIDGE_ALLOW_LIVE_CORE");
    return new RuntimeConfig(
      Environment.GetEnvironmentVariable("BCT_BRIDGE_EXTENSION_ORIGIN") ?? "",
      Environment.GetEnvironmentVariable("BCT_BRIDGE_PYTHON_EXE") ?? "",
      Environment.GetEnvironmentVariable("BCT_BRIDGE_PYTHON_SHA256") ?? "",
      Environment.GetEnvironmentVariable("BCT_BRIDGE_MCP_URL") ?? "",
      Environment.GetEnvironmentVariable("BCT_BRIDGE_TOKEN_PATH") ?? "",
      allowLiveCore is "1" or "true" or "TRUE",
      Environment.GetEnvironmentVariable("BCT_BRIDGE_WORK_ID") ?? "");
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
    if (args.Length == 3 && args[0] == "--bridge-listener-seal-fixture")
      return BridgeListenerFixture.SealFixtureBoundary(args[1], args[2]);
    if (args.Length == 6 && args[0] == "--bridge-listener-server")
      return await BridgeListenerFixture.RunServer(
        args[1], args[2], args[3], args[4], args[5]);
    if (args.Length == 4 && args[0] == "--bridge-listener-client")
      return await BridgeListenerFixture.RunClient(args[1], args[2], args[3]);
    if (args.Length == 3 && args[0] == "--bridge-listener-fault-client")
      return await BridgeListenerFixture.RunFaultClient(args[1], args[2]);
    // Neither a PATH search nor a caller-supplied origin may choose the host runtime.
    // Chrome passes the caller origin first. On Windows it also passes the
    // documented native parent window handle as a decimal argument. Keep the
    // origin pinned and accept no other launcher-controlled arguments.
    if (args.Length is < 1 or > 2 ||
        !string.Equals(args[0], ApprovedOrigin, StringComparison.Ordinal)) return 4;
    const string ParentWindowPrefix = "--parent-window=";
    if (args.Length == 2) {
      if (!args[1].StartsWith(ParentWindowPrefix, StringComparison.Ordinal)) return 4;
      var parentWindow = args[1][ParentWindowPrefix.Length..];
      if (parentWindow.Length == 0 || !parentWindow.All(c => c is >= '0' and <= '9')) return 4;
    }
    RuntimeConfig config;
    try { config = LoadRuntimeConfig() ?? LoadEnvironmentConfig(); }
    catch (InvalidDataException) { return 5; }
    if (!string.Equals(config.ExtensionOrigin, ApprovedOrigin, StringComparison.Ordinal)) return 4;
    var python = config.PythonExe;
    if (string.IsNullOrWhiteSpace(python) || !Path.IsPathFullyQualified(python) ||
        !string.Equals(Path.GetFullPath(python), python, StringComparison.OrdinalIgnoreCase) ||
        !File.Exists(python) || Path.GetExtension(python).ToLowerInvariant() != ".exe") return 5;
    var expectedSha = config.PythonSha256;
    if (string.IsNullOrEmpty(expectedSha) || expectedSha.Length != 64 || !expectedSha.All(Uri.IsHexDigit)) return 5;
    if (!Uri.TryCreate(config.McpUrl, UriKind.Absolute, out var mcpUri) ||
        mcpUri.Scheme != Uri.UriSchemeHttp || !mcpUri.IsLoopback || mcpUri.AbsolutePath != "/mcp") return 5;
    if (!Path.IsPathFullyQualified(config.TokenPath) ||
        !string.Equals(Path.GetFullPath(config.TokenPath), config.TokenPath, StringComparison.OrdinalIgnoreCase)) return 5;
    try { using var runtime = File.OpenRead(python); if (!string.Equals(Convert.ToHexString(SHA256.HashData(runtime)), expectedSha, StringComparison.OrdinalIgnoreCase)) return 5; }
    catch (IOException) { return 5; }
    catch (UnauthorizedAccessException) { return 5; }
    var host = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "persistent_host.py"));
    if (!File.Exists(host)) return 5;
    var psi = new ProcessStartInfo(python) {
      UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true,
      RedirectStandardError = false, CreateNoWindow = true
    };
    psi.Environment["BCT_BRIDGE_EXTENSION_ORIGIN"] = config.ExtensionOrigin;
    psi.Environment["BCT_BRIDGE_PYTHON_EXE"] = config.PythonExe;
    psi.Environment["BCT_BRIDGE_PYTHON_SHA256"] = config.PythonSha256;
    psi.Environment["BCT_BRIDGE_MCP_URL"] = config.McpUrl;
    psi.Environment["BCT_BRIDGE_TOKEN_PATH"] = config.TokenPath;
    psi.Environment["BCT_BRIDGE_ALLOW_LIVE_CORE"] = config.AllowLiveCore ? "1" : "0";
    psi.Environment["BCT_BRIDGE_WORK_ID"] = config.WorkId;
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
