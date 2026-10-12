using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

public class RelayNativeHostV2
{
    const string PipePrefix = "ai_workspace_relay_";
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static readonly Stream Input = Console.OpenStandardInput();
    static readonly Stream Output = Console.OpenStandardOutput();
    static readonly object OutputLock = new object();
    static readonly object PipeStartLock = new object();
    static readonly ConcurrentDictionary<string, StreamWriter> Clients =
        new ConcurrentDictionary<string, StreamWriter>();
    static readonly ConcurrentDictionary<string, Dictionary<string, object>> Endpoints =
        new ConcurrentDictionary<string, Dictionary<string, object>>();
    static readonly object PresenceLock = new object();
    static readonly object ActPresencePushLock = new object();
    static int PresencePushWorkerRunning = 0;
    static int PresencePushDirty = 0;
    static DateTime LastActPresencePushOkUtc = DateTime.MinValue;
    static string LastActPresencePushError = "";
    static object LastPresenceObservedAt = null;
    static string LastPresenceSessionId = "";
    static string InstanceId = "";
    static bool PipeStarted = false;
    static bool ActOriginAllowed = false;

    public static void Main(string[] args)
    {
        ActOriginAllowed = args.Length > 0 && args[0] == "chrome-extension://bhlcnmbodlhbephppahojbigleklpmhj/";
        try { NativeReadLoop(); }
        catch (Exception ex) { Console.Error.WriteLine("native loop: " + ex.Message); }
    }

