@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv-mobile-api\Scripts\python.exe" (
  echo [ERROR] Python environment not found: .venv-mobile-api
  pause
  exit /b 2
)
set "PATH=%CD%\ffmpeg\bin;%PATH%"
echo Listing UVR models advertised as Guitar targets...
".venv-mobile-api\Scripts\python.exe" -m tools.prepare_electric_guitar_model --model-dir "%CD%\models\uvr" --list-only
echo.
echo Only use a model whose dedicated_electric field is true.
echo Combined Guitar and htdemucs_6s are not accepted as Electric Guitar.
echo Copy one verified Electric Guitar model filename from the list above.
echo Then run:
echo .venv-mobile-api\Scripts\python.exe -m tools.prepare_electric_guitar_model --model-dir "%CD%\models\uvr" --model MODEL_FILENAME
pause
endlocal
