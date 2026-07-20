# -*- coding: utf-8 -*-
"""Fix OOM in run_selection_date_range: eliminate 3x memory amplification.

1) preprocess dates in-place (no full copy of 5221 DataFrames)
2) per-day: truncate per stock on the fly instead of materializing a full-market dict
"""
import py_compile
import sys

PATH = '/opt/khunter/web_server.py'
src = open(PATH, encoding='utf-8').read()

edits = []

old_a = """        normalized_data = {}
        for code, (name, df) in stock_data.items():
            try:
                df = df.copy()
                df['date'] = pd.to_datetime(df['date'])
                normalized_data[code] = (name, df)
            except Exception:
                continue"""
new_a = """        for code in list(stock_data.keys()):
            try:
                stock_data[code][1]['date'] = pd.to_datetime(stock_data[code][1]['date'])
            except Exception:
                del stock_data[code]"""
edits.append(('A-preprocess', old_a, new_a))

old_b = """            # 按当日截断每只股票的数据（仅保留 <= day 的数据）
            day_stock_data = {}
            for code, (name, df) in normalized_data.items():
                day_df = df[df['date'] <= day_ts]
                if len(day_df) >= 30:
                    day_stock_data[code] = (name, day_df)

            day_result = {}
            day_diag = {}"""
new_b = """            day_result = {}
            day_diag = {}
            analyzed_count = 0  # 当日满足最小数据量、实际参与分析的股票数"""
edits.append(('B-dayloop-init', old_b, new_b))

old_c = """            for strategy_name, strategy in strategies_to_execute:
                display_name = strategy_display_names.get(strategy_name, strategy_name)
                signals = []
                rejected = [] if include_diagnostics else None

                for code, (name, df) in day_stock_data.items():
                    try:
                        result = strategy.analyze_stock(code, name, df)
                        if result:
                            signals.append({
                                'code': result['code'],
                                'name': result.get('name', stock_names.get(code, '未知')),
                                'signals': result['signals'],
                                'strategy_display_name': display_name
                            })
                            # 并集合并（后处理的日期覆盖先处理的，最终保留最新日期）
                            merged.setdefault(strategy_name, {})[code] = signals[-1]
                            merged_dates.setdefault((strategy_name, code), []).append(day)
                        elif rejected is not None:
                            rejected.append({
                                'code': code,
                                'name': name,
                                'reason': strategy.get_last_reject_reason()
                            })
                    except Exception:
                        pass

                day_result[display_name] = signals"""
new_c = """            # 各策略当日结果容器
            signals_map = {sname: [] for sname, _ in strategies_to_execute}
            rejected_map = {sname: ([] if include_diagnostics else None) for sname, _ in strategies_to_execute}

            # 逐只股票截断当日数据并执行各策略（不缓存全市场截断副本，避免内存峰值）
            for code, (name, df) in stock_data.items():
                day_df = df[df['date'] <= day_ts]
                if len(day_df) < 30:
                    continue
                analyzed_count += 1
                for strategy_name, strategy in strategies_to_execute:
                    display_name = strategy_display_names.get(strategy_name, strategy_name)
                    signals = signals_map[strategy_name]
                    rejected = rejected_map[strategy_name]
                    try:
                        result = strategy.analyze_stock(code, name, day_df)
                        if result:
                            signal_entry = {
                                'code': result['code'],
                                'name': result.get('name', stock_names.get(code, '未知')),
                                'signals': result['signals'],
                                'strategy_display_name': display_name
                            }
                            signals.append(signal_entry)
                            # 并集合并（后处理的日期覆盖先处理的，最终保留最新日期）
                            merged.setdefault(strategy_name, {})[code] = signal_entry
                            merged_dates.setdefault((strategy_name, code), []).append(day)
                        elif rejected is not None:
                            rejected.append({
                                'code': code,
                                'name': name,
                                'reason': strategy.get_last_reject_reason()
                            })
                    except Exception:
                        pass

            for strategy_name, strategy in strategies_to_execute:
                display_name = strategy_display_names.get(strategy_name, strategy_name)
                signals = signals_map[strategy_name]
                rejected = rejected_map[strategy_name]
                day_result[display_name] = signals"""
edits.append(('C-strategy-loop', old_c, new_c))

old_d = "'total_analyzed': len(day_stock_data),"
new_d = "'total_analyzed': analyzed_count,"
edits.append(('D-total-analyzed', old_d, new_d))

for name, old, new in edits:
    cnt = src.count(old)
    if cnt != 1:
        print('ABORT: edit %s matched %d times (expected 1)' % (name, cnt))
        sys.exit(1)
    src = src.replace(old, new, 1)
    print('edit %s applied' % name)

open(PATH, 'w', encoding='utf-8').write(src)
py_compile.compile(PATH, doraise=True)
print('py_compile OK')

for bad in ['normalized_data', 'day_stock_data']:
    for i, line in enumerate(open(PATH, encoding='utf-8'), 1):
        if bad in line:
            print('WARNING: stale ref %s at line %d: %s' % (bad, i, line.rstrip()))
print('done')
