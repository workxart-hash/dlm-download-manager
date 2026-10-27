"""PyInstaller entry point. One frozen exe exposes the whole CLI, including
`dlm get`, `dlm gui`, and `dlm native-host`."""

import sys

from dlm.cli import main

if __name__ == "__main__":
    sys.exit(main())
