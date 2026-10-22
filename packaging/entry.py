"""PyInstaller entry. Worker arguments are an internal implementation detail."""
import sys

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        from pathlib import Path
        # A windowed Windows executable has no Python standard streams.
        root = Path(sys.argv[sys.argv.index('--project') + 1]) / '.runtime'
        root.mkdir(parents=True, exist_ok=True)
        log = (root / 'worker.log').open('a', encoding='utf-8', buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log
        from only_voice.worker import main
        raise SystemExit(main(sys.argv[2:]))
    from only_voice.tray import main
    raise SystemExit(main())
