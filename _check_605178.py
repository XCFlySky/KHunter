# -*- coding: utf-8 -*-
"""检测 605178 在 2026年6月 是否能被金三角策略选出"""
import sys
sys.path.insert(0, r'F:\PythonProject\KHunter')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, yaml
from utils.global_db import get_global_db
from strategy.golden_triangle_strategy import GoldenTriangleStrategy

CODE = '605178'
db = get_global_db()
name = db.get_all_stock_names().get(CODE, '')
print(f'股票: {CODE} {name}')

with open('config/strategy_params.yaml', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
strategy = GoldenTriangleStrategy(params=cfg['strategies']['GoldenTriangleStrategy'].get('params', {}))

df_full = db.read_stock(CODE).sort_values('date', ascending=False).reset_index(drop=True)
df_full['date'] = pd.to_datetime(df_full['date'])
print(f'数据: {len(df_full)}条, {str(df_full["date"].iloc[-1])[:10]} ~ {str(df_full["date"].iloc[0])[:10]}')

# 6月所有交易日逐日检测
days = [str(d)[:10] for d in df_full['date'] if str(d)[:7] == '2026-06']
print(f'\n6月交易日数: {len(days)}，逐日检测:')
found = False
for day in sorted(days):
    day_df = df_full[df_full['date'] <= pd.Timestamp(day)]
    if len(day_df) < 60:
        continue
    strategy._reject_reason = None
    r = strategy.analyze_stock(CODE, name, day_df)
    if r:
        found = True
        sig = r['signals'][0]
        cd = sig.get('cross_details', {})
        print(f'  ★ {day} 选中! {sig.get("reason")}')
        print(f'    A={cd.get("a_cross_date")} B={cd.get("b_cross_date")} C={cd.get("c_cross_date")} 间隔{cd.get("ac_interval_days")}天')
if not found:
    print('  6月没有任何一天被选中')

# 找6月内的C点金叉，看卡在哪个条件
print('\n6月内 MA10×MA20 金叉(C点)及条件明细:')
dfi = strategy.calculate_indicators(df_full.copy())
for i in range(0, len(dfi) - 1):
    d = str(dfi.iloc[i]['date'])[:10]
    if not d.startswith('2026-06'):
        continue
    curr, prev = dfi.iloc[i], dfi.iloc[i + 1]
    if prev['sma_mid'] < prev['sma_long'] and curr['sma_mid'] >= curr['sma_long']:
        # 该日作为信号日，跑完整诊断
        day_df = df_full[df_full['date'] <= curr['date']]
        strategy._reject_reason = None
        r = strategy.analyze_stock(CODE, name, day_df)
        gain = curr['gain'] * 100 if not pd.isna(curr['gain']) else 0
        vr = strategy._calc_volume_ratio(curr)
        tr = strategy._get_turnover_rate(curr)
        print(f'  C点 {d}: MA10={curr["sma_mid"]:.2f} MA20={curr["sma_long"]:.2f} 涨幅{gain:.1f}% 量比{vr:.2f} 换手{"-" if pd.isna(tr) else f"{tr:.1f}%"}')
        print(f'    → {"选中" if r else "未选中: " + str(strategy._reject_reason)}')

# 6月K线概览
print('\n6月K线（日期 收盘 涨幅% MA5 MA10 MA20）:')
for i in range(len(dfi)):
    d = str(dfi.iloc[i]['date'])[:10]
    if d.startswith('2026-06'):
        row = dfi.iloc[i]
        g = row['gain'] * 100 if not pd.isna(row['gain']) else 0
        print(f"  {d}  {row['close']:7.2f}  {g:6.2f}%  {row['sma_short']:.2f} {row['sma_mid']:.2f} {row['sma_long']:.2f}")
