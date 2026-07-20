# -*- coding: utf-8 -*-
"""信号质量统计：33只金三角信号股选出后 T+1/T+3/T+5 收益表现"""
import sys, json, os
sys.path.insert(0, r'F:\PythonProject\KHunter')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from utils.global_db import get_global_db

with open(os.path.join(os.environ['TEMP'], 'sel_rerun.json'), encoding='utf-8-sig') as f:
    r = json.load(f)

# 收集 (日期, 股票) 信号
signals = []
for day, day_data in r['data']['_by_date'].items():
    for k, v in day_data.items():
        if isinstance(v, list):
            for s in v:
                signals.append({'date': day, 'code': s['code'], 'name': s['name']})

db = get_global_db()
rows = []
for sig in signals:
    df = db.read_stock(sig['code']).sort_values('date', ascending=True).reset_index(drop=True)
    df['date'] = pd.to_datetime(df['date'])
    idx_list = df.index[df['date'] == pd.Timestamp(sig['date'])].tolist()
    if not idx_list:
        continue
    i = idx_list[0]
    entry = {'date': sig['date'], 'code': sig['code'], 'name': sig['name'],
             'close': df.iloc[i]['close']}
    c0 = df.iloc[i]['close']
    for n in (1, 3, 5):
        if i + n < len(df):
            entry[f'r{n}'] = (df.iloc[i + n]['close'] / c0 - 1) * 100
        else:
            entry[f'r{n}'] = None
    # 5日内最大不利变动（最低价相对信号日收盘）
    future = df.iloc[i + 1: i + 6]
    entry['max_dd'] = (future['low'].min() / c0 - 1) * 100 if len(future) > 0 else None
    # 5日内最大有利变动
    entry['max_up'] = (future['high'].max() / c0 - 1) * 100 if len(future) > 0 else None
    rows.append(entry)

res = pd.DataFrame(rows)
pd.set_option('display.width', 200)
pd.set_option('display.unicode.east_asian_width', True)

print('===== 逐股明细（收益%，相对信号日收盘）=====')
show = res.copy()
for c in ('r1', 'r3', 'r5', 'max_dd', 'max_up'):
    show[c] = show[c].map(lambda x: f'{x:+.1f}' if pd.notna(x) else '  -')
print(show[['date', 'code', 'name', 'close', 'r1', 'r3', 'r5', 'max_up', 'max_dd']].to_string(index=False))

print('\n===== 汇总统计 =====')
for n, label in ((1, 'T+1'), (3, 'T+3'), (5, 'T+5')):
    col = res[f'r{n}'].dropna()
    if len(col) == 0:
        continue
    win = (col > 0).sum()
    print(f'{label}: 样本{len(col)}只, 胜率 {win}/{len(col)} = {win/len(col)*100:.0f}%, '
          f'平均 {col.mean():+.2f}%, 中位数 {col.median():+.2f}%, '
          f'最好 {col.max():+.1f}%, 最差 {col.min():+.1f}%')

# 大盘环境分组：7-10 大盘下跌前 vs 后
print('\n===== 按信号日分组（7-10 起大盘回调）=====')
for group_name, cond in (('6-22~7-09 信号', res['date'] <= '2026-07-09'),
                          ('7-10 之后信号', res['date'] > '2026-07-09')):
    g = res[cond]
    if len(g) == 0:
        print(f'{group_name}: 无样本')
        continue
    r3 = g['r3'].dropna()
    win = (r3 > 0).sum() if len(r3) else 0
    print(f'{group_name}: {len(g)}只, T+3胜率 {win}/{len(r3)}, T+3平均 {r3.mean():+.2f}%' if len(r3) else f'{group_name}: {len(g)}只, 无T+3数据')

# 最差案例
print('\n===== T+3 最差 5 只 =====')
worst = res.dropna(subset=['r3']).nsmallest(5, 'r3')
for _, x in worst.iterrows():
    print(f"  {x['date']} {x['code']} {x['name']}: T+1 {x['r1']:+.1f}%  T+3 {x['r3']:+.1f}%  5日最大回撤 {x['max_dd']:+.1f}%")
