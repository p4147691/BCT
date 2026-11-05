using Microsoft.Win32.SafeHandles;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;

// Shared Windows policy primitive for explicit, production-disabled fixtures.
// It owns no runtime path or listener loop.  A caller supplies every path,
// pipe name and expected executable digest and must dispose every returned
// handle.  Both PR3-n and PR3-o use this exact implementation.
internal sealed class BridgeWindowsActivationPolicy : IDisposable {
  private const uint DaclSecurityInformation = 0x00000004;
  private const uint SecurityInformation = 0x00000001 | DaclSecurityInformation;
  private const uint ProtectedDaclSecurityInformation = 0x80000000;
  private const uint FileObject = 1;
  private const uint KernelObject = 6;
  private const uint SecurityDescriptorRevision = 1;
  private const int FileAllAccess = 0x001f01ff;
  private const uint GenericRead = 0x80000000;
  private const uint GenericWrite = 0x40000000;
  private const uint FileShareRead = 0x00000001;
  private const uint CreateNew = 1;
  private const uint FileAttributeNormal = 0x00000080;
  private const uint FileFlagOverlapped = 0x40000000;
  private const uint FileFlagFirstPipeInstance = 0x00080000;
  private const uint PipeAccessDuplex = 0x00000003;
  private const uint PipeRejectRemoteClients = 0x00000008;
  private const uint WriteDac = 0x00040000;
  private const uint InvalidFileAttributes = 0xffffffff;
  private const uint FileAttributeReparsePoint = 0x00000400;
  private const int ErrorSuccess = 0;
  private const int TokenLogonSid = 28;

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

  [DllImport("kernel32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool GetNamedPipeClientProcessId(
    SafePipeHandle pipe, out uint clientProcessId);

  [DllImport("advapi32.dll")]
  private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);

  [DllImport("advapi32.dll", SetLastError = true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  private static extern bool GetTokenInformation(
    SafeAccessTokenHandle token, int informationClass, IntPtr information,
    uint informationLength, out uint returnLength);

  [DllImport("kernel32.dll")]
  private static extern IntPtr LocalFree(IntPtr memory);

  private sealed class NativeDescriptor : IDisposable {
    internal IntPtr Value { get; private set; }

    internal NativeDescriptor(string sddl) {
      if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, SecurityDescriptorRevision, out IntPtr value, out _) ||
          value == IntPtr.Zero) throw new InvalidOperationException();
      Value = value;
    }

    public void Dispose() {
      if (Value != IntPtr.Zero) LocalFree(Value);
      Value = IntPtr.Zero;
    }
  }

  private readonly WindowsIdentity identity;
  private readonly NativeDescriptor exact;
  private readonly NativeDescriptor loose;
  internal string UserSid { get; }
  internal string LogonSid { get; }
  internal uint ServerSessionId { get; }

  internal BridgeWindowsActivationPolicy() {
    identity = WindowsIdentity.GetCurrent();
    UserSid = identity.User?.Value ?? throw new InvalidOperationException();
    LogonSid = ReadLogonSid(identity);
    exact = new NativeDescriptor($"O:{UserSid}D:P(A;;FA;;;{LogonSid})(A;;FA;;;SY)");
    loose = new NativeDescriptor(
      $"O:{UserSid}D:P(A;;FA;;;{LogonSid})(A;;FA;;;SY)(A;;FA;;;WD)");
    ServerSessionId = checked((uint)Process.GetCurrentProcess().SessionId);
  }

  internal bool CreateFixtureRootAndFile(
      string rootPath, string credentialPath, byte initialValue) {
    if (!StrictNewRoot(rootPath) || !StrictChild(rootPath, credentialPath)) return false;
    SecurityAttributes attributes = Attributes(exact);
    if (!CreateDirectoryW(rootPath, ref attributes)) return false;
    bool fileCreated = false;
    try {
      SafeFileHandle file = CreateFileW(
        credentialPath, GenericRead | GenericWrite, FileShareRead,
        ref attributes, CreateNew, FileAttributeNormal, IntPtr.Zero);
      if (file.IsInvalid) { file.Dispose(); return false; }
      fileCreated = true;
      using (var stream = new FileStream(file, FileAccess.ReadWrite)) {
        stream.WriteByte(initialValue);
        stream.Flush(true);
      }
      return VerifyCredentialBoundary(rootPath, credentialPath);
    } finally {
      if (!fileCreated || !VerifyCredentialBoundary(rootPath, credentialPath))
        CleanupFixtureOwned(rootPath, credentialPath, true, fileCreated);
    }
  }

