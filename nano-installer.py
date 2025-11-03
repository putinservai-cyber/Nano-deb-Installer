#!/usr/bin/env python3
"""
Nano Installer Entry Point

This script serves as the main entry point for the Nano Installer application,
delegating execution to the modularized code within the nano_installer package.
"""
import sys
from pathlib import Path

# Ensure the package is in the Python path
# The package is installed to /usr/lib/nano-installer/
sys.path.insert(0, "/usr/lib/nano-installer/")
from nano_installer.main import main # noqa: E402

if __name__ == "__main__":
    main()
