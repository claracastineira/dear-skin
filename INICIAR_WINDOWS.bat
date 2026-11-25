@echo off
chcp 65001 >nul
title Dear Skin
cd /d "%~dp0"
echo.
echo  ==============================
echo   DEAR SKIN - arrancando la web...
echo  ==============================
echo.

where python >nul 2>nul
if errorlevel 1 goto sin_python

if exist ".venv\Scripts\activate.bat" goto instalar
echo  Primera vez: preparando el proyecto. Puede tardar unos minutos...
python -m venv .venv

:instalar
call ".venv\Scripts\activate.bat"
echo  Instalando lo necesario. Puede tardar varios minutos, no cierres la ventana...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if errorlevel 1 goto error_instalar

if not exist ".env" copy ".env.example" ".env" >nul
findstr /c:"gsk_tu_clave" ".env" >nul
if errorlevel 1 goto catalogo

echo.
echo  FALTA TU CLAVE DE GROQ, es gratis:
echo  1. Se abre la web de Groq: crea una cuenta y pulsa Create API Key.
echo  2. Copia la clave, que empieza por gsk_
echo  3. Se abre el Bloc de notas: cambia gsk_tu_clave por tu clave, guarda con Ctrl+G y cierralo.
start "" https://console.groq.com/keys
notepad ".env"
echo.
echo  Cuando hayas guardado la clave, pulsa una tecla para seguir.
pause >nul

:catalogo
if exist "chroma_db" goto arrancar
echo  Primera vez: preparando el catalogo. Puede tardar varios minutos...
python -m app.ingesta
if errorlevel 1 goto error_catalogo

:arrancar
echo.
echo  LISTO. La web se abre en tu navegador: http://localhost:8000
echo  Para apagarla, cierra esta ventana.
start "" cmd /c "timeout /t 8 >nul & start http://localhost:8000"
python -m uvicorn app.api:app
echo.
echo  La web se ha parado. Si ves un error arriba, haz una captura.
pause
exit /b

:sin_python
echo  FALTA PYTHON.
echo  1. Entra en https://www.python.org/downloads/ y descargalo.
echo  2. Al instalar, MARCA la casilla Add Python to PATH.
echo  3. Despues vuelve a hacer doble clic en este archivo.
start "" https://www.python.org/downloads/
pause
exit /b

:error_instalar
echo.
echo  ERROR al instalar las librerias. Haz una captura de esta ventana y enviasela a Claude.
pause
exit /b

:error_catalogo
echo.
echo  ERROR al preparar el catalogo. Haz una captura de esta ventana y enviasela a Claude.
if exist "chroma_db" rmdir /s /q "chroma_db"
pause
exit /b
