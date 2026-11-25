#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo "  =============================="
echo "   DEAR SKIN - arrancando la web..."
echo "  =============================="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "  FALTA PYTHON. Instálalo desde https://www.python.org/downloads/ y vuelve a abrir este archivo."
  open "https://www.python.org/downloads/"
  read -p "  Pulsa Enter para cerrar."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "  Primera vez: preparando el proyecto. Puede tardar unos minutos..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "  Instalando lo necesario..."
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

[ -f ".env" ] || cp .env.example .env
if grep -q "gsk_tu_clave" .env; then
  echo ""
  echo "  FALTA TU CLAVE DE GROQ (es gratis):"
  echo "  1. Se abre la web de Groq: crea una cuenta y pulsa 'Create API Key'."
  echo "  2. Copia la clave (empieza por gsk_)."
  echo "  3. Se abre un editor de texto: cambia gsk_tu_clave por tu clave, guarda (Cmd+S) y ciérralo."
  open "https://console.groq.com/keys"
  open -e .env
  read -p "  Cuando hayas guardado la clave, pulsa Enter para seguir."
fi

if [ ! -d "chroma_db" ]; then
  echo "  Primera vez: preparando el catálogo. Puede tardar varios minutos..."
  python -m app.ingesta
fi

echo ""
echo "  LISTO. La web se abre en tu navegador: http://localhost:8000"
echo "  Para apagarla, cierra esta ventana."
(sleep 8 && open "http://localhost:8000") &
python -m uvicorn app.api:app
