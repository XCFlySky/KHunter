# -*- coding: utf-8 -*-
"""Helper: download/upload a file on the Aliyun server via SFTP (paramiko).
Usage:
  python ssh_sftp.py get <remote_path> <local_path>
  python ssh_sftp.py put <local_path> <remote_path>
"""
import sys
import paramiko

HOST = "47.254.123.6"
USER = "root"
PASS = "Lcz2022@"

def main():
    action, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20,
                   banner_timeout=20, auth_timeout=20)
    sftp = client.open_sftp()
    if action == "get":
        sftp.get(src, dst)
        print(f"downloaded {src} -> {dst}")
    elif action == "put":
        sftp.put(src, dst)
        print(f"uploaded {src} -> {dst}")
    else:
        raise SystemExit("action must be get|put")
    sftp.close()
    client.close()

if __name__ == "__main__":
    main()
