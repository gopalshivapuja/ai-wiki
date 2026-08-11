#!/usr/bin/env bash
# One-command local setup for LLM Wiki
set -euo pipefail

echo "🧠 LLM Wiki — Local Setup"
echo "========================="

# Python
pip install -e ".[api,dev]" -q
pip install -r requirements.txt -q

# Env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "✓ Created .env from template — add your OPENROUTER_API_KEY"
else
  echo "✓ .env already exists"
fi

# Web
if [ -d apps/web ]; then
  (cd apps/web && npm install --silent)
  echo "✓ Web dependencies installed"
fi

# Test
pytest tests/ -q
wiki lint

echo ""
echo "Ready! Start with:"
echo "  Terminal 1: uvicorn wiki_api.app:app --reload --port 8000"
echo "  Terminal 2: cd apps/web && npm run dev"
echo "  Browser:    http://localhost:5173"
echo ""
echo "CLI examples:"
echo "  wiki search 'attention'"
echo "  wiki query 'What is LoRA?'"
echo "  wiki ingest-web 'https://example.com'"
