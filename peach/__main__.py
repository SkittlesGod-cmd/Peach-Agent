"""Allow `python -m peach ...` as a CLI fallback."""

from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