    static void StartPipe(string instanceId)
    {
        lock (PipeStartLock)
        {
            if (PipeStarted) return;
            InstanceId = ValidateInstanceId(instanceId);
            PipeStarted = true;
            var thread = new Thread(PipeAcceptLoop) { IsBackground = true };
            thread.Start();
        }
    }
    static void PipeAcceptLoop()
    {
        var pipeName = PipePrefix + InstanceId;
        while (true)
        {
            var pipe = new NamedPipeServerStream(
                pipeName, PipeDirection.InOut, 8,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            pipe.WaitForConnection();
            ThreadPool.QueueUserWorkItem(_ => HandlePipeClient(pipe));
        }
    }

    static void HandlePipeClient(NamedPipeServerStream pipe)
    {
        StreamWriter writer = null;
        try
        {
            var utf8 = new UTF8Encoding(false);
            var reader = new StreamReader(pipe, utf8, false, 4096, true);
            writer = new StreamWriter(pipe, utf8, 4096, true) { AutoFlush = true };
            string line;
            while ((line = reader.ReadLine()) != null)
            {
                var msg = Json.Deserialize<Dictionary<string, object>>(line);
                var requestId = GetString(msg, "requestId");
                if (String.IsNullOrWhiteSpace(requestId))
                    requestId = Guid.NewGuid().ToString("N");
                if (String.Equals(GetString(msg, "command"), "presence", StringComparison.OrdinalIgnoreCase))
                {
                    lock (writer) writer.WriteLine(Json.Serialize(BuildPresenceResult(requestId)));
                    continue;
                }
                Clients[requestId] = writer;
                msg["type"] = "host:command";
                msg["requestId"] = requestId;
                msg["instanceId"] = InstanceId;
                SendNative(msg);
            }
        }
        catch (Exception ex) { Console.Error.WriteLine("pipe client: " + ex.Message); }
        finally
        {
            if (writer != null)
                foreach (var pair in Clients)
                    if (Object.ReferenceEquals(pair.Value, writer))
                    { StreamWriter removed; Clients.TryRemove(pair.Key, out removed); }
            try { pipe.Dispose(); } catch { }
        }
    }
    static void NativeReadLoop()
    {
        var header = new byte[4];
        while (ReadExact(Input, header, 0, 4))
        {
            int length = BitConverter.ToInt32(header, 0);
            if (length <= 0 || length > 1024 * 1024)
                throw new InvalidDataException("Invalid native message length");
            var payload = new byte[length];
            if (!ReadExact(Input, payload, 0, length)) break;
            var text = Encoding.UTF8.GetString(payload);
            var msg = Json.Deserialize<Dictionary<string, object>>(text);
            var type = GetString(msg, "type");
            if (type == "host:ready")
            {
                var instanceId = GetString(msg, "instanceId");
                Endpoints.Clear();
                lock (PresenceLock) {
                    LastPresenceObservedAt = null;
                    LastPresenceSessionId = "";
                }
                StartPipe(instanceId);
                SendNative(new Dictionary<string, object> {
                    { "type", "host:ready-ack" },
                    { "instanceId", InstanceId },
                    { "pipeName", PipePrefix + InstanceId }
                });
                continue;
            }
            if (type == "host:endpoints")
            {
                CacheEndpointMessage(msg);
                QueueEndpointSnapshotPush();
                continue;
            }
            if (type == "host:act")
            {
                HandleActRequest(msg);
                continue;
            }

            var requestId = GetString(msg, "requestId");
            StreamWriter writer;
            if (!String.IsNullOrWhiteSpace(requestId) &&
                Clients.TryGetValue(requestId, out writer))
            {
                try { lock (writer) writer.WriteLine(Json.Serialize(msg)); }
                catch (Exception ex) { Console.Error.WriteLine("pipe result dropped: " + ex.GetType().Name); }
                finally
                {
                    if (type == "host:result")
                    { StreamWriter removed; Clients.TryRemove(requestId, out removed); }
                }
            }
        }
    }

    static void HandleActRequest(Dictionary<string, object> msg)
    {
        string requestId = GetString(msg, "requestId");
        try
        {
            if (!ActOriginAllowed || !PipeStarted) throw new InvalidDataException("ACT_NATIVE_ORIGIN_REQUIRED");
            var caller = msg["caller"] as Dictionary<string, object>;
            if (caller == null) throw new InvalidDataException("ACT_CALLER_REQUIRED");
            Dictionary<string, object> endpoint;
            string tabId = GetString(caller, "tab_id");
            string key = GetString(caller, "conversation_key");
            if (GetString(caller, "transport_instance_id") != InstanceId ||
                GetString(caller, "session_id") != LastPresenceSessionId ||
                !Endpoints.TryGetValue(tabId, out endpoint) ||
                key == "" || GetString(endpoint, "conversationKey") != key)
                throw new InvalidDataException("ACT_NATIVE_ENDPOINT_MISMATCH");
            var op = GetString(msg, "op");
            string path;
            Dictionary<string, object> body;
            if (op == "bootstrap")
            {
                path = "/bootstrap/resync";
                body = new Dictionary<string, object> {
                    { "conversation_key", key }, { "transport_instance_id", InstanceId },
                    { "session_id", LastPresenceSessionId }, { "tab_id", caller["tab_id"] }
                };
            }
            else if (op == "command")
            {
                path = "/bootstrap/command";
                var directive = msg["directive"] as Dictionary<string, object>;
                string text = directive == null ? "" : GetString(directive, "text");
                if (String.IsNullOrWhiteSpace(text) || text.Length > 500)
                    throw new InvalidDataException("ACT_COMMAND_INVALID");
                string windowInstanceId = GetString(caller, "window_instance_id");
                if (String.IsNullOrWhiteSpace(windowInstanceId))
                    throw new InvalidDataException("ACT_WINDOW_IDENTITY_REQUIRED");
                body = new Dictionary<string, object> {
                    { "text", text }, { "conversation_key", key },
                    { "transport_instance_id", InstanceId }, { "session_id", LastPresenceSessionId },
                    { "tab_id", caller["tab_id"] }, { "window_instance_id", windowInstanceId }
                };
            }
            else if (op == "submit" || op == "status" || op == "result")
            {
                path = "/direct/tasks";
                body = msg["directive"] as Dictionary<string, object>;
                if (body == null || body.ContainsKey("caller") || GetString(body, "op") != op)
                    throw new InvalidDataException("ACT_DIRECTIVE_INVALID");
                body = new Dictionary<string, object>(body);
                body["caller"] = caller;
            }
            else if (op == "local-exec")
            {
                path = "/direct/local-execution";
                body = msg["directive"] as Dictionary<string, object>;
                if (body == null || body.ContainsKey("caller"))
                    throw new InvalidDataException("ACT_DIRECTIVE_INVALID");
                body = new Dictionary<string, object>(body);
                body["caller"] = caller;
            }
            else if (op == "worker-status" || op == "worker-claim" || op == "worker-start" ||
                     op == "worker-result" || op == "worker-complete" || op == "worker-return-status")
            {
                var directive = msg["directive"] as Dictionary<string, object>;
                if (directive == null || directive.ContainsKey("caller") || directive.ContainsKey("op"))
                    throw new InvalidDataException("ACT_WORKER_DIRECTIVE_INVALID");
                string gatewayOp;
                if (op == "worker-status") gatewayOp = "act_get_wake_task";
                else if (op == "worker-claim") gatewayOp = "act_claim_wake_task";
                else if (op == "worker-start") gatewayOp = "act_start_wake_task";
                else if (op == "worker-result") gatewayOp = "act_submit_wake_result";
                else if (op == "worker-complete") gatewayOp = "act_complete_wake_task";
                else gatewayOp = "act_get_wake_result";
                path = "/direct/gateway";
                body = new Dictionary<string, object> {
                    { "op", gatewayOp }, { "caller", caller },
                    { "arguments", new Dictionary<string, object>(directive) }
                };
            }
            else
            {
                throw new InvalidDataException("ACT_OPERATION_DENIED");
            }
            var bytes = Encoding.UTF8.GetBytes(Json.Serialize(body));
            if (bytes.Length > 65536) throw new InvalidDataException("ACT_REQUEST_TOO_LARGE");
            string keyPath = Environment.GetEnvironmentVariable("ACT_BROWSER_BRIDGE_KEY_FILE");
            if (String.IsNullOrEmpty(keyPath))
                keyPath = Environment.GetEnvironmentVariable("ACT_BROWSER_BRIDGE_KEY_FILE", EnvironmentVariableTarget.User);
            if (String.IsNullOrEmpty(keyPath)) throw new InvalidDataException("NATIVE_BRIDGE_UNAVAILABLE");
            var secret = File.ReadAllBytes(keyPath);
            if (secret.Length != 32) throw new InvalidDataException("NATIVE_BRIDGE_UNAVAILABLE");
            string stamp = ((long)(DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds).ToString(System.Globalization.CultureInfo.InvariantCulture);
            string nonce = Guid.NewGuid().ToString("N");
            var prefix = Encoding.UTF8.GetBytes("POST\n" + path + "\n" + stamp + "\n" + nonce + "\n");
            var signed = new byte[prefix.Length + bytes.Length];
            Buffer.BlockCopy(prefix, 0, signed, 0, prefix.Length);
            Buffer.BlockCopy(bytes, 0, signed, prefix.Length, bytes.Length);
            string signature;
            using (var hmac = new HMACSHA256(secret))
                signature = BitConverter.ToString(hmac.ComputeHash(signed)).Replace("-", "").ToLowerInvariant();
            Array.Clear(secret, 0, secret.Length);
            string baseUrl = ResolveActBaseUrl();
            var http = (HttpWebRequest)WebRequest.Create(baseUrl.TrimEnd('/') + path);
            http.Proxy = null;
            http.AllowAutoRedirect = false;
            http.Timeout = 5000;
            http.ReadWriteTimeout = 5000;
            http.Method = "POST";
            http.ContentType = "application/json";
            http.Headers["X-ACT-Time"] = stamp;
            http.Headers["X-ACT-Nonce"] = nonce;
            http.Headers["X-ACT-Signature"] = signature;
            http.ContentLength = bytes.Length;
            using (var stream = http.GetRequestStream()) stream.Write(bytes, 0, bytes.Length);
            WebResponse response;
            try { response = http.GetResponse(); }
            catch (WebException ex) { if (ex.Response == null) throw; response = ex.Response; }
            using (response)
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            {
                var buffer = new char[1048577];
                int length = reader.ReadBlock(buffer, 0, buffer.Length);
                if (length > 1048576) throw new InvalidDataException("ACT_RESPONSE_TOO_LARGE");
                var result = Json.Deserialize<Dictionary<string, object>>(new string(buffer, 0, length));
                SendNative(new Dictionary<string, object> { { "type", "host:act-result" },
                    { "requestId", requestId }, { "response", result } });
            }
        }
        catch (Exception ex)
        {
            // No file paths, key material, headers or response bodies in error telemetry.
            string error = ex is InvalidDataException ? ex.Message : "ACT_NATIVE_REQUEST_UNAVAILABLE";
            SendNative(new Dictionary<string, object> { { "type", "host:act-result" },
                { "requestId", requestId }, { "response", new Dictionary<string, object> {
                    { "ok", false }, { "error", error } } } });
        }
    }

    static void CacheEndpointMessage(Dictionary<string, object> msg)
    {
        var instanceId = GetString(msg, "instanceId");
        if (!String.IsNullOrWhiteSpace(InstanceId) && instanceId != InstanceId) return;
        var mode = GetString(msg, "mode");
        if (String.Equals(mode, "snapshot", StringComparison.OrdinalIgnoreCase)) Endpoints.Clear();
        object rawEndpoints;
        if (msg.TryGetValue("endpoints", out rawEndpoints) && rawEndpoints is IEnumerable)
        {
            foreach (var raw in (IEnumerable)rawEndpoints)
            {
                var endpoint = raw as Dictionary<string, object>;
                if (endpoint == null) continue;
                var tabId = GetString(endpoint, "tabId");
                if (String.IsNullOrWhiteSpace(tabId)) continue;
                var presence = GetString(endpoint, "presence");
                if (String.Equals(presence, "OFFLINE", StringComparison.OrdinalIgnoreCase))
                {
                    Dictionary<string, object> removed;
                    Endpoints.TryRemove(tabId, out removed);
                }
                else
                {
                    Endpoints[tabId] = new Dictionary<string, object>(endpoint);
                }
            }
        }
        object observedAt;
        if (msg.TryGetValue("observedAt", out observedAt))
            lock (PresenceLock) {
                LastPresenceObservedAt = observedAt;
                LastPresenceSessionId = GetString(msg, "sessionId");
            }
    }

    static Dictionary<string, object> BuildPresenceSnapshot()
    {
        object observedAt;
        string sessionId;
        lock (PresenceLock) {
            observedAt = LastPresenceObservedAt;
            sessionId = LastPresenceSessionId;
        }
        var endpoints = new List<object>();
        foreach (var endpoint in Endpoints.Values)
            endpoints.Add(new Dictionary<string, object>(endpoint));
        return new Dictionary<string, object> {
            { "instanceId", InstanceId },
            { "sessionId", sessionId },
            { "observedAt", observedAt },
            { "endpoints", endpoints }
        };
    }

    static void QueueEndpointSnapshotPush()
    {
        if (!ActOriginAllowed || !PipeStarted) return;
        Interlocked.Exchange(ref PresencePushDirty, 1);
        if (Interlocked.CompareExchange(ref PresencePushWorkerRunning, 1, 0) != 0) return;
        ThreadPool.QueueUserWorkItem(_ => PresencePushWorker());
    }

    static void PresencePushWorker()
    {
        int[] delays = new[] { 0, 500, 1000, 2000, 5000, 10000, 30000 };
        Interlocked.Exchange(ref PresencePushDirty, 0);
        try
        {
            for (int i = 0; i < delays.Length; i++)
            {
                if (delays[i] > 0) Thread.Sleep(delays[i]);
                if (TryPushEndpointSnapshotToAct()) return;
            }
        }
        finally
        {
            Interlocked.Exchange(ref PresencePushWorkerRunning, 0);
            if (Interlocked.Exchange(ref PresencePushDirty, 0) != 0)
                QueueEndpointSnapshotPush();
        }
    }

    static bool TryPushEndpointSnapshotToAct()
    {
        if (!ActOriginAllowed || !PipeStarted) return false;
        lock (ActPresencePushLock)
        {
            try
            {
                string path = "/browser/endpoints";
                var bytes = Encoding.UTF8.GetBytes(Json.Serialize(BuildPresenceSnapshot()));
                string keyPath = Environment.GetEnvironmentVariable("ACT_BROWSER_BRIDGE_KEY_FILE");
                if (String.IsNullOrEmpty(keyPath)) keyPath = Environment.GetEnvironmentVariable("ACT_BROWSER_BRIDGE_KEY_FILE", EnvironmentVariableTarget.User);
                if (String.IsNullOrEmpty(keyPath)) throw new InvalidDataException("ACT_BROWSER_BRIDGE_KEY_FILE_REQUIRED");
                var secret = File.ReadAllBytes(keyPath);
                if (secret.Length != 32) throw new InvalidDataException("ACT_BROWSER_BRIDGE_KEY_INVALID");
                string stamp = ((long)(DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds).ToString(System.Globalization.CultureInfo.InvariantCulture);
                string nonce = Guid.NewGuid().ToString("N");
                var prefix = Encoding.UTF8.GetBytes("POST\n" + path + "\n" + stamp + "\n" + nonce + "\n");
                var signed = new byte[prefix.Length + bytes.Length];
                Buffer.BlockCopy(prefix, 0, signed, 0, prefix.Length);
                Buffer.BlockCopy(bytes, 0, signed, prefix.Length, bytes.Length);
                string signature;
                using (var hmac = new HMACSHA256(secret)) signature = BitConverter.ToString(hmac.ComputeHash(signed)).Replace("-", "").ToLowerInvariant();
                Array.Clear(secret, 0, secret.Length);
                string baseUrl = ResolveActBaseUrl();
                var http = (HttpWebRequest)WebRequest.Create(baseUrl.TrimEnd('/') + path);
                http.Proxy = null; http.AllowAutoRedirect = false; http.Timeout = 5000; http.ReadWriteTimeout = 5000;
                http.Method = "POST"; http.ContentType = "application/json";
                http.Headers["X-ACT-Time"] = stamp; http.Headers["X-ACT-Nonce"] = nonce; http.Headers["X-ACT-Signature"] = signature;
                http.ContentLength = bytes.Length;
                using (var stream = http.GetRequestStream()) stream.Write(bytes, 0, bytes.Length);
                using (var response = (HttpWebResponse)http.GetResponse())
                { int code = (int)response.StatusCode; if (code < 200 || code >= 300) throw new WebException("ACT_PRESENCE_HTTP_" + code); }
                LastActPresencePushOkUtc = DateTime.UtcNow; LastActPresencePushError = "";
                return true;
            }
            catch (Exception ex)
            {
                LastActPresencePushError = ex.GetType().Name + ":" + ex.Message;
                Console.Error.WriteLine("presence push unavailable: " + LastActPresencePushError);
                return false;
            }
        }
    }

    static string ResolveActBaseUrl()
    {
        string explicitUrl = Environment.GetEnvironmentVariable("ACT_GATEWAY_URL");
        if (String.IsNullOrWhiteSpace(explicitUrl)) explicitUrl = Environment.GetEnvironmentVariable("ACT_GATEWAY_URL", EnvironmentVariableTarget.User);
        if (!String.IsNullOrWhiteSpace(explicitUrl)) return explicitUrl.TrimEnd('/');
        string runtimeDir = Environment.GetEnvironmentVariable("ACT_RUNTIME_DIR");
        if (String.IsNullOrWhiteSpace(runtimeDir)) runtimeDir = Environment.GetEnvironmentVariable("ACT_RUNTIME_DIR", EnvironmentVariableTarget.User);
        if (String.IsNullOrWhiteSpace(runtimeDir)) runtimeDir = @"D:\ACT\runtime";
        string endpointFile = Path.Combine(runtimeDir, "act-live-endpoint.json");
        try { if (File.Exists(endpointFile)) { var row = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(endpointFile, Encoding.UTF8)); string u=GetString(row,"base_url"); if(!String.IsNullOrWhiteSpace(u)) return u.TrimEnd('/'); string h=GetString(row,"host"), port=GetString(row,"port"); if(!String.IsNullOrWhiteSpace(h)&&!String.IsNullOrWhiteSpace(port)) return "http://"+h+":"+port; } } catch(Exception ex) { Console.Error.WriteLine("act endpoint file invalid: "+ex.GetType().Name); }
        string registryFile = Path.Combine(runtimeDir, "service-registry.json");
        try { if(File.Exists(registryFile)) { var r=Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(registryFile,Encoding.UTF8)); object raw; if(r.TryGetValue("preferred_ports",out raw)) { var ports=raw as Dictionary<string, object>; string port=ports==null?"":GetString(ports,"act"); if(!String.IsNullOrWhiteSpace(port)) { string c="http://127.0.0.1:"+port; if(ActHealthReachable(c)) return c; } } } } catch(Exception ex) { Console.Error.WriteLine("act service registry invalid: "+ex.GetType().Name); }
        throw new InvalidDataException("ACT_ENDPOINT_UNRESOLVED");
    }

    static bool ActHealthReachable(string baseUrl)
    {
        try { var req=(HttpWebRequest)WebRequest.Create(baseUrl.TrimEnd('/')+"/health"); req.Proxy=null; req.AllowAutoRedirect=false; req.Timeout=750; req.ReadWriteTimeout=750; req.Method="GET"; using(var response=(HttpWebResponse)req.GetResponse()) return (int)response.StatusCode>=200 && (int)response.StatusCode<300; }
        catch { return false; }
    }

    static Dictionary<string, object> BuildPresenceResult(string requestId)
    {
        object observedAt;
        string sessionId;
        lock (PresenceLock) {
            observedAt = LastPresenceObservedAt;
            sessionId = LastPresenceSessionId;
        }
        var endpoints = new List<object>();
        foreach (var endpoint in Endpoints.Values)
            endpoints.Add(new Dictionary<string, object>(endpoint));
        return new Dictionary<string, object> {
            { "type", "host:result" },
            { "requestId", requestId },
            { "ok", true },
            { "presence", new Dictionary<string, object> {
                { "instanceId", InstanceId },
                { "sessionId", sessionId },
                { "observedAt", observedAt },
                { "endpoints", endpoints }
            } }
        };
    }

    static bool ReadExact(Stream stream, byte[] buffer, int offset, int count)
    {
        int read = 0;
        while (read < count)
        {
            int n = stream.Read(buffer, offset + read, count - read);
            if (n <= 0) return false;
            read += n;
        }
        return true;
    }

    static void SendNative(Dictionary<string, object> msg)
    {
        var payload = Encoding.UTF8.GetBytes(Json.Serialize(msg));
        var header = BitConverter.GetBytes(payload.Length);
        lock (OutputLock)
        {
            Output.Write(header, 0, header.Length);
            Output.Write(payload, 0, payload.Length);
            Output.Flush();
        }
    }

    static string ValidateInstanceId(string value)
    {
        value = (value ?? "").Trim();
        if (value.Length < 8 || value.Length > 64)
            throw new InvalidDataException("Invalid instanceId length");
        foreach (char ch in value)
        {
            if (!(Char.IsLetterOrDigit(ch) || ch == '_' || ch == '-'))
                throw new InvalidDataException("Invalid instanceId characters");
        }
        return value;
    }

    static string GetString(Dictionary<string, object> msg, string key)
    {
        object value;
        if (!msg.TryGetValue(key, out value) || value == null) return "";
        return Convert.ToString(value);
    }
}
