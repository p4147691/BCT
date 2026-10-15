using Microsoft.Win32.SafeHandles;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;

// PR3-n fixture only. It proves the Windows owner/DACL and logon-session
// policy needed before a production-disabled listener can be composed. It is
// reachable only through explicit test arguments and never carries a peer
// frame, resolves a binding, loads a secret, or invokes Core ingress.
internal static class BridgeActivationPolicyFixture {
  private const byte Request = 0x42;
  private const byte Accepted = 0x4f;
  private const byte Denied = 0x15;
  private const uint SecurityInformation = 0x00000001 | 0x00000004;
  private const uint ProtectedDaclSecurityInformation = 0x80000000;
  private const uint FileObject = 1;
  private const uint KernelObject = 6;
  private const uint SecurityDescriptorRevision = 1;
  private const uint GenericRead = 0x80000000;
  private const uint GenericWrite = 0x40000000;
  private const uint FileShareRead = 0x00000001;
  private const uint CreateNew = 1;
  private const uint FileAttributeNormal = 0x00000080;
  private const uint FileFlagOverlapped = 0x40000000;
  private const uint FileFlagFirstPipeInstance = 0x00080000;
  private const uint PipeAccessDuplex = 0x00000003;
  private const uint PipeRejectRemoteClients = 0x00000008;
  private const uint InvalidFileAttributes = 0xffffffff;
  private const uint FileAttributeReparsePoint = 0x00000400;
  private const int ErrorSuccess = 0;
  private const int ErrorAlreadyExists = 183;
  private const string CredentialName = "fixture-binding.dpapi";
  private static readonly HashSet<string> Modes = new(StringComparer.Ordinal) {
    "valid", "session-mismatch", "root-acl", "file-acl", "pipe-acl",
  };

  [StructLayout(LayoutKind.Sequential)]
  private struct SecurityAttributes {
    internal int Length;
    internal IntPtr SecurityDescriptor;
    [MarshalAs(UnmanagedType.Bool)] internal bool InheritHandle;
  }

  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(
    string text, uint revision, out IntPtr descriptor, out uint size);

  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool ConvertSecurityDescriptorToStringSecurityDescriptorW(
    IntPtr descriptor, uint revision, uint information,
    out IntPtr text, out uint length);

  [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
  private static extern uint GetNamedSecurityInfoW(
    string name, uint objectType, uint information,
    out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl,
    out IntPtr descriptor);

  [DllImport("advapi32.dll")]
  private static extern uint GetSecurityInfo(
    SafePipeHandle handle, uint objectType, uint information,
    out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl,
    out IntPtr descriptor);

  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool SetFileSecurityW(
    string name, uint information, IntPtr descriptor);

  [DllImport("advapi32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool SetKernelObjectSecurity(
    SafePipeHandle handle, uint information, IntPtr descriptor);

  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool CreateDirectoryW(
    string path, ref SecurityAttributes attributes);

  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  private static extern SafeFileHandle CreateFileW(
    string path, uint access, uint share, ref SecurityAttributes attributes,
    uint creation, uint flags, IntPtr template);

  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  private static extern SafePipeHandle CreateNamedPipeW(
    string name, uint openMode, uint pipeMode, uint maxInstances,
    uint outputBufferSize, uint inputBufferSize, uint timeout,
    ref SecurityAttributes attributes);

  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  private static extern uint GetFileAttributesW(string path);

  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool GetNamedPipeClientSessionId(
    SafePipeHandle pipe, out uint clientSessionId);

  [DllImport("kernel32.dll")]
  private static extern IntPtr LocalFree(IntPtr memory);

  private sealed class NativeDescriptor : IDisposable {
    internal IntPtr Value { get; private set; }
    internal string Canonical { get; }

    internal NativeDescriptor(string sddl) {
      if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, SecurityDescriptorRevision, out IntPtr value, out _) ||
          value == IntPtr.Zero) throw new InvalidOperationException();
      Value = value;
      Canonical = DescriptorText(value);
    }

    public void Dispose() {
      if (Value != IntPtr.Zero) LocalFree(Value);
      Value = IntPtr.Zero;
    }
  }

