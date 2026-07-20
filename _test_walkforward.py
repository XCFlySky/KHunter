# -*- coding: utf-8 -*-
"""Walk-Forward 验证：Y1/Y2 年度分段回测 新/旧金三角策略
Y3 已有结果（新 25.95%/156笔, 旧 9.68%/274笔），本脚本补 Y1、Y2 共 4 组。
"""
import sys
sys.path.insert(0, '.')
import yaml
import shutil
import logging
import traceback
logging.basicConfig(level=logging.WARNING)

YAML_PATH = 'config/strategy_params.yaml'
BAK_PATH = 'config/strategy_params.yaml.bak_wf'

BASE = {
    'long_period': 20, 'mid_period': 10, 'short_period': 5, 'super_long_period': 60,
    'lookback_days': 30, 'strategy_weight': 50, 'volume_ma_days': 5,
    'limit_up_gain': 0.095, 'ma5_rising_tolerance': 0.001,
    'ma_long_slope_days': 5, 'ma_super_long_slope_days': 10,
    'c_cross_min_gain': 0.01, 'ac_interval': 6,
}
NEW_PARAMS = dict(BASE, c_cross_min_volume_ratio=1.5, c_point_valid_days=2, exclude_xd=True,
                  min_turnover_rate=3.0, exclude_consecutive_limit_up=True,
                  require_ma5_rising=True, max_rise_from_low=0.35,
                  ma_long_min_slope=-0.02, ma_super_long_min_slope=-0.05,
                  require_price_above_ma_long=True)
OLD_PARAMS = dict(BASE, c_cross_min_volume_ratio=1.1, c_point_valid_days=1, exclude_xd=False,
                  min_turnover_rate=0, exclude_consecutive_limit_up=False,
                  require_ma5_rising=False, max_rise_from_low=10.0,
                  ma_long_min_slope=-1, ma_super_long_min_slope=-1,
                  require_price_above_ma_long=False)

PERIODS = [
    ('Y1 2023-07~2024-07', '2023-07-18', '2024-07-17'),
    ('Y2 2024-07~2025-07', '2024-07-18', '2025-07-17'),
]
VARIANTS = [('新策略', NEW_PARAMS), ('旧策略', OLD_PARAMS)]

KEYS = ['total_return', 'win_rate', 'max_drawdown', 'sharpe_ratio',
        'total_trades', 'profit_factor', 'avg_return', 'avg_hold_days']


def set_gt_params(params):
    with open(YAML_PATH, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    cfg['strategies']['GoldenTriangleStrategy']['params'] = params
    with open(YAML_PATH, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def run_one(start, end):
    from trading.backtest_engine import BacktestEngine
    cfg = {
        'start_date': start, 'end_date': end,
        'initial_capital': 300000, 'buy_amount': 100000,
        'score_threshold': 0, 'max_daily_buys': 5, 'max_buy_count_per_stock': 3,
        'take_profit': 0.21, 'stop_loss': -0.07, 'hold_period': 10,
        'timing_strategy': 'support',
    }
    engine = BacktestEngine()
    return engine.run_backtest('GoldenTriangleStrategy', cfg)


def main():
    shutil.copy(YAML_PATH, BAK_PATH)
    results = {}
    try:
        for pname, start, end in PERIODS:
            for vname, params in VARIANTS:
                tag = f'{pname} {vname}'
                print(f'\n===== 开始回测: {tag} =====', flush=True)
                try:
                    set_gt_params(params)
                    r = run_one(start, end)
                    perf = r.get('performance', r)
                    results[tag] = perf
                    line = '  ' + ' | '.join(
                        f'{k}={perf[k]:.2f}' for k in KEYS if k in perf)
                    print(line, flush=True)
                except Exception as e:
                    print(f'  [ERROR] {tag}: {e}', flush=True)
                    traceback.print_exc()
    finally:
        shutil.move(BAK_PATH, YAML_PATH)
        print('\nYAML 已恢复生产参数', flush=True)

    print('\n\n========== Walk-Forward 汇总 ==========', flush=True)
    header = f'{"期间":<22}{"策略":<8}{"收益率":>9}{"胜率":>7}{"回撤":>8}{"夏普":>7}{"交易数":>7}{"盈利因子":>9}'
    print(header, flush=True)
    print('-' * 80, flush=True)
    for pname, _, _ in PERIODS:
        for vname, _ in VARIANTS:
            perf = results.get(f'{pname} {vname}')
            if not perf:
                continue
            print(f'{pname:<22}{vname:<8}{perf.get("total_return", 0):>+8.2f}%{perf.get("win_rate", 0):>6.1f}%'
                  f'{perf.get("max_drawdown", 0):>7.2f}%{perf.get("sharpe_ratio", 0):>7.2f}'
                  f'{perf.get("total_trades", 0):>7}{perf.get("profit_factor", 0):>9.2f}', flush=True)
    print('-' * 80, flush=True)
    print('参考 Y3 2025-07~2026-07: 新策略 +25.95%/81.4%/DD7.69/Sharpe1.42/156笔/PF1.75 | 旧策略 +9.68%/77.4%/DD16.99/Sharpe0.44/274笔/PF1.37', flush=True)


if __name__ == '__main__':
    main()
