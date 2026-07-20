# -*- coding: utf-8 -*-
"""对金三角33只信号股做五维评分（重点看资金面）"""
import sys, json, os
sys.path.insert(0, r'F:\PythonProject\KHunter')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from trading.stock_score_calculator import StockScoreCalculator

with open(os.path.join(os.environ['TEMP'], 'sel_rerun.json'), encoding='utf-8-sig') as f:
    r = json.load(f)
stocks = [(s['code'], s['name']) for s in r['data']['金三角策略']]
codes = [c for c, n in stocks]
names = dict(stocks)
print(f'共 {len(codes)} 只信号股，评分日期 2026-07-17\n')

calc = StockScoreCalculator()
results = calc.calculate_score(codes, '2026-07-17')

rows = []
for s in results:
    rows.append({
        'code': s.stock_code,
        'name': names.get(s.stock_code, ''),
        'total': s.total_score,
        'level': s.score_level,
        'tech': s.technical_score,
        'money': s.moneyflow_score,
        'fund': s.fundamental_score,
        'sector': s.sector_score,
        'event': s.event_score,
    })
df = pd.DataFrame(rows).sort_values('total', ascending=False)
pd.set_option('display.width', 200)
pd.set_option('display.unicode.east_asian_width', True)
print('===== 五维评分排名（按总分降序）=====')
print(df.to_string(index=False))

print('\n===== 资金面维度单列（降序）=====')
dm = df.sort_values('money', ascending=False)[['code', 'name', 'money', 'total']]
print(dm.to_string(index=False))
print(f'\n资金面: 平均 {df["money"].mean():.1f}, 中位 {df["money"].median():.1f}, >0占比 {(df["money"]>0).mean()*100:.0f}%')
print(f'总分: 平均 {df["total"].mean():.1f}, 等级分布: {dict(df["level"].value_counts())}')
