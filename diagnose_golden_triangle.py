# -*- coding: utf-8 -*-
"""
金三角策略选股诊断脚本
复现 web_server 的选股流程（end_date=2026-07-17），逐股记录被拒原因，
输出：过滤漏斗统计 + 逐股明细 CSV + 选中股票清单。
"""
import sys
import io
import json
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd

from utils.global_db import get_global_db
from strategy.strategy_registry import get_registry

END_DATE = '2026-07-17'
STRATEGY_NAME = 'GoldenTriangleStrategy'
OUT_DIR = Path('reports')


def main():
    db_manager = get_global_db()
    registry = get_registry("config/strategy_params.yaml")
    if not registry.strategies:
        registry.auto_register_from_directory("strategy")
    strategy = registry.get_strategy(STRATEGY_NAME)
    if strategy is None:
        print(f"策略未找到: {STRATEGY_NAME}")
        return

    print("=" * 70)
    print(f"策略参数（当前生效值）:")
    for k, v in strategy.params.items():
        print(f"  {k} = {v}")
    print("=" * 70)

    stock_codes = db_manager.list_all_stocks()
    stock_names = db_manager.get_all_stock_names()
    print(f"数据库股票总数: {len(stock_codes)}")

    stock_data = {}
    skip_count = 0
    for code in stock_codes:
        try:
            df = db_manager.read_stock(code, end_date=END_DATE)
            if not df.empty and len(df) >= 30:
                df = df.sort_values('date', ascending=False)
                stock_data[code] = (stock_names.get(code, '未知'), df)
        except Exception:
            skip_count += 1
    print(f"成功加载: {len(stock_data)} 只，跳过: {skip_count} 只")
    print("=" * 70)

    selected = []
    rejected = []
    error_count = 0

    for idx, (code, (name, df)) in enumerate(stock_data.items()):
        try:
            result = strategy.analyze_stock(code, name, df)
            if result:
                sig = result['signals'][0]
                selected.append({
                    'code': code,
                    'name': result.get('name', name),
                    'date': sig.get('date'),
                    'key_date': sig.get('key_date'),
                    'key_date_type': sig.get('key_date_type'),
                    'price': sig.get('price'),
                    'volume_ratio': sig.get('volume_ratio'),
                    'turnover_rate': sig.get('turnover_rate'),
                    'signal_strength': sig.get('signal_strength'),
                    'reason': sig.get('reason'),
                })
            else:
                rejected.append({
                    'code': code,
                    'name': name,
                    'reason': strategy.get_last_reject_reason(),
                })
        except Exception as e:
            error_count += 1
            rejected.append({'code': code, 'name': name, 'reason': f'分析异常: {e}'})
        if (idx + 1) % 1000 == 0:
            print(f"进度 [{idx + 1}/{len(stock_data)}] 已选中 {len(selected)} 只")

    print("=" * 70)
    print(f"分析完成：共 {len(stock_data)} 只，选中 {len(selected)} 只，"
          f"未选中 {len(rejected) - error_count} 只，异常 {error_count} 只")
    print("=" * 70)

    # ---- 过滤漏斗统计（按首条拒绝原因归类）----
    def categorize(reason: str) -> str:
        cat = reason.split('（')[0].split('，')[0]
        import re
        cat = re.sub(r'\d+\.?\d*', 'N', cat)
        return cat

    counter = Counter(categorize(r['reason']) for r in rejected)
    print("\n【过滤漏斗 - 按拒绝原因统计】（股票按首条未通过条件归类）")
    for reason, cnt in counter.most_common():
        pct = cnt / len(stock_data) * 100
        print(f"  {cnt:>5} 只 ({pct:5.1f}%)  {reason}")

    # ---- 保存明细 ----
    OUT_DIR.mkdir(exist_ok=True)
    rej_df = pd.DataFrame(rejected)
    rej_path = OUT_DIR / 'golden_triangle_rejected_20260717.csv'
    rej_df.to_csv(rej_path, index=False, encoding='utf-8-sig')

    sel_df = pd.DataFrame(selected)
    sel_path = OUT_DIR / 'golden_triangle_selected_20260717.csv'
    sel_df.to_csv(sel_path, index=False, encoding='utf-8-sig')

    summary = {
        'end_date': END_DATE,
        'strategy': STRATEGY_NAME,
        'params': {k: (v if not isinstance(v, float) else round(v, 6)) for k, v in strategy.params.items()},
        'total_analyzed': len(stock_data),
        'selected': len(selected),
        'rejected': len(rejected) - error_count,
        'errors': error_count,
        'reason_stats': dict(counter.most_common()),
    }
    sum_path = OUT_DIR / 'golden_triangle_diagnosis_20260717.json'
    with open(sum_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n明细已保存:")
    print(f"  未选中明细: {rej_path}")
    print(f"  选中清单:   {sel_path}")
    print(f"  统计摘要:   {sum_path}")

    if selected:
        print("\n【选中股票】")
        for s in selected:
            print(f"  {s['code']} {s['name']} | {s['key_date_type']} {s['key_date']} | "
                  f"价 {s['price']} | 量比 {s['volume_ratio']} | 强度 {s['signal_strength']}")
            print(f"      理由: {s['reason']}")
    else:
        print("\n【选中股票】无（0 只通过全部条件）")

        # 额外诊断：找出“最接近通过”的股票 —— 仅被最后一道多头节奏/均线条件挡掉的
        near_miss = [r for r in rejected if '均线非多头排列' in r['reason']]
        print(f"\n其中通过 C 点形态/量能/趋势全部校验、仅因最新一日均线非多头排列被拒的: {len(near_miss)} 只")
        for r in near_miss[:20]:
            print(f"  {r['code']} {r['name']}  {r['reason']}")


if __name__ == '__main__':
    main()
