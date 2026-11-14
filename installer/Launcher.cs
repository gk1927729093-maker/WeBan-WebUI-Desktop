// 安装版只管理自己的后台进程；账号、进度和日志始终保存在独立用户数据目录。
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("WeBan WebUI")]
[assembly: AssemblyDescription("WeBan WebUI 安装版启动和停止入口")]
[assembly: AssemblyCompany("WeBan WebUI")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

public sealed class ServerState
{
    public int Pid;
    public long StartedUtcTicks;
    public int Port;
    public string InstanceId;
    public string InstallDirectory;
}

internal static class Launcher
{
    static readonly string InstallDirectory = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar);
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static string DataDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WeBanWebUI", "Data");
    static string Action = "start";
    static int PreferredPort = 8088;
    static bool NoBrowser;
    static bool Quiet;
    static string StatePath { get { return Path.Combine(DataDirectory, "logs", "desktop-server.json"); } }
    static string PythonPath { get { return Path.Combine(InstallDirectory, "runtime", "python.exe"); } }

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            ParseArguments(args);
            if (Action == "stop" && !Directory.Exists(DataDirectory)) return 0;
            Directory.CreateDirectory(Path.Combine(DataDirectory, "logs"));
            string name;
            using (SHA256 hash = SHA256.Create())
                name = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(DataDirectory.ToLowerInvariant()))).Replace("-", "");
            using (Mutex mutex = new Mutex(false, "Local\\WeBanWebUI_" + name))
            {
                bool locked;
                try { locked = mutex.WaitOne(30000); }
                catch (AbandonedMutexException) { locked = true; }
                if (!locked) throw new InvalidOperationException("另一个启动或停止操作仍在执行，请稍后重试。");
                try
                {
                    if (Action == "stop") Stop();
                    else if (Action == "data") Open(DataDirectory);
                    else Start();
                }
                finally { mutex.ReleaseMutex(); }
            }
            return 0;
        }
        catch (Exception error)
        {
            try
            {
                Directory.CreateDirectory(Path.Combine(DataDirectory, "logs"));
                File.AppendAllText(Path.Combine(DataDirectory, "logs", "launcher.log"),
                    DateTime.Now.ToString("s") + " " + error + Environment.NewLine, Encoding.UTF8);
            }
            catch { }
            if (!Quiet) MessageBox.Show(error.Message + "\n\n日志目录：" + Path.Combine(DataDirectory, "logs"),
                "WeBan WebUI", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static void ParseArguments(string[] args)
    {
        for (int index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--stop": Action = "stop"; break;
                case "--open-data": Action = "data"; break;
                case "--no-browser": NoBrowser = true; break;
                case "--quiet": Quiet = true; break;
                case "--data-dir": DataDirectory = Path.GetFullPath(args[++index]); break;
                case "--port": PreferredPort = int.Parse(args[++index]); break;
                default: throw new ArgumentException("无法识别的启动参数：" + args[index]);
            }
        }
        if (PreferredPort < 1024 || PreferredPort > 65525) throw new ArgumentException("端口必须在 1024 到 65525 之间。");
        DataDirectory = Path.GetFullPath(DataDirectory).TrimEnd(Path.DirectorySeparatorChar);
    }

    // 按 Windows 命令行规则转义，路径包含空格、中文或末尾反斜杠时也能正确传递。
    static string Quote(string text)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in text)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"') result.Append('\\', slashes * 2 + 1).Append('"');
            else result.Append('\\', slashes).Append(character);
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }

    static ServerState ReadState()
    {
        try { return Json.Deserialize<ServerState>(File.ReadAllText(StatePath, Encoding.UTF8)); }
        catch { return null; }
    }

    static Process OwnedProcess(ServerState state)
    {
        if (state == null || state.Pid <= 0 || state.Port < 1024 || state.Port > 65535 ||
            !String.Equals(state.InstallDirectory, InstallDirectory, StringComparison.OrdinalIgnoreCase)) return null;
        Process process = null;
        try
        {
            process = Process.GetProcessById(state.Pid);
            if (!process.HasExited && process.StartTime.ToUniversalTime().Ticks == state.StartedUtcTicks &&
                String.Equals(Path.GetFullPath(process.MainModule.FileName), PythonPath, StringComparison.OrdinalIgnoreCase)) return process;
        }
        catch { }
        if (process != null) process.Dispose();
        return null;
    }

    static string Request(ServerState state, string path, string method, int timeout)
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + state.Port + path);
        request.Proxy = null;
        request.Method = method;
        request.Timeout = timeout;
        request.ReadWriteTimeout = timeout;
        if (method == "POST") request.ContentLength = 0;
        using (WebResponse response = request.GetResponse())
        using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            return reader.ReadToEnd();
    }

    static bool Ready(ServerState state)
    {
        try
        {
            var identity = Json.Deserialize<System.Collections.Generic.Dictionary<string, object>>(
                Request(state, "/api/desktop/identity", "GET", 1000));
            return (string)identity["application"] == "WeBanWebUI" && (string)identity["instance_id"] == state.InstanceId;
        }
        catch { return false; }
    }

    static void Start()
    {
        if (!File.Exists(PythonPath)) throw new FileNotFoundException("未找到内置 Python，请通过安装程序修复或重新安装。");
        ServerState previous = ReadState();
        using (Process existing = OwnedProcess(previous))
        {
            if (existing != null)
            {
                if (!Ready(previous)) throw new InvalidOperationException("后台进程仍在启动或暂时未响应，请稍后重试，或使用开始菜单中的停止入口。");
                if (!NoBrowser) Open("http://127.0.0.1:" + previous.Port + "/");
                return;
            }
        }

        string defaults = Path.Combine(InstallDirectory, "defaults");
        Seed(Path.Combine(defaults, "config.toml"), Path.Combine(DataDirectory, "config.toml"));
        Directory.CreateDirectory(Path.Combine(DataDirectory, "answer"));
        Seed(Path.Combine(defaults, "answer.json"), Path.Combine(DataDirectory, "answer", "answer.json"));
        int port = FindFreePort();
        ServerState state = new ServerState { Port = port, InstanceId = Guid.NewGuid().ToString("N"), InstallDirectory = InstallDirectory };
        ProcessStartInfo start = new ProcessStartInfo(PythonPath,
            "-B -u " + Quote(Path.Combine(InstallDirectory, "app", "desktop_server.py")));
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WorkingDirectory = Path.Combine(InstallDirectory, "app");
        start.EnvironmentVariables["WB_DATA_DIR"] = DataDirectory;
        start.EnvironmentVariables["WEBUI_HOST"] = "127.0.0.1";
        start.EnvironmentVariables["WEBUI_PORT"] = port.ToString();
        start.EnvironmentVariables["WB_DESKTOP_INSTANCE"] = state.InstanceId;
        using (Process server = Process.Start(start))
        {
            state.Pid = server.Id;
            state.StartedUtcTicks = server.StartTime.ToUniversalTime().Ticks;
            File.WriteAllText(StatePath, Json.Serialize(state), Encoding.UTF8);
            for (int attempt = 0; attempt < 60; attempt++)
            {
                if (server.HasExited) throw new InvalidOperationException("后台启动失败，请查看 webui.stderr.log。");
                if (Ready(state))
                {
                    if (!NoBrowser) Open("http://127.0.0.1:" + port + "/");
                    return;
                }
                Thread.Sleep(250);
            }
            throw new TimeoutException("后台启动超时，请查看日志或使用停止入口后重试。");
        }
    }

    static void Seed(string source, string destination)
    {
        if (!File.Exists(destination)) File.Copy(source, destination, false);
    }

    static int FindFreePort()
    {
        for (int port = PreferredPort; port < PreferredPort + 10; port++)
        {
            TcpListener listener = new TcpListener(IPAddress.Loopback, port);
            try { listener.Start(); return port; }
            catch (SocketException) { }
            finally { listener.Stop(); }
        }
        throw new InvalidOperationException("本机端口暂时不可用，请关闭冲突的程序后重试。");
    }

    static void Stop()
    {
        ServerState state = ReadState();
        using (Process owned = OwnedProcess(state))
        {
            if (owned == null) return;
            if (Ready(state))
            {
                try { Request(state, "/api/task/stop", "POST", 12000); }
                catch { }
            }
        }
        // 再次核验创建时间和完整路径，防止 PID 被其他程序复用。
        using (Process owned = OwnedProcess(state))
        {
            if (owned == null) return;
            ProcessStartInfo stop = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "taskkill.exe"),
                "/PID " + state.Pid + " /T /F");
            stop.UseShellExecute = false;
            stop.CreateNoWindow = true;
            using (Process killer = Process.Start(stop))
            {
                if (!killer.WaitForExit(15000)) throw new TimeoutException("停止后台进程超时。");
            }
            if (!owned.WaitForExit(5000)) throw new TimeoutException("后台进程尚未退出。");
        }
        if (File.Exists(StatePath)) File.Delete(StatePath);
    }

    static void Open(string target)
    {
        Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
    }
}
