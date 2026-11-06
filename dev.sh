#!/usr/bin/env bash
# Atalhos de desenvolvimento (Linux/macOS). Uso: ./dev.sh setup | doctor | run | test | fast | quality | smoke
set -euo pipefail
cd "$(dirname "$0")"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
PY=".venv/bin/python"
case "${1:-help}" in
  setup)   python3 -m venv .venv && "$PY" -m pip install --upgrade pip && "$PY" -m pip install -r requirements.txt -r requirements-dev.txt && "$PY" tools/doctor.py ;;
  doctor)  "$PY" tools/doctor.py ;;
  run)     QT_QPA_PLATFORM="" "$PY" app.py ;;
  test)    "$PY" -I -W ignore -m unittest discover -s tests -q ;;
  fast)    "$PY" -I -W ignore -m unittest discover -s tests -q -k pdfform -k pdfredact -k pdfinfo -k stamp ;;   # só um pedaço; ajuste o -k
  quality) "$PY" tools/quality_suite.py --only pdf --fast --out quality-report; "$PY" tools/quality_suite.py --only audio --fast --out quality-report-audio ;;
  smoke)   QT_QPA_PLATFORM="" "$PY" app.py --smoke-test ;;
  *) echo "uso: ./dev.sh setup|doctor|run|test|fast|quality|smoke" ;;
esac
