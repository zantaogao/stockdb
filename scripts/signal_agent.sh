#!/bin/bash
cd /Users/zantao/.hermes/stockdb
/usr/bin/python3 -B agents/signal_agent.py "$@"
/usr/bin/python3 -B new_factors.py 2>&1 | tail -5
