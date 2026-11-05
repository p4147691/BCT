using System.IO.Pipes;

// Explicit PR3-o one-shot composition fixture. It is not a runtime listener:
// Program reaches it only through exact test arguments, it accepts one client,
// and it never creates/deletes credential or binding state.
internal static class BridgeListenerFixture {
  private const byte Verified = 0x56;
  private const byte Accepted = 0x4f;
  private const byte Denied = 0x15;
  private static readonly HashSet<string> Modes = new(StringComparer.Ordinal) {
    "valid", "session-mismatch", "root-acl", "file-acl", "pipe-acl",
  };

  internal static int SealFixtureBoundary(string rootPath, string credentialPath) {
    try {
      using var policy = new BridgeWindowsActivationPolicy();
      return policy.SealExistingFixtureBoundary(rootPath, credentialPath) ? 0 : 7;
    } catch { return 7; }
  }

  internal static async Task<int> RunServer(
      string rootPath, string credentialPath, string pipeName,
      string expectedClientSha256, string mode) {
    if (!Modes.Contains(mode) ||
        !BridgeWindowsActivationPolicy.ValidPipeName(pipeName) ||
        !BridgeWindowsActivationPolicy.ValidSha256(expectedClientSha256)) return 4;
    string stage = "configuration";
    try {
      using var policy = new BridgeWindowsActivationPolicy();
      stage = "credential-policy";
      if (!policy.VerifyCredentialBoundary(rootPath, credentialPath))
        throw new InvalidOperationException();

      stage = "fresh-first-instance";
      using NamedPipeServerStream pipe = policy.CreateFirstInstancePipe(pipeName);
      Console.Out.WriteLine("READY");
      Console.Out.Flush();
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      stage = "connect";
      await pipe.WaitForConnectionAsync(timeout.Token);

      stage = "tamper-policy";
      if (!policy.TamperFixture(mode, rootPath, credentialPath, pipe.SafePipeHandle))
        throw new InvalidOperationException();
      uint? expectedSession = mode == "session-mismatch"
        ? (policy.ServerSessionId == uint.MaxValue ? 0 : policy.ServerSessionId + 1)
        : null;

      // One combined same-connection gate. No client-controlled frame byte is
      // touched until root/file/pipe ACL, logon session, PID and executable SHA
      // all pass and the Python composition authorizes this attestation.
      stage = "pre-read-policy";
      if (!policy.VerifyConnectedBeforeRead(
            pipe, rootPath, credentialPath, expectedClientSha256,
            expectedSession, out string digest)) {
        Console.Out.WriteLine("DENIED_BEFORE_READ");
        Console.Out.Flush();
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        return 7;
      }
      Console.Out.WriteLine("ATTEST:" + digest);
      Console.Out.Flush();
      stage = "binding-authorization";
      string? authorization = await Console.In.ReadLineAsync().WaitAsync(timeout.Token);
      if (!string.Equals(authorization, "AUTHORIZE", StringComparison.Ordinal)) {
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        return 7;
      }

      stage = "pre-read-policy-recheck";
      if (!policy.VerifyConnectedBeforeRead(
            pipe, rootPath, credentialPath, expectedClientSha256,
            expectedSession, out string finalDigest) ||
          !string.Equals(finalDigest, digest, StringComparison.Ordinal)) {
        Console.Out.WriteLine("DENIED_BEFORE_READ");
        Console.Out.Flush();
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        return 7;
      }

      await pipe.WriteAsync(new byte[] { Verified }.AsMemory(), timeout.Token);
      stage = "frame";
      byte[]? transport = await BridgePipeRelayFixture.ReadTransport(pipe, timeout.Token);
      if (transport is null) return 7;
      Console.Out.WriteLine("FRAME:" + digest + ":" + Convert.ToBase64String(transport));
      Console.Out.Flush();

      // A transport write is not delivery. Only the Python/Core completion
      // signal produces the client ACK; disconnect/UNKNOWN closes without retry.
      stage = "publish";
      string? published = await Console.In.ReadLineAsync().WaitAsync(timeout.Token);
      if (!string.Equals(published, "PUBLISH:OK", StringComparison.Ordinal)) return 7;
      await pipe.WriteAsync(new byte[] { Accepted }.AsMemory(), timeout.Token);
      return 0;
    } catch {
      Console.Error.WriteLine("LISTENER_DENIED:" + stage);
      return 7;
    }
  }

  internal static Task<int> RunClient(
      string pipeName, string fixturePath, string protectedSecretPath) =>
    BridgePipeRelayFixture.RunGatedClient(
      pipeName, fixturePath, protectedSecretPath);

  internal static async Task<int> RunFaultClient(string pipeName, string mode) {
    if (!BridgeWindowsActivationPolicy.ValidPipeName(pipeName) ||
        (mode != "disconnect" && mode != "partial")) return 4;
    try {
      using var pipe = new NamedPipeClientStream(
        ".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      await pipe.ConnectAsync(timeout.Token);
      byte[] gate = new byte[1];
      if (await pipe.ReadAsync(gate.AsMemory(), timeout.Token) != 1 ||
          gate[0] != Verified) return 7;
      if (mode == "partial")
        await pipe.WriteAsync(new byte[] { 12, 0 }.AsMemory(), timeout.Token);
      return 0;
    } catch { return 7; }
  }
}
