#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from _bootstrap import ensure_project_root_on_path

ensure_project_root_on_path()

from src.ui.app_ui import main, run_task_mode_if_requested


if __name__ == "__main__":
    import sys

    if run_task_mode_if_requested():
        sys.exit(0)
    main()
