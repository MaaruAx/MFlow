@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  MFlow — Release signing (SHA256SUMS.txt + GPG)
:: ============================================================
::
:: Run this AFTER:
::   1. build_mflow.bat (produces release\MFlow-vX.Y.Z-x64-standalone.zip)
::   2. Compiling MFlow.iss with Inno Setup (produces installer\MFlow-vX.Y.Z-x64-Setup.exe)
::
:: Generates packaging\SHA256SUMS.txt (hashes of both files) and signs it
:: with your GPG key, producing SHA256SUMS.txt.asc — upload BOTH alongside
:: the release on Codeberg (in addition to the .zip/.exe you already
:: upload/attach).
::
:: ── Configuration ────────────────────────────────────────────────────────
:: Fingerprint of your GPG key (the one you generated in Kleopatra). Using
:: "-u" with the full fingerprint avoids ambiguity if you ever have more
:: than one key in your keyring.
set GPG_FINGERPRINT=3B4859FFA12947974836ADB48130B8F7C0C7FAEB

set MFLOW_VERSION=2.6.0
set MFLOW_ARCH=x64
set MFLOW_TAG=v%MFLOW_VERSION%
set ZIP_NAME=MFlow-%MFLOW_TAG%-%MFLOW_ARCH%-standalone.zip
set EXE_NAME=MFlow-%MFLOW_TAG%-%MFLOW_ARCH%-Setup.exe

set ZIP_PATH=release\%ZIP_NAME%
set EXE_PATH=installer\%EXE_NAME%

echo.
echo  ============================================
echo   Signing release %MFLOW_TAG%
echo  ============================================
echo.

if not exist "%ZIP_PATH%" (
    echo [ERROR] %ZIP_PATH% not found.
    echo         Run build_mflow.bat first.
    pause & exit /b 1
)
if not exist "%EXE_PATH%" (
    echo [ERROR] %EXE_PATH% not found.
    echo         Compile MFlow.iss with Inno Setup first.
    pause & exit /b 1
)

where gpg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] gpg not found in PATH.
    echo         Gpg4win should add it automatically — if not, add its
    echo         install folder ^(e.g. C:\Program Files ^(x86^)\GnuPG\bin^)
    echo         to your PATH environment variable manually.
    pause & exit /b 1
)

echo [1/3] Calculating SHA-256...
for /f "usebackq delims=" %%h in (`powershell -NoProfile -Command ^
    "(Get-FileHash -Algorithm SHA256 -Path '%ZIP_PATH%').Hash.ToLower()"`) do set ZIP_HASH=%%h
for /f "usebackq delims=" %%h in (`powershell -NoProfile -Command ^
    "(Get-FileHash -Algorithm SHA256 -Path '%EXE_PATH%').Hash.ToLower()"`) do set EXE_HASH=%%h

if "%ZIP_HASH%"=="" (
    echo [ERROR] Could not calculate the hash of %ZIP_PATH%.
    pause & exit /b 1
)
if "%EXE_HASH%"=="" (
    echo [ERROR] Could not calculate the hash of %EXE_PATH%.
    pause & exit /b 1
)

echo        %ZIP_NAME%: %ZIP_HASH%
echo        %EXE_NAME%: %EXE_HASH%

echo.
echo [2/3] Writing SHA256SUMS.txt...
if exist "SHA256SUMS.txt" del /q "SHA256SUMS.txt"
if exist "SHA256SUMS.txt.asc" del /q "SHA256SUMS.txt.asc"

:: Standard "hash  filename" format (two spaces) — compatible with
:: `sha256sum -c SHA256SUMS.txt` on Linux/Mac as well as manual checking.
> SHA256SUMS.txt (
    echo %ZIP_HASH%  %ZIP_NAME%
    echo %EXE_HASH%  %EXE_NAME%
)

echo.
echo [3/3] Signing with GPG ^(fingerprint %GPG_FINGERPRINT%^)...
echo        You'll be asked for your private key's passphrase.
gpg --local-user %GPG_FINGERPRINT% --detach-sign --armor SHA256SUMS.txt
if errorlevel 1 (
    echo [ERROR] GPG signing failed. Check that the fingerprint is correct
    echo         ^(gpg --list-secret-keys^) and that the key hasn't expired.
    pause & exit /b 1
)

echo.
echo  ============================================
echo   Done. Upload these files alongside the release on Codeberg:
echo     - %ZIP_PATH%
echo     - %EXE_PATH%
echo     - SHA256SUMS.txt
echo     - SHA256SUMS.txt.asc
echo.
echo   In this version's changelog, paste:
echo     SHA256 (%ZIP_NAME%): %ZIP_HASH%
echo     SHA256 (%EXE_NAME%): %EXE_HASH%
echo  ============================================
echo.
pause
