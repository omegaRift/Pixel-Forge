@echo off
rem ------------------------------------------------------------------
rem  Rebuilds "Pixel Forge.exe" from launcher.cs with forge.ico as its
rem  icon, using the C# compiler that ships with Windows (.NET 4).
rem  The app folder's location is built in, so the .exe keeps working
rem  after you move it (e.g. to the Desktop). Run this again after
rem  moving the app folder or changing forge.ico / launcher.cs.
rem ------------------------------------------------------------------
cd /d "%~dp0"
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
    echo [Pixel Forge] The .NET 4 C# compiler wasn't found on this PC.
    pause
    exit /b 1
)
rem Record where the app lives (a C# verbatim string, so backslashes are fine).
echo static class LauncherBuild { public const string AppDir = @"%~dp0"; } > launcher_path.cs
"%CSC%" /nologo /target:winexe /win32icon:forge.ico /reference:System.Windows.Forms.dll /out:"Pixel Forge.exe" launcher.cs launcher_path.cs
if errorlevel 1 (
    echo [Pixel Forge] Building the launcher failed - see the error above.
    pause
    exit /b 1
)
echo [Pixel Forge] Built "Pixel Forge.exe" for the app in %~dp0
