@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
rem Сборка проверенной версии. Требуются Rust и Visual Studio Build Tools C++.
set "SOURCE_DIR=.toolchains\win-nightlight-cli"
set "WNL_COMMIT=1081b0a9d11a7ba84bcc40385807e99b1b5ac306"
if exist ".toolchains\cargo\bin\cargo.exe" (
    set "CARGO_HOME=%CD%\.toolchains\cargo"
    set "RUSTUP_HOME=%CD%\.toolchains\rustup"
    set "PATH=%CD%\.toolchains\cargo\bin;%PATH%"
)
where cargo.exe >nul 2>&1
if errorlevel 1 (
    echo Не найден Cargo. Установите Rust для сборки wnl.exe.
    exit /b 1
)
if not exist "%SOURCE_DIR%\Cargo.toml" (
    git clone --no-checkout https://github.com/kvnxiao/win-nightlight-cli.git "%SOURCE_DIR%"
    if errorlevel 1 exit /b 1
    git -C "%SOURCE_DIR%" checkout --detach %WNL_COMMIT%
    if errorlevel 1 exit /b 1
)
set "ACTUAL_COMMIT="
for /f "delims=" %%I in ('git -C "%SOURCE_DIR%" rev-parse HEAD') do set "ACTUAL_COMMIT=%%I"
if not "%ACTUAL_COMMIT%"=="%WNL_COMMIT%" (
    echo Версия исходников wnl отличается от проверенного коммита.
    exit /b 1
)
set "WNL_DIRTY="
for /f "delims=" %%I in ('git -C "%SOURCE_DIR%" status --porcelain') do set "WNL_DIRTY=yes"
if defined WNL_DIRTY (
    echo В исходниках wnl есть изменения. Сборка остановлена.
    exit /b 1
)
rustup.exe target add --toolchain stable x86_64-pc-windows-msvc
if errorlevel 1 exit /b 1
set "RUSTFLAGS=-C target-feature=+crt-static"
cargo.exe +stable build --locked --release --target x86_64-pc-windows-msvc --manifest-path "%SOURCE_DIR%\Cargo.toml" --package win-nightlight-cli
if errorlevel 1 exit /b 1
copy /y "%SOURCE_DIR%\target\x86_64-pc-windows-msvc\release\wnl.exe" "tools\wnl.exe" >nul
if errorlevel 1 exit /b 1
copy /y "%SOURCE_DIR%\LICENSE" "tools\WNL_LICENSE.txt" >nul
if errorlevel 1 exit /b 1
echo Готово: tools\wnl.exe
