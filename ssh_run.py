# -*- coding: utf-8 -*-
"""Helper: run a remote command on the Aliyun server via SSH (paramiko)."""
import sys
import paramiko

HOST = "47.254.123.6"
USER = "root"
PASS = "Lcz2022@"

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "echo no-cmd"
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20,
                   banner_timeout=20, auth_timeout=20)
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    print(f"\n[exit={rc}]")
    client.close()

if __name__ == "__main__":
    main()
