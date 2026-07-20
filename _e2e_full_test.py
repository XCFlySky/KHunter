# -*- coding: utf-8 -*-
"""
KHunter 全功能端到端测试
模拟用户从前端页面逐个点击，调用与前端相同的 API，输出每项功能的可用性。

用法:
  python _e2e_full_test.py [--base http://47.254.123.6:5001]
"""
import argparse
import json
import time
import sys

import requests

requests.packages.urllib3.disable_warnings()

RESULTS = []  # (page, name, method, path, status, ok, elapsed, note)
BASE = "http://47.254.123.6:5001"
TODAY = "2026-07-20"


def check(page, name, method, path, payload=None, timeout=30, expect_key='success'):
    """调用 API 并记录结果"""
    url = BASE + path
    t0 = time.time()
    status, ok, note = '-', False, ''
    try:
        if method == 'GET':
            r = requests.get(url, timeout=timeout)
        else:
            r = requests.post(url, json=payload or {}, timeout=timeout)
        status = r.status_code
        try:
            j = r.json()
            if expect_key in j:
                ok = bool(j.get(expect_key))
                if not ok:
                    note = str(j.get('message') or j.get('error') or '')[:100]
            elif j.get('status') == 'success':
                ok = True
            else:
                # 无 success 字段的接口（如 portfolio），HTTP 200 且有内容即算通过
                ok = r.status_code == 200
            if ok:
                note = _brief(j)
        except ValueError:
            ok = r.status_code == 200 and len(r.content) > 0
            note = f'非JSON响应 {len(r.content)}B'
    except requests.exceptions.Timeout:
        note = f'超时(>{timeout}s)'
    except Exception as e:
        note = f'{type(e).__name__}: {str(e)[:80]}'
    elapsed = time.time() - t0
    RESULTS.append((page, name, method, path, status, ok, elapsed, note))
    mark = 'PASS' if ok else 'FAIL'
    print(f'  [{mark}] {name:<28} {method:<4} {path:<52} {status} {elapsed:6.1f}s {note}', flush=True)
    return ok, note


def _brief(j):
    """从响应里提取简短摘要"""
    if isinstance(j, dict):
        d = j.get('data', j)
        if isinstance(d, list):
            return f'{len(d)} 条记录'
        if isinstance(d, dict):
            keys = list(d.keys())[:4]
            return 'keys=' + ','.join(keys) if keys else 'ok'
        if 'total' in j:
            return f"total={j['total']}"
    return 'ok'


