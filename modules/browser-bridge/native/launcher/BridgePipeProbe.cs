using Microsoft.Win32.SafeHandles;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

// PR3-j probe only: validates Windows named-pipe primitives in a disposable
// test.  It is not a listener, does not load a secret, and is never called by
// the Native Messaging origin path.
internal static class BridgePipeProbe {
  private const byte Request = 0x42;
  private const byte Accepted = 0x4f;
  private const byte Denied = 0x15;

  [DllImport("kernel32.dll", SetLastError = true)]
  private static extern bool GetNamedPipeClientProcessId(
    SafePipeHandle pipe, out uint clientProcessId);

  internal static async Task<int> RunServer(string pipeName, string expectedClientSha256) {
    if (!ValidPipeName(pipeName) || !ValidSha256(expectedClientSha256)) return 4;
    try {
      using var pipe = new NamedPipeServerStream(
        pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
        PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
      Console.Out.WriteLine("READY");
      Console.Out.Flush();
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
      await pipe.WaitForConnectionAsync(timeout.Token);
      if (!GetNamedPipeClientProcessId(pipe.SafePipeHandle, out uint processId) ||
          !ClientMatches(processId, expectedClientSha256)) {
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        return 7;
      }
      var request = new byte[1];
      if (await pipe.ReadAsync(request, timeout.Token) != 1 || request[0] != Request) {
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        return 7;
      }
      await pipe.WriteAsync(new byte[] { Accepted }.AsMemory(), timeout.Token);
      return 0;
    } catch {
      return 7;
    }
  }

  internal static async Task<int> RunClient(string pipeName) {
    if (!ValidPipeName(pipeName)) return 4;
    try {
      using var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut,
                                                 PipeOptions.Asynchronous);
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
      await pipe.ConnectAsync(timeout.Token);
      await pipe.WriteAsync(new byte[] { Request }.AsMemory(), timeout.Token);
      var response = new byte[1];
      return await pipe.ReadAsync(response, timeout.Token) == 1 && response[0] == Accepted ? 0 : 7;
    } catch {
      return 7;
    }
  }

  private static bool ClientMatches(uint processId, string expectedClientSha256) {
    try {
      using var process = Process.GetProcessById(checked((int)processId));
      var path = process.MainModule?.FileName;
      if (string.IsNullOrEmpty(path) || !Path.IsPathFullyQualified(path)) return false;
      using var executable = File.OpenRead(path);
      return string.Equals(Convert.ToHexString(SHA256.HashData(executable)), expectedClientSha256,
                           StringComparison.OrdinalIgnoreCase);
    } catch {
      return false;
    }
  }

  private static bool ValidPipeName(string value) =>
    !string.IsNullOrEmpty(value) && value.Length <= 128 &&
    value.All(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_');

  private static bool ValidSha256(string value) =>
    value.Length == 64 && value.All(Uri.IsHexDigit);
}
