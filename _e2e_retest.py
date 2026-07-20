# -*- coding: utf-8 -*-
"""E2E 复测：针对首轮失败的 9 项，使用正确参数重新验证"""
import json
import sys
import time

import requests

BASE = 'http://47.254.123.6:5001'
TODAY = '2026-07-20'
TODAY_FMT = '20260720'
RESULTS = []


def check(name, method, path, payload=None, timeout=60, note_key=None):
    t0 = time.time()
    status, ok, note = '-', False, ''
    try:
        if method == 'GET':
            r = requests.get(BASE + path, timeout=timeout)
        else:
            r = requests.post(BASE + path, json=payload or {}, timeout=timeout)
        status = r.status_code
        try:
            j = r.json()
            ok = bool(j.get('success')) or j.get('status') == 'success'
            if ok:
                d = j.get('data', j)
                note = f'{len(d)} 条记录' if isinstance(d, list) else ('keys=' + ','.join(list(d.keys())[:4]) if isinstance(d, dict) else 'ok')
            else:
                note = str(j.get('message') or j.get('error') or '')[:120]
        except ValueError:
            ok = r.status_code == 200 and len(r.content) > 0
            note = f'文件/非JSON {len(r.content)}B'
    except Exception as e:
        note = f'{type(e).__name__}: {str(e)[:100]}'
    el = time.time() - t0
    RESULTS.append((name, ok, el, note))
    print(f"[{'PASS' if ok else 'FAIL'}] {name:<26} {method} {path} -> {status} {el:6.1f}s {note}", flush=True)
    return ok, note


print('【复测：首轮失败的 9 项 + 修复验证】\n')

# 1. 导出报告（需 stock_code）
check('导出报告', 'GET', '/api/export-report?stock_code=000001', timeout=120)

# 2-4. 趋势动物：先搜索拿 tmId，再测快照/绘图/信号股票
tm_id = None
try:
    j = requests.get(BASE + '/api/trend/search?keyword=000001', timeout=30).json()
    data = j.get('data') or []
    if data:
        tm_id = data[0].get('tmId') or data[0].get('id')
    print(f'(趋势搜索得到 tmId={tm_id})', flush=True)
except Exception as e:
    print(f'(趋势搜索异常: {e})', flush=True)

if tm_id:
    check('趋势快照', 'GET', f'/api/trend/snapshot?tmIds={tm_id}', timeout=60)
    check('趋势绘图', 'GET', f'/api/trend/plot?tmId={tm_id}', timeout=60)
else:
    RESULTS.append(('趋势快照', False, 0, '无 tmId 无法测试'))
    RESULTS.append(('趋势绘图', False, 0, '无 tmId 无法测试'))
check('信号股票趋势确认', 'GET', f'/api/trend/signal-stocks?date={TODAY}', timeout=180)

# 5-7. 市场温度（参数名 trade_date，YYYYMMDD）
check('温度查询', 'GET', f'/api/market-temperature/query?trade_date={TODAY_FMT}')
check('仓位比例', 'GET', f'/api/market-temperature/position-ratio?trade_date={TODAY_FMT}', timeout=120)
check('计算温度', 'POST', '/api/market-temperature/calculate', {'trade_date': TODAY_FMT}, timeout=180)

# 8-9. 回测约束（需日期参数）
check('回测约束列表', 'GET', f'/api/backtest/constraints?start_date=2026-06-01&end_date={TODAY}', timeout=120)
check('回测约束详情', 'GET', f'/api/backtest/constraint?trade_date={TODAY_FMT}', timeout=60)

# 10. 风控状态（验证 index_data_fetcher token 修复）
check('风控状态', 'GET', '/api/risk/status', timeout=120)

print('\n===== 复测汇总 =====')
p = sum(1 for r in RESULTS if r[1])
print(f'{p}/{len(RESULTS)} 通过')
for r in RESULTS:
    if not r[1]:
        print(f'  FAIL: {r[0]} - {r[3]}')
sys.exit(0 if p == len(RESULTS) else 1)
