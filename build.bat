@echo off
rem Builds dist\DesktopStatWidget.exe (one file, no console window).
rem Needs: pip install -r requirements.txt pyinstaller
cd /d "%~dp0"
python tools\make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name DesktopStatWidget --icon assets\icon.ico ^
  --exclude-module tkinter --exclude-module unittest ^
  app.py
echo.
echo Built: %~dp0dist\DesktopStatWidget.exe
