#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from _bootstrap import ensure_project_root_on_path

ensure_project_root_on_path()

from src.parsers.parse_vk import main


if __name__ == "__main__":
    main()
