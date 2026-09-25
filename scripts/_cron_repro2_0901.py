# EXACT reproduction of the cron error: a string containing the shell's warning
# text, decoded as GBK then re-encoded as UTF-8 (mojibake), then decoded UTF-8 strict.
# The cron scheduler's error message was:
#   'utf-8' codec can't decode byte 0xbc in position 42: invalid start byte
warn = '⚠️ backfill_stk_factor.py 失败 exit=1（因子未更新，信号用现有因子重算，保证当天有信号）'
mojibake = warn.encode('utf-8').decode('gbk', errors='replace').encode('gbk', errors='replace')
try:
    mojibake.decode('utf-8')
    print('no error')
except UnicodeDecodeError as e:
    print('REPRO:', e)
    print('byte at 42:', hex(mojibake[42]))
    # Show the GBK decoding of the bad region
    print('region as GBK:', mojibake[35:60].decode('gbk', errors='replace'))