def skip(page, name, method, path, reason):
    RESULTS.append((page, name, method, path, 'SKIP', None, 0, reason))
    print(f'  [SKIP] {name:<28} {method:<4} {path:<52} -      - {reason}', flush=True)


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=BASE)
    args = ap.parse_args()
    BASE = args.base.rstrip('/')
    print(f'目标服务器: {BASE}\n' + '=' * 100, flush=True)

    # ========== 0. 首页 ==========
    page = '首页'
    print(f'\n【{page}】', flush=True)
    check(page, '打开首页', 'GET', '/')

    # ========== 1. Dashboard 仪表盘 ==========
    page = '仪表盘'
    print(f'\n【{page}】', flush=True)
    check(page, '我的金叉股票', 'GET', '/api/dashboard/my-golden-stocks')
    ok, note = check(page, '热门行业', 'GET', '/api/dashboard/hot-industries')
    check(page, '热门地区', 'GET', '/api/dashboard/hot-areas')
    check(page, '行业成分股', 'GET', '/api/dashboard/industry-stocks?industry=半导体')
    check(page, '地区成分股', 'GET', '/api/dashboard/area-stocks?area=广东')
    check(page, '统计数据', 'GET', '/api/stats')

    # ========== 2. 个股图谱 ==========
    page = '个股图谱'
    print(f'\n【{page}】', flush=True)
    check(page, '股票列表', 'GET', '/api/stocks')
    check(page, '个股详情', 'GET', '/api/stock/000001')
    check(page, '分析股票', 'POST', '/api/analyze-stock', {'stock_code': '000001', 'period': '30d'}, timeout=120)
    check(page, '分析历史', 'GET', '/api/analysis-history')
    check(page, '导出报告列表', 'GET', '/api/export-report')

    # ========== 3. 执行选股（选1个快速策略模拟点击"执行选股"） ==========
    page = '执行选股'
    print(f'\n【{page}】', flush=True)
    ok, note = check(page, '获取策略名称列表', 'GET', '/api/strategies/names')
    strategy_key = None
    try:
        j = requests.get(BASE + '/api/strategies', timeout=30).json()
        items = j.get('data') or j.get('strategies') or []
        if isinstance(items, dict):
            items = list(items.values())
        for s in items:
            name = s.get('name', '') if isinstance(s, dict) else str(s)
            disp = s.get('display_name', '') if isinstance(s, dict) else ''
            if '多方炮' in disp or '多方炮' in name:
                strategy_key = name
                break
        if not strategy_key and items:
            s = items[0]
            strategy_key = s.get('name') if isinstance(s, dict) else str(s)
    except Exception as e:
        print(f'  (获取策略名失败: {e})', flush=True)
    if strategy_key:
        check(page, f'执行选股[{strategy_key}]', 'POST', '/api/select',
              {'strategies': [strategy_key], 'end_date': TODAY}, timeout=600)
    else:
        skip(page, '执行选股', 'POST', '/api/select', '未获取到策略名')
    skip(page, '保存选股结果', 'POST', '/api/save_selection', '写操作，避免产生重复数据')
    check(page, '选股历史', 'GET', '/api/selection-history')

    # ========== 4. 选股排名 ==========
    page = '选股排名'
    print(f'\n【{page}】', flush=True)
    check(page, '可选日期', 'GET', '/api/ranking/dates')
    check(page, '生成排名', 'POST', '/api/ranking/generate', {'selection_date': TODAY}, timeout=600)
    check(page, '排名跟踪', 'GET', f'/api/ranking/track?selection_date={TODAY}&top_n=5', timeout=120)
    check(page, '重新生成排名', 'POST', '/api/ranking/regenerate', {'selection_date': TODAY, 'force_recalculate': False}, timeout=600)

    # ========== 5. 趋势动物 ==========
    page = '趋势动物'
    print(f'\n【{page}】', flush=True)
    check(page, '趋势状态', 'GET', '/api/trend/status')
    check(page, '趋势搜索', 'GET', '/api/trend/search?keyword=000001')
    check(page, '趋势快照', 'GET', '/api/trend/snapshot')
    check(page, '趋势绘图', 'GET', '/api/trend/plot?code=000001')
    check(page, '信号股票', 'GET', '/api/trend/signal-stocks')
    check(page, '趋势配置', 'GET', '/api/trend/config')
    check(page, '选股日期列表', 'GET', '/api/trend/selection-dates')
    check(page, '每日报告', 'GET', '/api/trend/daily-report')

    # ========== 6. 市场温度计 ==========
    page = '市场温度计'
    print(f'\n【{page}】', flush=True)
    check(page, '最新温度', 'GET', '/api/market-temperature/latest')
    check(page, '温度查询', 'GET', f'/api/market-temperature/query?date={TODAY}')
    check(page, '温度趋势', 'GET', '/api/market-temperature/trend?days=10')
    check(page, '仓位比例', 'GET', '/api/market-temperature/position-ratio')
    check(page, '计算温度', 'POST', '/api/market-temperature/calculate', {'date': TODAY}, timeout=180)

    # ========== 7. 资金流向选股 ==========
    page = '资金流向'
    print(f'\n【{page}】', flush=True)
    check(page, '持续流入选股', 'POST', '/api/money-flow/select', {'days': 10, 'min_net_amount': 0, 'end_date': TODAY.replace('-', '')}, timeout=180)

    # ========== 8. 策略回测 ==========
    page = '策略回测'
    print(f'\n【{page}】', flush=True)
    check(page, '回测约束列表', 'GET', '/api/backtest/constraints')
    check(page, '回测约束详情', 'GET', '/api/backtest/constraint')
    check(page, '策略运行器状态', 'GET', '/api/strategy/status')
    check(page, '初始化策略运行器', 'POST', '/api/strategy/initialize', timeout=300)
    check(page, '批量回测(1个任务)', 'POST', '/api/strategy/run-batch',
          {'tasks': [{'selection_strategy': 'limit_up', 'timing_strategy': 'support'}]}, timeout=600)

    # ========== 9. 回测历史 ==========
    page = '回测历史'
    print(f'\n【{page}】', flush=True)
    check(page, '任务历史', 'GET', '/api/task/history')
    check(page, '最近任务', 'GET', '/api/task/last')
    check(page, '查看报告#1', 'GET', '/api/report/1')

    # ========== 10. 数据管理 ==========
    page = '数据管理'
    print(f'\n【{page}】', flush=True)
    check(page, '数据状态', 'GET', '/api/data/status')
    check(page, '数据检查', 'GET', '/api/data/check', timeout=120)
    check(page, '表信息', 'GET', '/api/data/tables/info')
    check(page, '表统计', 'GET', '/api/data/tables/stats', timeout=120)
    check(page, '更新状态', 'GET', '/api/update/status')
    check(page, '最后更新时间', 'GET', '/api/data/update/last-update-time')
    check(page, '初始化配置', 'GET', '/api/data/init/config')
    check(page, '更新配置', 'GET', '/api/data/update/config')
    skip(page, '触发全量更新', 'POST', '/api/data/update/start', '重量级写操作，避免重复下载数据')

    # ========== 11. 策略管理 ==========
    page = '策略管理'
    print(f'\n【{page}】', flush=True)
    check(page, '策略列表', 'GET', '/api/strategies')
    if strategy_key:
        check(page, '策略详情', 'GET', f'/api/strategies/{strategy_key}')
    check(page, '策略配置检查', 'GET', '/api/strategy/has-config')
    check(page, '系统配置', 'GET', '/api/config')

    # ========== 12. 风控模块 ==========
    page = '风控模块'
    print(f'\n【{page}】', flush=True)
    check(page, '风控状态', 'GET', '/api/risk/status')
    check(page, '风控历史', 'GET', '/api/risk/history')
    check(page, '风控配置', 'GET', '/api/risk/config')

    # ========== 13. 模拟交易 ==========
    page = '模拟交易'
    print(f'\n【{page}】', flush=True)
    check(page, '持仓组合', 'GET', '/api/portfolio')
    check(page, '交易信号', 'GET', '/api/signals')
    check(page, '股票池', 'GET', '/api/stock-pool')
    check(page, '卖出(空参数探测)', 'POST', '/api/portfolio/sell', {}, expect_key='__none__')
    check(page, '执行信号(不存在ID探测)', 'POST', '/api/signals/__nonexist__/execute', {}, expect_key='__none__')

    # ========== 汇总 ==========
    print('\n' + '=' * 100)
    print('【测试结果汇总】')
    passed = [r for r in RESULTS if r[5] is True]
    failed = [r for r in RESULTS if r[5] is False]
    skipped = [r for r in RESULTS if r[5] is None]
    cur = None
    for r in RESULTS:
        if r[0] != cur:
            cur = r[0]
            print(f'\n  [{cur}]')
        mark = 'PASS' if r[5] is True else ('SKIP' if r[5] is None else 'FAIL')
        print(f'    {mark}  {r[1]}')
    print(f'\n总计: {len(passed)} 通过, {len(failed)} 失败, {len(skipped)} 跳过')
    if failed:
        print('\n失败明细:')
        for r in failed:
            print(f'  - [{r[0]}] {r[1]} {r[2]} {r[3]} -> HTTP {r[4]}: {r[7]}')
    # 机器可读结果
    with open('e2e_result.json', 'w', encoding='utf-8') as f:
        json.dump([{'page': r[0], 'name': r[1], 'method': r[2], 'path': r[3],
                    'status': str(r[4]), 'ok': r[5], 'elapsed': round(r[6], 1), 'note': r[7]}
                   for r in RESULTS], f, ensure_ascii=False, indent=2)
    print('\n详细结果已保存: e2e_result.json')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