  // Explicit-fixture-only bridge from PR3-h's disposable file to the exact
  // Windows policy.  It never creates paths and refuses reparse/foreign paths.
  internal bool SealExistingFixtureBoundary(string rootPath, string credentialPath) {
    if (!StrictExistingRoot(rootPath)) {
      Console.Error.WriteLine("SEAL_DENIED:root");
      return false;
    }
    if (!StrictExistingFile(credentialPath)) {
      Console.Error.WriteLine("SEAL_DENIED:file");
      return false;
    }
    if (!StrictChild(rootPath, credentialPath)) {
      Console.Error.WriteLine("SEAL_DENIED:child");
      return false;
    }
    if (!SetFileSecurityW(rootPath,
          SecurityInformation | ProtectedDaclSecurityInformation, exact.Value)) {
      Console.Error.WriteLine("SEAL_DENIED:root-dacl:" +
        Marshal.GetLastWin32Error().ToString(System.Globalization.CultureInfo.InvariantCulture));
      return false;
    }
    if (!SetFileSecurityW(credentialPath,
          SecurityInformation | ProtectedDaclSecurityInformation, exact.Value)) {
      Console.Error.WriteLine("SEAL_DENIED:file-dacl:" +
        Marshal.GetLastWin32Error().ToString(System.Globalization.CultureInfo.InvariantCulture));
      return false;
    }
    if (!VerifyCredentialBoundary(rootPath, credentialPath)) {
      Console.Error.WriteLine("SEAL_DENIED:verify");
      return false;
    }
    return true;
  }

  internal bool VerifyCredentialBoundary(string rootPath, string credentialPath) =>
    StrictExistingRoot(rootPath) && StrictExistingFile(credentialPath) &&
    StrictChild(rootPath, credentialPath) &&
    NamedSecurityMatches(rootPath, "root") &&
    NamedSecurityMatches(credentialPath, "file");

  internal NamedPipeServerStream CreateFirstInstancePipe(string pipeName) {
    if (!ValidPipeName(pipeName)) throw new InvalidOperationException();
    SecurityAttributes attributes = Attributes(exact);
    SafePipeHandle handle = CreateNamedPipeW(
      @"\\.\pipe\" + pipeName,
      PipeAccessDuplex | WriteDac | FileFlagOverlapped | FileFlagFirstPipeInstance,
      PipeRejectRemoteClients, 1, 49152, 49152, 0, ref attributes);
    if (handle.IsInvalid) {
      handle.Dispose();
      throw new IOException("PIPE_POLICY_DENIED");
    }
    var stream = new NamedPipeServerStream(PipeDirection.InOut, true, false, handle);
    if (!KernelSecurityMatches(stream.SafePipeHandle)) {
      stream.Dispose();
      throw new IOException("PIPE_POLICY_DENIED");
    }
    return stream;
  }

  internal bool VerifyConnectedBeforeRead(
      NamedPipeServerStream pipe, string rootPath, string credentialPath,
      string expectedClientSha256, uint? expectedClientSession,
      out string clientDigest) {
    clientDigest = "";
    if (!ValidSha256(expectedClientSha256) ||
        !VerifyCredentialBoundary(rootPath, credentialPath) ||
        !KernelSecurityMatches(pipe.SafePipeHandle) ||
        !GetNamedPipeClientSessionId(pipe.SafePipeHandle, out uint clientSession) ||
        clientSession != (expectedClientSession ?? ServerSessionId) ||
        !VerifyConnectedProcess(pipe.SafePipeHandle, expectedClientSha256,
                                out clientDigest))
      return false;
    return true;
  }