  internal static async Task<int> RunServer(
      string rootPath, string pipeName, string mode) {
    if (!Modes.Contains(mode) || !ValidPipeName(pipeName) ||
        !StrictNewRoot(rootPath)) return 4;
    bool rootCreated = false;
    bool fileCreated = false;
    int result = 7;
    string credentialPath = Path.Combine(rootPath, CredentialName);
    try {
      using WindowsIdentity identity = WindowsIdentity.GetCurrent();
      string userSid = identity.User?.Value ?? throw new InvalidOperationException();
      string logonSid = LogonSid(identity) ?? throw new InvalidOperationException();
      string exactSddl = $"O:{userSid}D:P(A;;FA;;;{logonSid})(A;;FA;;;SY)";
      string looseSddl = exactSddl + "(A;;FA;;;WD)";
      using var exact = new NativeDescriptor(exactSddl);
      using var loose = new NativeDescriptor(looseSddl);
      SecurityAttributes attributes = Attributes(exact);

      if (!CreateDirectoryW(rootPath, ref attributes)) {
        if (Marshal.GetLastWin32Error() == ErrorAlreadyExists) return 7;
        throw new InvalidOperationException();
      }
      rootCreated = true;
      if (!NamedSecurityMatches(rootPath, exact.Canonical))
        throw new InvalidOperationException();

      SafeFileHandle file = CreateFileW(
        credentialPath, GenericRead | GenericWrite, FileShareRead,
        ref attributes, CreateNew, FileAttributeNormal, IntPtr.Zero);
      if (file.IsInvalid) {
        file.Dispose();
        throw new InvalidOperationException();
      }
      fileCreated = true;
      using (var stream = new FileStream(file, FileAccess.ReadWrite)) {
        stream.WriteByte(Request);
        stream.Flush(true);
      }
      if (!NamedSecurityMatches(credentialPath, exact.Canonical))
        throw new InvalidOperationException();

      SafePipeHandle pipeHandle = CreateNamedPipeW(
        @"\\.\pipe\" + pipeName,
        PipeAccessDuplex | FileFlagOverlapped | FileFlagFirstPipeInstance,
        PipeRejectRemoteClients, 1, 4096, 4096, 0, ref attributes);
      if (pipeHandle.IsInvalid) {
        pipeHandle.Dispose();
        throw new InvalidOperationException();
      }
      using var pipe = new NamedPipeServerStream(
        PipeDirection.InOut, true, false, pipeHandle);
      if (!KernelSecurityMatches(pipe.SafePipeHandle, exact.Canonical))
        throw new InvalidOperationException();

      uint serverSession = checked((uint)Process.GetCurrentProcess().SessionId);
      uint expectedClientSession = mode == "session-mismatch"
        ? (serverSession == uint.MaxValue ? 0 : serverSession + 1)
        : serverSession;
      Console.Out.WriteLine("READY:" + serverSession.ToString(
        System.Globalization.CultureInfo.InvariantCulture));
      Console.Out.Flush();
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      await pipe.WaitForConnectionAsync(timeout.Token);

      // Deliberately mutate one policy object only after connection so the
      // fixture proves that the pre-read revalidation, rather than only the
      // creation-time check, rejects a changed boundary.
      if (mode == "root-acl" && !SetFileSecurityW(
            rootPath, SecurityInformation | ProtectedDaclSecurityInformation,
            loose.Value)) throw new InvalidOperationException();
      if (mode == "file-acl" && !SetFileSecurityW(
            credentialPath, SecurityInformation | ProtectedDaclSecurityInformation,
            loose.Value)) throw new InvalidOperationException();
      if (mode == "pipe-acl" && !SetKernelObjectSecurity(
            pipe.SafePipeHandle,
            SecurityInformation | ProtectedDaclSecurityInformation,
            loose.Value)) throw new InvalidOperationException();

      // Recheck every mutable policy object after connect and before touching
      // attacker-controlled bytes.
      if (!NamedSecurityMatches(rootPath, exact.Canonical) ||
          !NamedSecurityMatches(credentialPath, exact.Canonical) ||
          !KernelSecurityMatches(pipe.SafePipeHandle, exact.Canonical) ||
          !GetNamedPipeClientSessionId(pipe.SafePipeHandle, out uint clientSession) ||
          clientSession != expectedClientSession) {
        Console.Out.WriteLine("DENIED_BEFORE_READ");
        Console.Out.Flush();
        await pipe.WriteAsync(new byte[] { Denied }.AsMemory(), timeout.Token);
        throw new InvalidOperationException();
      }

      byte[] request = new byte[1];
      if (await pipe.ReadAsync(request.AsMemory(), timeout.Token) != 1 ||
          request[0] != Request) throw new InvalidOperationException();
      await pipe.WriteAsync(new byte[] { Accepted }.AsMemory(), timeout.Token);
      result = 0;
    } catch {
      result = 7;
    }

    bool cleaned = CleanupOwned(rootPath, credentialPath, rootCreated, fileCreated);
    Console.Out.WriteLine(cleaned ? "CLEANED" : "CLEANUP_FAILED");
    Console.Out.Flush();
    return cleaned ? result : 9;
  }

