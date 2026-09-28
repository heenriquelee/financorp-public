@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto error
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto error
python -m pip install -r requirements.txt
if errorlevel 1 goto error
set FINANCORP_DEMO=1
python -m streamlit run app.py
goto end
:error
echo Falha ao preparar o FinanCorp. Confira se o Python 3 esta instalado.
pause
:end
