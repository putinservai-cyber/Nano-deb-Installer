#!/usr/bin/env python3
"""
Nano Installer Entry Point

This script serves as the main entry point for the Nano Installer application,
delegating execution to the modularized code within the nano_installer package.
"""
import sysa
from nano_installer.main import main

if __name__ == "__main__":
    main()
