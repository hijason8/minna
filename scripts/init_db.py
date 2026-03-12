#!/usr/bin/env python3
"""
從指令列初始化 SQLite 資料庫（建立 app_data.db 與所有資料表）。
使用方式：python -m scripts.init_db
"""
import sys
from pathlib import Path

# 將專案根目錄加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import init_db, get_db_path


def main():
    path = get_db_path()
    init_db(path)
    print(f"資料庫已初始化：{path.absolute()}")


if __name__ == "__main__":
    main()
