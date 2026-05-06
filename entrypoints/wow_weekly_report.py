#!/usr/bin/env python3
from _bootstrap import ensure_project_root_on_path

ensure_project_root_on_path()

from src.core.wow_weekly_report import main

if __name__ == "__main__":
    main()