  internal static bool VerifyConnectedProcess(
      SafePipeHandle pipe, string expectedClientSha256, out string clientDigest) {
    clientDigest = "";
    if (!ValidSha256(expectedClientSha256) ||
        !GetNamedPipeClientProcessId(pipe, out uint clientProcessId)) return false;
    string? digest = ProcessDigest(clientProcessId);
    if (!string.Equals(digest, expectedClientSha256,
                       StringComparison.OrdinalIgnoreCase)) return false;
    clientDigest = digest!;
    return true;
  }

  internal bool TamperFixture(string mode, string rootPath,
                              string credentialPath, SafePipeHandle pipe) {
    if (mode == "root-acl") return SetFileSecurityW(
      rootPath, DaclSecurityInformation | ProtectedDaclSecurityInformation, loose.Value);
    if (mode == "file-acl") return SetFileSecurityW(
      credentialPath, DaclSecurityInformation | ProtectedDaclSecurityInformation,
      loose.Value);
    if (mode == "pipe-acl") return SetKernelObjectSecurity(
      pipe, DaclSecurityInformation | ProtectedDaclSecurityInformation, loose.Value);
    return true;
  }

  internal static string SelfDigest() {
    string? path = Environment.ProcessPath;
    if (string.IsNullOrEmpty(path) || !Path.IsPathFullyQualified(path))
      throw new InvalidOperationException();
    using var executable = File.OpenRead(path);
    return Convert.ToHexString(SHA256.HashData(executable)).ToLowerInvariant();
  }

  internal static bool CleanupFixtureOwned(
      string root, string credential, bool rootCreated, bool fileCreated) {
    try {
      if (fileCreated) File.Delete(credential);
      if (rootCreated) Directory.Delete(root, false);
      return !File.Exists(credential) && !Directory.Exists(root);
    } catch { return false; }
  }

  private static string? ProcessDigest(uint processId) {
    try {
      using var process = Process.GetProcessById(checked((int)processId));
      string? path = process.MainModule?.FileName;
      if (string.IsNullOrEmpty(path) || !Path.IsPathFullyQualified(path)) return null;
      using var executable = File.OpenRead(path);
      return Convert.ToHexString(SHA256.HashData(executable)).ToLowerInvariant();
    } catch { return null; }
  }

  private SecurityAttributes Attributes(NativeDescriptor descriptor) => new() {
    Length = Marshal.SizeOf<SecurityAttributes>(),
    SecurityDescriptor = descriptor.Value,
    InheritHandle = false,
  };

  private static string ReadLogonSid(WindowsIdentity identity) {
    GetTokenInformation(identity.AccessToken, TokenLogonSid, IntPtr.Zero, 0,
                        out uint size);
    if (size == 0 || size > 65536) throw new InvalidOperationException();
    IntPtr information = Marshal.AllocHGlobal(checked((int)size));
    try {
      if (!GetTokenInformation(identity.AccessToken, TokenLogonSid, information,
                               size, out uint written) || written > size)
        throw new InvalidOperationException();
      if (Marshal.ReadInt32(information) != 1) throw new InvalidOperationException();
      IntPtr sidPointer = Marshal.ReadIntPtr(information, IntPtr.Size == 8 ? 8 : 4);
      if (sidPointer == IntPtr.Zero) throw new InvalidOperationException();
      string value = new SecurityIdentifier(sidPointer).Value;
      if (!value.StartsWith("S-1-5-5-", StringComparison.Ordinal))
        throw new InvalidOperationException();
      return value;
    } finally { Marshal.FreeHGlobal(information); }
  }

  private bool NamedSecurityMatches(string path, string label) {
    uint error = GetNamedSecurityInfoW(
      path, FileObject, SecurityInformation,
      out _, out _, out _, out _, out IntPtr descriptor);
    if (error != ErrorSuccess || descriptor == IntPtr.Zero) return false;
    try { return DescriptorMatches(descriptor, label); }
    catch { return false; }
    finally { LocalFree(descriptor); }
  }

  private bool KernelSecurityMatches(SafePipeHandle handle) {
    uint error = GetSecurityInfo(
      handle, KernelObject, SecurityInformation,
      out _, out _, out _, out _, out IntPtr descriptor);
    if (error != ErrorSuccess || descriptor == IntPtr.Zero) return false;
    try { return DescriptorMatches(descriptor, "pipe"); }
    catch { return false; }
    finally { LocalFree(descriptor); }
  }