  internal static async Task<int> RunClient(string pipeName) {
    if (!ValidPipeName(pipeName)) return 4;
    try {
      using var pipe = new NamedPipeClientStream(
        ".", pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
      using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
      await pipe.ConnectAsync(timeout.Token);
      await pipe.WriteAsync(new byte[] { Request }.AsMemory(), timeout.Token);
      byte[] response = new byte[1];
      return await pipe.ReadAsync(response.AsMemory(), timeout.Token) == 1 &&
             response[0] == Accepted ? 0 : 7;
    } catch {
      return 7;
    }
  }

  private static SecurityAttributes Attributes(NativeDescriptor descriptor) => new() {
    Length = Marshal.SizeOf<SecurityAttributes>(),
    SecurityDescriptor = descriptor.Value,
    InheritHandle = false,
  };

  private static string? LogonSid(WindowsIdentity identity) {
    if (identity.Groups is null) return null;
    foreach (IdentityReference group in identity.Groups) {
      SecurityIdentifier? sid = group as SecurityIdentifier;
      if (sid is not null && sid.Value.StartsWith("S-1-5-5-", StringComparison.Ordinal))
        return sid.Value;
    }
    return null;
  }

  private static bool NamedSecurityMatches(string path, string expected) {
    uint error = GetNamedSecurityInfoW(
      path, FileObject, SecurityInformation,
      out _, out _, out _, out _, out IntPtr descriptor);
    if (error != ErrorSuccess || descriptor == IntPtr.Zero) return false;
    try { return string.Equals(DescriptorText(descriptor), expected, StringComparison.Ordinal); }
    catch { return false; }
    finally { LocalFree(descriptor); }
  }

  private static bool KernelSecurityMatches(SafePipeHandle handle, string expected) {
    uint error = GetSecurityInfo(
      handle, KernelObject, SecurityInformation,
      out _, out _, out _, out _, out IntPtr descriptor);
    if (error != ErrorSuccess || descriptor == IntPtr.Zero) return false;
    try { return string.Equals(DescriptorText(descriptor), expected, StringComparison.Ordinal); }
    catch { return false; }
    finally { LocalFree(descriptor); }
  }

  private static string DescriptorText(IntPtr descriptor) {
    if (!ConvertSecurityDescriptorToStringSecurityDescriptorW(
          descriptor, SecurityDescriptorRevision, SecurityInformation,
          out IntPtr text, out _) || text == IntPtr.Zero)
      throw new InvalidOperationException();
    try { return Marshal.PtrToStringUni(text) ?? throw new InvalidOperationException(); }
    finally { LocalFree(text); }
  }

  private static bool StrictNewRoot(string path) {
    if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path)) return false;
    try {
      string full = Path.GetFullPath(path);
      if (!string.Equals(full, path, StringComparison.OrdinalIgnoreCase) ||
          GetFileAttributesW(full) != InvalidFileAttributes) return false;
      string? parent = Path.GetDirectoryName(full);
      return !string.IsNullOrEmpty(parent) && AncestorsAreNotReparsePoints(parent);
    } catch {
      return false;
    }
  }

  private static bool AncestorsAreNotReparsePoints(string path) {
    string? current = path;
    while (!string.IsNullOrEmpty(current)) {
      uint attributes = GetFileAttributesW(current);
      if (attributes == InvalidFileAttributes ||
          (attributes & FileAttributeReparsePoint) != 0) return false;
      string? parent = Path.GetDirectoryName(current);
      if (string.Equals(parent, current, StringComparison.OrdinalIgnoreCase)) break;
      current = parent;
    }
    return true;
  }

  private static bool CleanupOwned(
      string root, string credential, bool rootCreated, bool fileCreated) {
    try {
      if (fileCreated) File.Delete(credential);
      if (rootCreated) Directory.Delete(root, false);
      return !File.Exists(credential) && !Directory.Exists(root);
    } catch {
      return false;
    }
  }

  private static bool ValidPipeName(string value) =>
    !string.IsNullOrEmpty(value) && value.Length <= 128 &&
    value.All(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_');
}
