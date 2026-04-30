#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from _bootstrap import ensure_project_root_on_path

ensure_project_root_on_path()

from src.core.unified_app import main, parse_args, run_pipeline


if __name__ == "__main__":
    main()
