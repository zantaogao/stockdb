#!/bin/bash
cd ~/.hermes/stockdb
export PATH="$PWD/venv/bin:$PATH"
exec python3 fund_nav_daily_update.py
