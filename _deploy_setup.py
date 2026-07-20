# -*- coding: utf-8 -*-
"""服务器初始化：配置密钥登录 + 探测环境"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import paramiko
from pathlib import Path

HOST = '47.254.123.6'
USER = 'root'
PASSWORD = 'Lcz2022@'
PUBKEY = Path.home().joinpath('.ssh/khunter_deploy.pub').read_text().strip()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=20)
print('密码登录成功')

def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# 配置密钥
run("mkdir -p ~/.ssh && chmod 700 ~/.ssh")
run(f"echo '{PUBKEY}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys")
print('公钥已写入 authorized_keys')

# 探测环境
for label, cmd in [
    ('系统', 'lsb_release -d; uname -m'),
    ('Python', 'python3 --version; which python3'),
    ('内存', 'free -h | head -2'),
    ('磁盘', 'df -h / | tail -1'),
    ('CPU', 'nproc'),
    ('pip/venv', 'python3 -m pip --version 2>&1 | head -1; dpkg -l python3-venv 2>/dev/null | tail -1'),
]:
    out, err = run(cmd)
    print(f'--- {label} ---')
    print(out or err)

ssh.close()
print('完成')
