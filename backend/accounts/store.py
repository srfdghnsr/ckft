# -*- coding: utf-8 -*-
"""状态持久化（JSON）。"""
import json
import os
from backend.config import STATE_PATH


def save_state(data: dict, path=STATE_PATH):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_state(path=STATE_PATH):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_params(params: dict, path=None):
    from backend.config import PARAMS_PATH
    path = path or PARAMS_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)


def load_params(default):
    from backend.config import PARAMS_PATH
    if os.path.exists(PARAMS_PATH):
        try:
            with open(PARAMS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = dict(default)
            merged.update(saved)
            return merged
        except Exception:
            return dict(default)
    return dict(default)
