@echo off
setlocal EnableDelayedExpansion

REM Installs the shared, global "tp" environment under your user profile:
REM   %USERPROFILE%\.venvs\tp
REM Contents: Python 3.12, JupyterLab, pandas, numpy (+ a Jupyter kernel).

set "VENV_PATH=%USERPROFILE%\.venvs\tp"
set "PYTHON_VERSION=3.12"
set "PYTHON_PATH=%VENV_PATH%\Scripts\python.exe"

REM --- Locate uv (on PATH, else the default per-user install location) ---
set "UV_PATH="
for /f "delims=" %%I in ('where uv 2^>nul') do (
    if not defined UV_PATH set "UV_PATH=%%I"
)
if not defined UV_PATH (
    if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_PATH=%USERPROFILE%\.local\bin\uv.exe"
)
if not defined UV_PATH (
    echo uv was not found. Install uv first, then rerun this script.
    echo Expected uv on PATH or at: %USERPROFILE%\.local\bin\uv.exe
    exit /b 1
)
echo Using uv: %UV_PATH%

REM --- Create the environment if it does not exist yet ---
if not exist "%PYTHON_PATH%" (
    echo Creating shared tp environment at: %VENV_PATH%
    "%UV_PATH%" venv "%VENV_PATH%" --python %PYTHON_VERSION%
    if errorlevel 1 (
        echo uv venv failed.
        exit /b 1
    )
)

if not exist "%PYTHON_PATH%" (
    echo The tp environment was not created correctly; Python is missing: %PYTHON_PATH%
    exit /b 1
)

REM --- Install / update the packages into the tp environment ---
echo Installing packages into: %VENV_PATH%
"%UV_PATH%" pip install --python "%PYTHON_PATH%" jupyterlab pandas numpy
if errorlevel 1 (
    echo Package installation failed.
    exit /b 1
)

REM --- Register a Jupyter kernel so tp is selectable from any Jupyter install ---
"%PYTHON_PATH%" -m ipykernel install --user --name tp --display-name "Python (tp)"
if errorlevel 1 (
    echo Jupyter kernel installation failed.
    exit /b 1
)

echo.
echo The shared tp environment is ready.
echo.
echo Activate it from CMD with:
echo   call "%VENV_PATH%\Scripts\activate.bat"
echo Or from this repository:
echo   python\activate_tp.bat
echo.
echo Activate it in PowerShell with:
echo   ^& "%VENV_PATH%\Scripts\Activate.ps1"
echo.
echo Launch JupyterLab with:
echo   jupyter lab

endlocal
