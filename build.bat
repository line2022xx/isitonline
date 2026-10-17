@echo off
REM 打包为单文件 exe（无需控制台窗口）
chcp 65001 >nul
echo [1/2] 安装 PyInstaller...
pip install pyinstaller || goto :error
echo [2/2] 打包...
pyinstaller --onefile --windowed --name IsItOnline main.py || goto :error
echo.
echo 打包完成：dist\IsItOnline.exe
pause
exit /b 0

:error
echo 打包失败，请检查上方错误信息。
pause
exit /b 1
