@echo off
REM ============================================================
REM Trading Copier - one-shot Windows build script
REM Requirements: Python 3.11 x64 in PATH, Inno Setup 6 installed
REM Output: dist\TradingCopierSetup_x64.exe + zipped bundle
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/5] installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt || goto :err

echo [2/5] running unit tests (no MT5 needed)...
python -m pytest tests -q || goto :err

echo [3/5] building executable (PyInstaller)...
pyinstaller build\pyinstaller\TradingCopier.spec --distpath dist --workpath build\pyi --clean -y || goto :err

echo [4/5] building installer (Inno Setup)...
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
%ISCC% build\inno\TradingCopierSetup.iss || goto :err

echo [5/5] zipping installer...
powershell -NoProfile -Command "Compress-Archive -Path 'Output\TradingCopierSetup_x64.exe' -DestinationPath 'Output\TradingCopierSetup_x64.zip' -Force"

echo.
echo DONE:
echo   Output\TradingCopierSetup_x64.exe
echo   Output\TradingCopierSetup_x64.zip
goto :eof

:err
echo BUILD FAILED with errorlevel %errorlevel%
exit /b %errorlevel%
