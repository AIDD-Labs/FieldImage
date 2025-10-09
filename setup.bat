@echo off
echo Setting up FieldImage...

REM Create virtual environment
python -m venv .venv
IF ERRORLEVEL 1 (
    echo.
    echo ERROR: Failed to create virtual environment.
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat
IF ERRORLEVEL 1 (
    echo.
    echo ERROR: Failed to activate virtual environment.
    exit /b 1
)

REM Upgrade pip
python -m pip install --upgrade pip
IF ERRORLEVEL 1 (
    echo.
    echo ERROR: Failed to upgrade pip.
    echo Please check your internet connection or try upgrading pip manually.
    exit /b 1
)

REM Install the package
pip install .
IF ERRORLEVEL 1 (
    echo.
    echo ERROR: pip install failed.
    echo Please review the error messages above and ensure all dependencies are met.
    exit /b 1
)

echo.
echo Setup complete! Virtual environment is now active.
echo You can start using FieldImage inside this environment.