  private bool DescriptorMatches(IntPtr descriptor, string label) {
    uint nativeLength = GetSecurityDescriptorLength(descriptor);
    if (nativeLength == 0 || nativeLength > 65536) return false;
    byte[] raw = new byte[checked((int)nativeLength)];
    Marshal.Copy(descriptor, raw, 0, raw.Length);
    var security = new RawSecurityDescriptor(raw, 0);
    if (!string.Equals(security.Owner?.Value, UserSid, StringComparison.Ordinal)) {
      Console.Error.WriteLine("POLICY_MISMATCH:" + label + ":owner");
      return false;
    }
    if ((security.ControlFlags & ControlFlags.DiscretionaryAclProtected) == 0) {
      Console.Error.WriteLine("POLICY_MISMATCH:" + label + ":unprotected-dacl");
      return false;
    }
    if (security.DiscretionaryAcl is null || security.DiscretionaryAcl.Count != 2) {
      Console.Error.WriteLine("POLICY_MISMATCH:" + label + ":ace-count:" +
        (security.DiscretionaryAcl?.Count ?? -1).ToString(
          System.Globalization.CultureInfo.InvariantCulture));
      return false;
    }
    var logon = new SecurityIdentifier(LogonSid);
    var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
    bool sawLogon = false;
    bool sawSystem = false;
    foreach (GenericAce ace in security.DiscretionaryAcl) {
      if (ace is not CommonAce common ||
          common.AceQualifier != AceQualifier.AccessAllowed ||
          common.AceFlags != AceFlags.None || common.AccessMask != FileAllAccess) {
        Console.Error.WriteLine("POLICY_MISMATCH:" + label + ":ace-contract");
        return false;
      }
      if (common.SecurityIdentifier.Equals(logon) && !sawLogon) sawLogon = true;
      else if (common.SecurityIdentifier.Equals(system) && !sawSystem) sawSystem = true;
      else {
        Console.Error.WriteLine("POLICY_MISMATCH:" + label + ":ace-principal");
        return false;
      }
    }
    return sawLogon && sawSystem;
  }

  private static bool StrictNewRoot(string path) {
    if (!Canonical(path)) return false;
    return GetFileAttributesW(path) == InvalidFileAttributes &&
           AncestorsAreNotReparsePoints(Path.GetDirectoryName(path)!);
  }

  private static bool StrictExistingRoot(string path) =>
    Canonical(path) && Directory.Exists(path) &&
    (GetFileAttributesW(path) & FileAttributeReparsePoint) == 0 &&
    AncestorsAreNotReparsePoints(path);

  private static bool StrictExistingFile(string path) =>
    Canonical(path) && File.Exists(path) &&
    (GetFileAttributesW(path) & FileAttributeReparsePoint) == 0 &&
    AncestorsAreNotReparsePoints(Path.GetDirectoryName(path)!);

  private static bool StrictChild(string root, string child) {
    try {
      string prefix = Path.GetFullPath(root) + Path.DirectorySeparatorChar;
      return Path.GetFullPath(child).StartsWith(prefix, StringComparison.OrdinalIgnoreCase) &&
             string.Equals(Path.GetDirectoryName(Path.GetFullPath(child)),
                           Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase);
    } catch { return false; }
  }

  private static bool Canonical(string path) {
    if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path)) return false;
    try { return string.Equals(Path.GetFullPath(path), path,
                               StringComparison.OrdinalIgnoreCase); }
    catch { return false; }
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

  internal static bool ValidPipeName(string value) =>
    !string.IsNullOrEmpty(value) && value.Length <= 128 &&
    value.All(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_');

  internal static bool ValidSha256(string value) =>
    value.Length == 64 && value.All(character =>
      (character is >= '0' and <= '9') ||
      (character is >= 'a' and <= 'f') ||
      (character is >= 'A' and <= 'F'));

  public void Dispose() {
    loose.Dispose();
    exact.Dispose();
    identity.Dispose();
  }
}
