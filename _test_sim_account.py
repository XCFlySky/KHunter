# -*- coding: utf-8 -*-
"""模拟盘模块本地验证脚本（临时库，不污染 data/sim_account.db）"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.global_db import get_global_db
from trading.sim_account import SimAccount

TEST_DB = Path('data/_sim_test.db')
if TEST_DB.exists():
    TEST_DB.unlink()

db = get_global_db()

# 用平安银行(000001)的K线确定最近3个交易日
df = db.read_stock('000001', limit=10, order='desc')
dates = sorted(df['date'].dt.strftime('%Y-%m-%d').tolist())
d1, d2, d3 = dates[-3], dates[-2], dates[-1]
print(f"测试交易日: {d1} / {d2} / {d3}")

sim = SimAccount(db_path=str(TEST_DB))

candidates = [
    {'code': '000001', 'name': '平安银行', 'signals': ['t1'], 'strategies': ['金三角']},
    {'code': '600519', 'name': '贵州茅台', 'signals': ['t1'], 'strategies': ['金三角', '仙人指路']},
    {'code': '000002', 'name': '万科A', 'signals': ['t1'], 'strategies': ['金三角']},
]

print("\n=== Day1: 生成买单 + 记净值 ===")
print(sim.run_daily(d1, candidates))

print("\n=== Day1 幂等检查（应跳过）===")
r = sim.run_daily(d1, candidates)
assert r.get('skipped'), "幂等失败！"
print("幂等 OK:", r)

print("\n=== Day2: 开盘成交昨日买单 ===")
print(sim.run_daily(d2, []))

print("\n=== Day3: 正常结算 ===")
print(sim.run_daily(d3, candidates))

print("\n=== 持仓 ===")
for p in sim.get_positions():
    print(f"  {p['code']} {p['name']} x{p['quantity']} 买价{p['buy_price']} 现价{p['current_price']} 收益{p['return_rate']*100:+.2f}%")

print("\n=== 成交明细 ===")
for t in sim.get_trades():
    print(f"  {t['trade_date']} {t['side']} {t['code']} {t['name']} x{t['quantity']} @ {t['price']} 费用{t['fee']} 盈亏{t.get('profit')}")

print("\n=== 净值序列 ===")
for n in sim.get_nav_series():
    print(f"  {n['nav_date']} 现金{n['cash']:,.2f} 市值{n['market_value']:,.2f} 总资产{n['total_assets']:,.2f} 日收益{n['daily_return']*100:+.2f}% 累计{n['cum_return']*100:+.2f}%")

print("\n=== 指标 ===")
for k, v in sim.get_metrics().items():
    print(f"  {k}: {v}")

TEST_DB.unlink(missing_ok=True)
print("\n验证完成，测试库已清理")
