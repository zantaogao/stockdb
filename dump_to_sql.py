#!/usr/bin/env python3
"""Dump DuckDB tushare.db to SQL file (CREATE TABLE + INSERT format)."""

import duckdb
import os
import time
import datetime

DB_PATH = '/Users/zantao/.hermes/stockdb/tushare.db'
OUTPUT_PATH = sys.argv[1] if len(sys.argv) > 1 else '/Users/zantao/.hermes/stockdb/tushare_dump.sql'
BATCH_SIZE = 2000  # rows per INSERT batch


def get_column_type(col_type):
    t = col_type.upper()
    mapping = {
        'VARCHAR': 'TEXT', 'CHAR': 'TEXT', 'TEXT': 'TEXT', 'STRING': 'TEXT',
        'INT': 'INTEGER', 'INTEGER': 'INTEGER', 'BIGINT': 'INTEGER',
        'DOUBLE': 'REAL', 'REAL': 'REAL', 'FLOAT': 'REAL',
        'BOOLEAN': 'INTEGER', 'TIMESTAMP': 'TEXT', 'DATE': 'TEXT', 'JSON': 'TEXT',
    }
    return mapping.get(t, 'TEXT' if 'STRING' in t or 'CHAR' in t or 'TEXT' in t or 'VARCHAR' in t else 'REAL' if 'INT' in t else 'TEXT')


def escape_sql_value(value, col_type):
    if value is None:
        return 'NULL'
    t = col_type.upper()
    if any(x in t for x in ('TEXT', 'VARCHAR', 'CHAR', 'DATE', 'TIMESTAMP', 'JSON', 'STRING')):
        s = str(value).replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        return "'" + s + "'"
    elif any(x in t for x in ('INTEGER', 'BIGINT', 'INT', 'BOOLEAN')):
        return str(int(value))
    elif any(x in t for x in ('REAL', 'DOUBLE', 'FLOAT')):
        s = str(value)
        if s in ('nan', 'NaN'):
            return 'NULL'
        return s
    return "'" + str(value) + "'"


def dump_table(con, cursor, table_name, col_names, col_types):
    start = time.time()
    cursor.write("CREATE TABLE IF NOT EXISTS " + table_name + " (\n")
    for i, (name, ctype) in enumerate(zip(col_names, col_types)):
        comma = "," if i < len(col_names) - 1 else ""
        cursor.write("  " + name + " " + ctype + comma + "\n")
    cursor.write(");\n")

    batch = []
    batch_count = 0
    total_rows = 0

    select_cols = ', '.join(['"' + c + '"' for c in col_names])
    query = 'SELECT ' + select_cols + ' FROM "' + table_name + '"'
    result = con.execute(query)

    while True:
        rows = result.fetchmany(BATCH_SIZE)
        if not rows:
            break
        for row in rows:
            values = ', '.join([escape_sql_value(v, ct) for v, ct in zip(row, col_types)])
            batch.append("(" + values + ")")
            total_rows += 1
            if len(batch) >= BATCH_SIZE:
                cursor.write("INSERT INTO " + table_name + " VALUES " + ','.join(batch) + ";\n")
                batch = []
                batch_count += 1

    if batch:
        cursor.write("INSERT INTO " + table_name + " VALUES " + ','.join(batch) + ";\n")
        batch_count += 1

    elapsed = time.time() - start
    size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
    print("  " + table_name.ljust(25) + ": {:>10,} rows, {:>4} batches, {:>6.1f}s, file now {:>8.0f} MB".format(
        total_rows, batch_count, elapsed, size_mb))
    return total_rows


def main():
    print("=" * 60)
    print("tushare.db SQL Dump")
    print("Source: " + DB_PATH)
    print("Output: " + OUTPUT_PATH)
    print("=" * 60)

    con = duckdb.connect(DB_PATH)

    tables = con.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name != '_test_speed'
        ORDER BY name
    """).fetchall()

    total_rows = 0
    total_time = time.time()

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write("-- tushare.db SQL Dump\n")
        f.write("-- Generated: " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + "\n")
        f.write("-- Source: " + DB_PATH + "\n")
        dbver = con.execute('SELECT version()').fetchone()[0]
        f.write("-- DuckDB version: " + str(dbver) + "\n")
        f.write("-- Tables: " + str(len(tables)) + "\n\n")

        for (table_name,) in tables:
            desc = con.execute('DESCRIBE "' + table_name + '"').fetchall()
            col_names = [row[0] for row in desc]
            col_types_raw = [row[1] for row in desc]
            col_types = [get_column_type(ct) for ct in col_types_raw]

            if not desc:
                pragma = con.execute('PRAGMA table_info("' + table_name + '")').fetchall()
                if pragma:
                    col_names = [row[0] for row in pragma]
                    col_types = [get_column_type(row[1]) for row in pragma]
                else:
                    print("  WARNING: no columns for " + table_name)
                    f.write("\n")
                    continue

            rows = dump_table(con, f, table_name, col_names, col_types)
            total_rows += rows
            f.write("\n")

    elapsed = time.time() - total_time
    size_gb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024 / 1024

    print("\n" + "=" * 60)
    print("Dump complete!")
    print("  Total rows: " + "{:,}".format(total_rows))
    print("  Total time: {:.1f}s".format(elapsed))
    print("  File size:  {:.2f} GB".format(size_gb))
    print("  Tables: " + str(len(tables)))
    print("=" * 60)

    con.close()


if __name__ == '__main__':
    main()
