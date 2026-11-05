using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

// PR3-m fixture only. It proves that the built Host can unprotect a disposable
// Bridge credential, create the canonical signed frame and carry it through a
// process-verified same-user pipe. It is unreachable from the Native Messaging
// origin path and creates no listener unless explicit test arguments are used.
internal static class BridgePipeRelayFixture {
  private const int UiForbidden = 0x1;
  private const int MaxTransportBytes = 49152;
  private const byte Accepted = 0x4f;
  private const byte Denied = 0x15;
  private const string Origin = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/";
  private static readonly byte[] ContextPrefix =
    Encoding.ASCII.GetBytes("bct-bridge-peer-secret-v1\0");

  [StructLayout(LayoutKind.Sequential)]
  private struct DataBlob {
    internal uint Size;
    internal IntPtr Data;
  }

  [DllImport("crypt32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool CryptUnprotectData(
    ref DataBlob dataIn, IntPtr description, ref DataBlob optionalEntropy,
    IntPtr reserved, IntPtr prompt, int flags, out DataBlob dataOut);

  [DllImport("kernel32.dll")]
  private static extern IntPtr LocalFree(IntPtr memory);

  private sealed record RelayFixture(
    string PeerId, long BindingGeneration, string LauncherSha256,
    string OriginValue, long Sequence, byte[] Envelope);

  internal static async Task<int> RunServer(string pipeName, string expectedClientSha256) {
    if (!BridgeWindowsActivationPolicy.ValidPipeName(pipeName) ||
        !BridgeWindowsActivationPolicy.ValidSha256(expectedClientSha256)) return 4;
    try {
      using var pipe = new NamedPipeServerStream(
        pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
        PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
      Console.Out.WriteLine("READY");
      Console.Out.Flush();
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      await pipe.WaitForConnectionAsync(timeout.Token);
      if (!BridgeWindowsActivationPolicy.VerifyConnectedProcess(
            pipe.SafePipeHandle, expectedClientSha256, out string digest)) {
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        return 7;
      }
      byte[]? transport = await ReadTransport(pipe, timeout.Token);
      if (transport is null) return 7;
      Console.Out.WriteLine("FRAME:" + digest + ":" + Convert.ToBase64String(transport));
      Console.Out.Flush();
      await pipe.WriteAsync(new byte[] { Accepted }.AsMemory(), timeout.Token);
      return 0;
    } catch {
      return 7;
    }
  }

  internal static async Task<int> RunClient(
      string pipeName, string fixturePath, string protectedSecretPath) {
    return await RunClient(
      pipeName, fixturePath, protectedSecretPath, waitForPolicyGate: false);
  }

  internal static async Task<int> RunGatedClient(
      string pipeName, string fixturePath, string protectedSecretPath) {
    return await RunClient(
      pipeName, fixturePath, protectedSecretPath, waitForPolicyGate: true);
  }

  private static async Task<int> RunClient(
      string pipeName, string fixturePath, string protectedSecretPath,
      bool waitForPolicyGate) {
    if (!BridgeWindowsActivationPolicy.ValidPipeName(pipeName) || !StrictFile(fixturePath) ||
        !StrictFile(protectedSecretPath)) return 4;
    byte[]? secret = null;
    try {
      RelayFixture fixture = LoadFixture(fixturePath);
      string selfDigest = BridgeWindowsActivationPolicy.SelfDigest();
      if (!string.Equals(selfDigest, fixture.LauncherSha256,
                         StringComparison.Ordinal)) return 7;
      byte[] protectedSecret = File.ReadAllBytes(protectedSecretPath);
      if (protectedSecret.Length == 0 || protectedSecret.Length > 65536) return 7;
      secret = Unprotect(
        protectedSecret, BindingContext(fixture.PeerId, fixture.BindingGeneration));
      if (secret.Length != 32) return 7;
      byte[] transport = BuildTransport(fixture, secret);
      using var pipe = new NamedPipeClientStream(
        ".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      await pipe.ConnectAsync(timeout.Token);
      if (waitForPolicyGate) {
        byte[] gate = new byte[1];
        if (await pipe.ReadAsync(gate.AsMemory(), timeout.Token) != 1 ||
            gate[0] != 0x56) {
          if (gate[0] == Denied) Console.Out.WriteLine("DENIED_WITHOUT_WRITE");
          return 7;
        }
      }
      await pipe.WriteAsync(transport.AsMemory(), timeout.Token);
      byte[] response = new byte[1];
      return await pipe.ReadAsync(response, timeout.Token) == 1 &&
             response[0] == Accepted ? 0 : 7;
    } catch {
      return 7;
    } finally {
      if (secret is not null) CryptographicOperations.ZeroMemory(secret);
    }
  }

  private static RelayFixture LoadFixture(string path) {
    byte[] raw = File.ReadAllBytes(path);
    if (raw.Length == 0 || raw.Length > 32768) throw new InvalidDataException();
    using JsonDocument document = JsonDocument.Parse(raw, new JsonDocumentOptions {
      AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow,
      MaxDepth = 4,
    });
    JsonElement root = document.RootElement;
    if (root.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
    string[] expected = { "peer_id", "binding_generation", "launcher_sha256",
                          "origin", "sequence", "envelope_b64" };
    var names = new HashSet<string>(StringComparer.Ordinal);
    foreach (JsonProperty property in root.EnumerateObject()) {
      if (!names.Add(property.Name)) throw new InvalidDataException();
    }
    if (names.Count != expected.Length || expected.Any(name => !names.Contains(name)))
      throw new InvalidDataException();
    string peerId = root.GetProperty("peer_id").GetString() ?? "";
    long generation = root.GetProperty("binding_generation").GetInt64();
    string launcher = root.GetProperty("launcher_sha256").GetString() ?? "";
    string origin = root.GetProperty("origin").GetString() ?? "";
    long sequence = root.GetProperty("sequence").GetInt64();
    string encoded = root.GetProperty("envelope_b64").GetString() ?? "";
    if (!ValidPeerId(peerId) || generation < 1 ||
        !BridgeWindowsActivationPolicy.ValidSha256(launcher) ||
        launcher != launcher.ToLowerInvariant() || origin != Origin || sequence < 1)
      throw new InvalidDataException();
    byte[] envelope = Convert.FromBase64String(encoded);
    if (envelope.Length == 0 || envelope.Length > 8192 ||
        Convert.ToBase64String(envelope) != encoded) throw new InvalidDataException();
    return new RelayFixture(peerId, generation, launcher, origin, sequence, envelope);
  }

  private static byte[] BuildTransport(RelayFixture fixture, byte[] secret) {
    byte[] proofInput = JsonSerializer.SerializeToUtf8Bytes(new object[] {
      "bct-bridge-peer-adapter-v1", fixture.PeerId, fixture.BindingGeneration,
      fixture.LauncherSha256, fixture.OriginValue, fixture.Sequence,
      Convert.ToHexString(fixture.Envelope).ToLowerInvariant(),
    }, new JsonSerializerOptions { Encoder = JavaScriptEncoder.Default });
    string proof = Convert.ToHexString(HMACSHA256.HashData(secret, proofInput))
      .ToLowerInvariant();
    byte[] peerFrame;
    using (var stream = new MemoryStream()) {
      using (var writer = new Utf8JsonWriter(stream)) {
        writer.WriteStartObject();
        writer.WriteNumber("version", 1);
        writer.WriteString("peer_id", fixture.PeerId);
        writer.WriteNumber("binding_generation", fixture.BindingGeneration);
        writer.WriteString("launcher_sha256", fixture.LauncherSha256);
        writer.WriteString("origin", fixture.OriginValue);
        writer.WriteNumber("sequence", fixture.Sequence);
        writer.WriteString("envelope_b64", Convert.ToBase64String(fixture.Envelope));
        writer.WriteString("proof", proof);
        writer.WriteEndObject();
      }
      peerFrame = stream.ToArray();
    }
    byte[] body;
    using (var stream = new MemoryStream()) {
      using (var writer = new Utf8JsonWriter(stream)) {
        writer.WriteStartObject();
        writer.WriteNumber("version", 1);
        writer.WriteString("operation", "peer_frame");
        writer.WriteString("peer_frame_b64", Convert.ToBase64String(peerFrame));
        writer.WriteEndObject();
      }
      body = stream.ToArray();
    }
    if (body.Length == 0 || body.Length > MaxTransportBytes)
      throw new InvalidDataException();
    byte[] transport = new byte[4 + body.Length];
    BitConverter.GetBytes(body.Length).CopyTo(transport, 0);
    Buffer.BlockCopy(body, 0, transport, 4, body.Length);
    return transport;
  }

  private static byte[] Unprotect(byte[] protectedValue, byte[] entropy) {
    GCHandle valueHandle = GCHandle.Alloc(protectedValue, GCHandleType.Pinned);
    GCHandle entropyHandle = GCHandle.Alloc(entropy, GCHandleType.Pinned);
    var input = new DataBlob { Size = checked((uint)protectedValue.Length),
                               Data = valueHandle.AddrOfPinnedObject() };
    var context = new DataBlob { Size = checked((uint)entropy.Length),
                                 Data = entropyHandle.AddrOfPinnedObject() };
    DataBlob output = default;
    try {
      if (!CryptUnprotectData(ref input, IntPtr.Zero, ref context, IntPtr.Zero,
                              IntPtr.Zero, UiForbidden, out output) ||
          output.Data == IntPtr.Zero || output.Size != 32) {
        throw new CryptographicException();
      }
      byte[] result = new byte[checked((int)output.Size)];
      Marshal.Copy(output.Data, result, 0, checked((int)output.Size));
      return result;
    } finally {
      if (output.Data != IntPtr.Zero) LocalFree(output.Data);
      entropyHandle.Free();
      valueHandle.Free();
    }
  }

  private static byte[] BindingContext(string peerId, long generation) {
    byte[] suffix = Encoding.UTF8.GetBytes(peerId + "\0" + generation.ToString(
      System.Globalization.CultureInfo.InvariantCulture));
    byte[] result = new byte[ContextPrefix.Length + suffix.Length];
    Buffer.BlockCopy(ContextPrefix, 0, result, 0, ContextPrefix.Length);
    Buffer.BlockCopy(suffix, 0, result, ContextPrefix.Length, suffix.Length);
    return result;
  }

  internal static async Task<byte[]?> ReadTransport(
      Stream stream, CancellationToken token) {
    byte[] prefix = new byte[4];
    if (!await ReadExact(stream, prefix, token)) return null;
    int bodyLength = BitConverter.ToInt32(prefix, 0);
    if (bodyLength <= 0 || bodyLength > MaxTransportBytes) return null;
    byte[] body = new byte[bodyLength];
    if (!await ReadExact(stream, body, token)) return null;
    byte[] transport = new byte[4 + bodyLength];
    Buffer.BlockCopy(prefix, 0, transport, 0, 4);
    Buffer.BlockCopy(body, 0, transport, 4, bodyLength);
    return transport;
  }

  private static async Task<bool> ReadExact(
      Stream stream, byte[] destination, CancellationToken token) {
    int offset = 0;
    while (offset < destination.Length) {
      int count = await stream.ReadAsync(destination.AsMemory(offset), token);
      if (count == 0) return false;
      offset += count;
    }
    return true;
  }

  private static bool StrictFile(string value) {
    if (string.IsNullOrWhiteSpace(value) || !Path.IsPathFullyQualified(value)) return false;
    try {
      string full = Path.GetFullPath(value);
      var info = new FileInfo(full);
      return string.Equals(full, value, StringComparison.OrdinalIgnoreCase) &&
             info.Exists && info.LinkTarget is null;
    } catch {
      return false;
    }
  }

  private static bool ValidPeerId(string value) =>
    !string.IsNullOrEmpty(value) && value.Length <= 128 &&
    value.All(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_' or '.');

}
