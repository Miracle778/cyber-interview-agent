#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Cyber Interview Agent local development"
echo ""
echo "1. Start backend:"
echo "   cd \"$ROOT_DIR/backend\" && uv run fastapi dev app/main.py"
echo ""
echo "2. Start frontend in another terminal:"
echo "   pnpm --dir \"$ROOT_DIR/frontend\" dev"
echo ""
echo "3. Open:"
echo "   http://127.0.0.1:5173"
echo ""
echo "4. Sample file:"
echo "   $ROOT_DIR/examples/cache_question.txt"
