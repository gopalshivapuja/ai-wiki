#!/usr/bin/env python3
"""Backward-compatible entrypoint — delegates to wiki CLI."""

from wiki_cli.main import app

if __name__ == "__main__":
    app()
