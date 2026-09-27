// Pixel Forge launcher: a real .exe, so the app has its own icon (forge.ico
// is built into it) and it can be pinned to the taskbar - neither of which a
// .bat file can do. Rebuild with build-launcher.bat.
//
// - It can live anywhere (e.g. the Desktop): if the app files aren't next to
//   it, it uses the app folder recorded when it was built.
// - Normally it starts the app with .venv\Scripts\pythonw.exe: no console.
// - If the Python environment isn't set up yet, it runs start.bat instead,
//   in a console, so the one-time setup and its messages are visible.
// - An image dropped onto the .exe (or passed as an argument) is opened.
// - It tells the app its own path (PIXEL_FORGE_LAUNCHER), so pinning the
//   running window pins this .exe.
// - Other apps (Grass Block) call it with options (--edit, --describe; see
//   docs/INTEGRATION.md). Then it passes every argument on, WAITS for the app
//   to close and returns the app's exit code (0 saved, 10 cancelled, 1 error).

using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

static class PixelForgeLauncher
{
    [STAThread]
    static int Main(string[] args)
    {
        bool protocol = args.Any(a => a.StartsWith("--"));  // called by another app: wait, report
        bool quiet = protocol && Environment.GetEnvironmentVariable("PIXEL_FORGE_HIDDEN") == "1";
        string here = AppDomain.CurrentDomain.BaseDirectory;
        string dir = File.Exists(Path.Combine(here, "pixel_forge.py")) ? here : LauncherBuild.AppDir;
        if (!File.Exists(Path.Combine(dir, "pixel_forge.py")))
            return Fail(args, quiet, "Can't find the Pixel Forge app files.\n\nThis launcher expects them at:\n" + dir +
                                     "\n\nIf you moved the app folder, run build-launcher.bat in its new location.");

        string pythonw = Path.Combine(dir, ".venv", "Scripts", "pythonw.exe");
        string passed = string.Concat(args.Select(a => " " + Quote(a)));
        Environment.SetEnvironmentVariable("PIXEL_FORGE_LAUNCHER", Application.ExecutablePath);  // inherited by the app
        var start = new ProcessStartInfo { WorkingDirectory = dir, UseShellExecute = false };

        if (File.Exists(pythonw))
        {
            start.FileName = pythonw;
            start.Arguments = Quote(Path.Combine(dir, "pixel_forge.py")) + passed;
        }
        else if (protocol)
        {
            // The one-time setup needs a person watching; a calling app can't do it.
            return Fail(args, quiet, "Pixel Forge isn't set up yet.\n\nOpen Pixel Forge once by itself " +
                                     "(it installs what it needs), then try again.");
        }
        else
        {
            start.FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe";
            start.Arguments = "/c \"" + Quote(Path.Combine(dir, "start.bat")) + passed + "\"";
            start.UseShellExecute = true;  // its own visible console for the setup
        }

        try
        {
            Process app = Process.Start(start);
            if (!protocol)
                return 0;
            app.WaitForExit();
            return app.ExitCode;
        }
        catch (Exception e)
        {
            return Fail(args, quiet, "Couldn't start Pixel Forge:\n\n" + e.Message);
        }
    }

    // Report a failure: a message box for a person, and in protocol mode the
    // result file too (the same JSON the app writes), then exit code 1.
    static int Fail(string[] args, bool quiet, string message)
    {
        int i = Array.IndexOf(args, "--result");
        if (i >= 0 && i + 1 < args.Length)
        {
            try
            {
                string json = "{\n  \"protocol\": 1,\n  \"status\": \"error\",\n  \"message\": \"" + JsonEscape(message) + "\"\n}";
                File.WriteAllText(args[i + 1], json, new UTF8Encoding(false));
            }
            catch (Exception) { }
        }
        if (!quiet)
            MessageBox.Show(message, "Pixel Forge", MessageBoxButtons.OK, MessageBoxIcon.Error);
        return 1;
    }

    static string JsonEscape(string s)
    {
        var b = new StringBuilder();
        foreach (char c in s)
        {
            if (c == '"' || c == '\\') b.Append('\\').Append(c);
            else if (c == '\n') b.Append("\\n");
            else if (c < ' ') b.AppendFormat("\\u{0:x4}", (int)c);
            else b.Append(c);
        }
        return b.ToString();
    }

    // Quote one argument the way the C runtime (and Python) parse command
    // lines: backslashes only matter right before a quote.
    static string Quote(string arg)
    {
        if (arg.Length > 0 && arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            return arg;
        var b = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in arg)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') b.Append('\\', slashes * 2 + 1);
            else b.Append('\\', slashes);
            slashes = 0;
            b.Append(c);
        }
        b.Append('\\', slashes * 2).Append('"');
        return b.ToString();
    }
}
