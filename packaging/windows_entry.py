"""PyInstaller entry point for the Windows build."""
import sys

from x6100_remote.app import main

sys.exit(main())
