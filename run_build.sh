#!/bin/bash
cd /Users/zantao/.hermes/stockdb
rm -f stock_clean.db
python3 -u build_clean_db.py 2>&1