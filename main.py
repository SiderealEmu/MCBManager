#!/usr/bin/env python3
"""
MCBManager

A desktop application for managing addons on a Minecraft Bedrock Dedicated Server.
"""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path.parent))

from src.ui import MainWindow


def main():
    """Main entry point."""
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
