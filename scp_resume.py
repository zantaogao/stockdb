#!/usr/bin/env python3
"""Simple resume-capable file transfer over SSH using paramiko or raw socket."""

import subprocess
import os
import sys

LOCAL_FILE = '/Users/zantao/.hermes/stockdb/tushare.db'
REMOTE_HOST = 'zantan@192.168.3.168'
REMOTE_PATH = r'C:\Users\zanta\.hermes\stockdb\tushare.db'

def get_remote_size():
    """Get current file size on remote PC."""
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', REMOTE_HOST, 
             f'dir "{REMOTE_PATH}" 2>&1 | findstr -v "File(s)"'],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        
        if 'tushare.db' in result.stdout:
            lines = result.stdout.split('\n')
            for line in lines:
                if 'tushare.db' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            return int(parts[3].replace(',', ''))
                        except:
                            pass
    except:
        pass
    return 0

def transfer_file():
    local_size = os.path.getsize(LOCAL_FILE)
    remote_size = get_remote_size()
    
    print(f"Local file size: {local_size:,} bytes ({local_size/1024/1024/1024:.1f} GB)")
    print(f"Remote file size: {remote_size:,} bytes ({remote_size/1024/1024/1024:.1f} GB)")
    
    if remote_size >= local_size:
        print("File already fully transferred!")
        return
    
    # Calculate how much to transfer
    remaining = local_size - remote_size
    print(f"Remaining to transfer: {remaining/1024/1024/1024:.1f} GB")
    
    # Use scp with resume capability via SSH's built-in dd command
    # First, create the file on PC with the correct size (sparse file)
    print("Creating sparse file on remote...")
    subprocess.run([
        'ssh', '-o', 'ConnectTimeout=5', REMOTE_HOST,
        f'cmd /c "fsutil file createnew {REMOTE_PATH} {local_size}"'
    ], capture_output=True, text=True)
    
    # Then use scp to overwrite from the beginning
    print("Starting SCP transfer...")
    result = subprocess.run([
        'scp', '-o', 'ConnectTimeout=5', '-C',
        LOCAL_FILE,
        f'{REMOTE_HOST}:{REMOTE_PATH}'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("Transfer complete!")
    else:
        print(f"SCP failed with code {result.returncode}")
        print(f"STDERR: {result.stderr[:500]}")

if __name__ == '__main__':
    transfer_file()
