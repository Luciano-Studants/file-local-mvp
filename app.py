"""Arquivo Local: tray UI plus a disposable conversion worker."""
import sys

if '--worker' in sys.argv:
    from engine import worker_main
    raise SystemExit(worker_main())

from tray_app import main

if __name__ == '__main__':
    raise SystemExit(main())
