using System.IO.Pipes;

// PR3-n compatibility fixture. All Windows owner/DACL/session/process policy
// comes from BridgeWindowsActivationPolicy, which PR3-o also composes.
internal static class BridgeActivationPolicyFixture {
  private const byte Request = 0x42;
  private const byte Verified = 0x56;
  private const byte Accepted = 0x4f;
  private const byte Denied = 0x15;
  private const string CredentialName = "fixture-binding.dpapi";
  private static readonly HashSet<string> Modes = new(StringComparer.Ordinal) {
    "valid", "session-mismatch", "root-acl", "file-acl", "pipe-acl",
  };

  internal static async Task<int> RunServer(
      string rootPath, string pipeName, string mode) {
    if (!Modes.Contains(mode) ||
        !BridgeWindowsActivationPolicy.ValidPipeName(pipeName)) return 4;
    bool rootCreated = false;
    bool fileCreated = false;
    int result = 7;
    string stage = "identity";
    string credentialPath = Path.Combine(rootPath, CredentialName);
    try {
      using var policy = new BridgeWindowsActivationPolicy();
      stage = "create-boundary";
      if (!policy.CreateFixtureRootAndFile(rootPath, credentialPath, Request))
        throw new InvalidOperationException();
      rootCreated = true;
      fileCreated = true;

      stage = "create-pipe";
      using NamedPipeServerStream pipe = policy.CreateFirstInstancePipe(pipeName);
      Console.Out.WriteLine("READY:" + policy.ServerSessionId.ToString(
        System.Globalization.CultureInfo.InvariantCulture));
      Console.Out.Flush();
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      stage = "wait-client";
      await pipe.WaitForConnectionAsync(timeout.Token);

      stage = "tamper-policy";
      if (!policy.TamperFixture(mode, rootPath, credentialPath, pipe.SafePipeHandle))
        throw new InvalidOperationException();

      stage = "pre-read-policy";
      uint? expectedSession = mode == "session-mismatch"
        ? (policy.ServerSessionId == uint.MaxValue ? 0 : policy.ServerSessionId + 1)
        : null;
      if (!policy.VerifyConnectedBeforeRead(
            pipe, rootPath, credentialPath,
            BridgeWindowsActivationPolicy.SelfDigest(), expectedSession, out _)) {
        Console.Out.WriteLine("DENIED_BEFORE_READ");
        Console.Out.Flush();
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        throw new InvalidOperationException();
      }

      await pipe.WriteAsync(new byte[] { Verified }.AsMemory(), timeout.Token);
      stage = "payload";
      byte[] request = new byte[1];
      if (await pipe.ReadAsync(request.AsMemory(), timeout.Token) != 1 ||
          request[0] != Request) throw new InvalidOperationException();
      await pipe.WriteAsync(new byte[] { Accepted }.AsMemory(), timeout.Token);
      result = 0;
    } catch {
      Console.Error.WriteLine("FIXTURE_DENIED:" + stage);
      result = 7;
    }

    bool cleaned = BridgeWindowsActivationPolicy.CleanupFixtureOwned(
      rootPath, credentialPath, rootCreated, fileCreated);
    Console.Out.WriteLine(cleaned ? "CLEANED" : "CLEANUP_FAILED");
    Console.Out.Flush();
    return cleaned ? result : 9;
  }

  internal static async Task<int> RunClient(string pipeName) {
    if (!BridgeWindowsActivationPolicy.ValidPipeName(pipeName)) return 4;
    try {
      using var pipe = new NamedPipeClientStream(
        ".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      await pipe.ConnectAsync(timeout.Token);
      byte[] policyGate = new byte[1];
      if (await pipe.ReadAsync(policyGate.AsMemory(), timeout.Token) != 1 ||
          policyGate[0] != Verified) {
        if (policyGate[0] == Denied) Console.Out.WriteLine("DENIED_WITHOUT_WRITE");
        return 7;
      }
      await pipe.WriteAsync(new byte[] { Request }.AsMemory(), timeout.Token);
      byte[] response = new byte[1];
      return await pipe.ReadAsync(response.AsMemory(), timeout.Token) == 1 &&
             response[0] == Accepted ? 0 : 7;
    } catch { return 7; }
  }
}
