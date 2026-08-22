@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv-mobile-api\Scripts\python.exe" (
  echo [ERROR] Python environment not found: .venv-mobile-api
  pause
  exit /b 2
)
set "PYTHONUTF8=1"
set "MODEL=roformer-model-bs-roformer-mvsep-mega-53-stems"
set "MODELDIR=%CD%\models\bs-roformer"
if not exist "%MODELDIR%" mkdir "%MODELDIR%"
echo Installing BS-RoFormer inference engine...
".venv-mobile-api\Scripts\python.exe" -m pip install --upgrade bs-roformer-infer
if errorlevel 1 goto :failed
echo Downloading and SHA256-verifying MVSep Mega 53-Stems model...
if exist ".venv-mobile-api\Scripts\bs-roformer-download.exe" (
  ".venv-mobile-api\Scripts\bs-roformer-download.exe" --model "%MODEL%" --output-dir "%MODELDIR%"
) else (
  ".venv-mobile-api\Scripts\python.exe" -m bs_roformer.download --model "%MODEL%" --output-dir "%MODELDIR%"
)
if errorlevel 1 goto :failed
".venv-mobile-api\Scripts\python.exe" -c "import json,pathlib; p=pathlib.Path(r'%MODELDIR%')/'mvsep-mega53-ready.json'; p.write_text(json.dumps({'model':'%MODEL%','electric':'electric-guitar','acoustic':'acoustic-guitar'},indent=2),encoding='utf-8'); print('READY:',p)"
echo MVSep Electric Guitar engine is ready.
pause
exit /b 0
:failed
echo [ERROR] Installation or model download failed. Send the last error screenshot.
pause
exit /b 3
