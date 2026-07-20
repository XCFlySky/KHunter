# -*- coding: utf-8 -*-
"""从 Tushare daily_basic 拉取最新总市值，回填 stock_basic.market_cap（单位：元）"""
import sys, json, time
sys.path.insert(0, r'F:\PythonProject\KHunter')
sys.stdout.reconfigure(encoding='utf-8')
import tushare as ts
from utils.global_db import get_global_db

with open(r'F:\PythonProject\KHunter\config\tushare_config.json', encoding='utf-8') as f:
    token = json.load(f)['token']
pro = ts.pro_api(token)

db = get_global_db()

# 找最近一个有数据的交易日
trade_date = None
for d in ['20260717', '20260716', '20260715']:
    df = pro.daily_basic(trade_date=d, fields='ts_code,total_mv')
    if df is not None and not df.empty:
        trade_date = d
        break
if df is None or df.empty:
    print('未获取到市值数据')
    sys.exit(1)
print(f'交易日 {trade_date}: 获取 {len(df)} 只股票的市值')

# ts_code -> 6位代码；total_mv 单位万元 -> 元
updated, skipped = 0, 0
rows = []
for _, r in df.iterrows():
    code = str(r['ts_code']).split('.')[0]
    mv = r['total_mv']
    if mv and mv > 0:
        rows.append((float(mv) * 1e4, code))  # 万元 -> 元
    else:
        skipped += 1

conn = db.connect()
cur = conn.cursor()
cur.executemany('UPDATE stock_basic SET market_cap = ?, update_time = datetime("now", "localtime") WHERE code = ?', rows)
conn.commit()
updated = cur.rowcount if cur.rowcount else 0
print(f'回填完成: 更新 {updated} 行, 跳过 {skipped} 只')

# 验证日联科技
r = db.query_one("SELECT code, name, market_cap FROM stock_basic WHERE code='688531'")
print('日联科技:', r)
