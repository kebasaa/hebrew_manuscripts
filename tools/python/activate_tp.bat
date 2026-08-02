@echo off
set "ACTIVATE_SCRIPT=%USERPROFILE%\.venvs\tp\Scripts\activate.bat"

if not exist "%ACTIVATE_SCRIPT%" (
    echo Could not find the shared tp environment.
    echo Expected activation script:
    echo   %ACTIVATE_SCRIPT%
    echo.
    echo Create it from this repository with:
    echo   python\install_tp.bat
    exit /b 1
)

call "%ACTIVATE_SCRIPT%"
set "ACTIVATE_SCRIPT="
