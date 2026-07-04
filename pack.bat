@echo off
chcp 65001 >nul
setlocal

set "PROJECT_DIR=%~dp0"
set "OUTPUT=%PROJECT_DIR%log_analyzer.zip"

echo.
echo ============================================
echo   Log Analyzer - 项目打包
echo ============================================
echo.
echo 源目录: %PROJECT_DIR%
echo 输出  : %OUTPUT%
echo 排除  : node_modules, __pycache__, .git, data
echo.

REM 删除旧压缩包
if exist "%OUTPUT%" del /f /q "%OUTPUT%"

echo 正在打包...

powershell -NoProfile -Command ^
    "$src = '%PROJECT_DIR:\=\\%'.TrimEnd('\\'); " ^
    "$dst = '%OUTPUT:\=\\%'; " ^
    "$files = Get-ChildItem -Path $src -Recurse -File ^| Where-Object { " ^
    "    $_.DirectoryName -notmatch '\\\\node_modules\\\\' -and " ^
    "    $_.DirectoryName -notmatch '\\\\node_modules$' -and " ^
    "    $_.DirectoryName -notmatch '\\\\__pycache__\\\\' -and " ^
    "    $_.DirectoryName -notmatch '\\\\__pycache__$' -and " ^
    "    $_.DirectoryName -notmatch '\\\\.git\\\\' -and " ^
    "    $_.DirectoryName -notmatch '\\\\.git$' -and " ^
    "    $_.DirectoryName -notmatch '\\\\data\\\\' -and " ^
    "    $_.DirectoryName -notmatch '\\\\data$' -and " ^
    "    $_.Name -notmatch '\\.pyc$' -and " ^
    "    $_.Name -notmatch '\\.env$' -and " ^
    "    $_.Name -notmatch '\\.env\\.' " ^
    "}; " ^
    "try { " ^
    "    $files ^| Compress-Archive -DestinationPath $dst -Force; " ^
    "    Write-Host ''; " ^
    "    Write-Host '✓ 打包成功'  -ForegroundColor Green; " ^
    "    $size = (Get-Item $dst).Length; " ^
    "    Write-Host ('  文件: ' + $dst); " ^
    "    Write-Host ('  大小: ' + [math]::Round($size/1KB, 1) + ' KB'); " ^
    "    Write-Host ('  文件数: ' + $files.Count); " ^
    "} catch { " ^
    "    Write-Host '✗ 打包失败: ' $_.Exception.Message -ForegroundColor Red; " ^
    "    exit 1 " ^
    "}"

echo.
endlocal
