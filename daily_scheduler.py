# -*- coding: utf-8 -*-
"""
每日定时任务调度器

每天定时（默认 17:00，可在 config/config.yaml 的 schedule.time 修改）自动执行：
  1. 数据增量更新（K线/资金流向/市值，复用 DataCollectionService 完整更新流程）
  2. 全策略选股（复用与 Web 端完全相同的策略注册表和分析逻辑）
  3. 保存选股结果到 stock_selection_record 表（后续可在 Web 端做排名/狩猎场）

特性：
  - 自动跳过非交易日（周末/节假日不执行）
  - 选股结果按当日日期保存，Web 端「选股排名/狩猎场」可直接使用
  - 日志输出到 logs/daily_scheduler.log

用法：
  python daily_scheduler.py            # 启动常驻调度（每天定时执行）
  python daily_scheduler.py --now      # 立即执行一次（仍检查是否交易日）
  python daily_scheduler.py --test     # 仅测试选股流程（不更新数据、不保存结果）
"""
import sys
import os
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path

# 确保项目根目录在路径中
sys.path.insert(0, str(Path(__file__).parent))

import yaml

# ==================== 日志配置 ====================
LOG_FILE = Path('logs') / 'daily_scheduler.log'
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('daily_scheduler')

# 屏蔽部分嘈杂的第三方日志
for noisy in ('urllib3', 'requests', 'werkzeug'):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def load_schedule_time() -> str:
    """从配置文件读取定时时间，默认 17:00"""
    try:
        with open('config/config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        return str(config.get('schedule', {}).get('time', '17:00'))
    except Exception:
        return '17:00'


def run_data_update() -> bool:
    """执行数据增量更新（同步），复用 DataCollectionService 完整流程

    Returns:
        bool: 更新是否成功完成
    """
    from utils.data_collection_service import DataCollectionService

    logger.info('[1/3] 开始数据增量更新...')
    try:
        service = DataCollectionService('data')
        task_id = f"SCHEDULED_UPDATE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        # 直接调用内部方法同步执行（start_update 是异步线程版，不适合脚本）
        service._run_update(task_id, None)  # None = 全部类型（K线/资金流/市值）
        status = service.update_status.get('status')
        if status == 'completed':
            stats = service.update_status.get('totalStats', {})
            logger.info(f"[1/3] 数据更新完成: {stats}")
            return True
        else:
            logger.warning(f"[1/3] 数据更新结束，状态: {status}，继续执行选股")
            return False
    except Exception as e:
        logger.error(f"[1/3] 数据更新异常: {e}，继续执行选股", exc_info=True)
        return False


def run_selection(end_date: str) -> list:
    """执行全策略选股（与 Web 端 OR 逻辑一致）

    Args:
        end_date: 选股截止日期（YYYY-MM-DD）

    Returns:
        list: 信号列表 [{'code', 'name', 'signals', 'strategies'}, ...]
    """
    from utils.global_db import get_global_db
    from strategy.strategy_registry import get_registry

    logger.info('[2/3] 开始全策略选股...')
    db = get_global_db()
    registry = get_registry("config/strategy_params.yaml")
    registry.auto_register_from_directory("strategy")  # 与 web_server 启动时一致，注册全部策略

    # 加载策略中文名称映射
    display_names = {}
    try:
        with open('config/strategy_params.yaml', 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        for sname, scfg in (cfg.get('strategies', {}) or {}).items():
            display_names[sname] = scfg.get('display_name', sname)
    except Exception:
        pass

    # 加载股票数据（与 Web 端相同的过滤条件）
    stock_codes = db.list_all_stocks()
    stock_names = db.get_all_stock_names()
    stock_data = {}
    for code in stock_codes:
        try:
            df = db.read_stock(code, end_date=end_date)
            if not df.empty and len(df) >= 30:
                df = df.sort_values('date', ascending=False)
                stock_data[code] = (stock_names.get(code, '未知'), df)
        except Exception:
            continue
    logger.info(f"[2/3] 加载 {len(stock_data)} 只股票K线数据，截止 {end_date}")

    # 逐策略执行
    all_signals = []
    for strategy_name in registry.strategies.keys():
        strategy = registry.get_strategy(strategy_name)
        if not strategy:
            continue
        display_name = display_names.get(strategy_name, strategy_name)
        count = 0
        for code, (name, df) in stock_data.items():
            try:
                result = strategy.analyze_stock(code, name, df)
                if result:
                    all_signals.append({
                        'code': result['code'],
                        'name': result.get('name', name),
                        'signals': result['signals'],
                        'strategies': [display_name]
                    })
                    count += 1
            except Exception:
                continue
        if count > 0:
            logger.info(f"[2/3]   {display_name}: 选中 {count} 只")

    # 合并同一股票被多个策略选中的情况（strategies 合并）
    merged = {}
    for sig in all_signals:
        code = sig['code']
        if code not in merged:
            merged[code] = sig
        else:
            existing = merged[code]
            for s in sig['strategies']:
                if s not in existing['strategies']:
                    existing['strategies'].append(s)
            existing['signals'].extend(sig['signals'])

    result = list(merged.values())
    logger.info(f"[2/3] 选股完成: 共 {len(result)} 只股票（去重后）")
    return result


def save_results(signals: list, end_date: str):
    """保存选股结果到 stock_selection_record"""
    from utils.selection_record_manager import SelectionRecordManager

    logger.info('[3/3] 保存选股结果...')
    if not signals:
        logger.info('[3/3] 无选股结果，跳过保存')
        return

    manager = SelectionRecordManager()
    strategy_names = []
    for sig in signals:
        for s in sig.get('strategies', []):
            if s not in strategy_names:
                strategy_names.append(s)

    result = manager.save_selection_result(
        strategy_names=strategy_names,
        signals=signals,
        selection_time=datetime.now(),
        end_date=end_date
    )
    logger.info(f"[3/3] 保存完成: {result}")


def daily_task():
    """每日任务主流程：交易日检查 → 更新 → 选股 → 保存"""
    today = datetime.now().strftime('%Y-%m-%d')
    logger.info("=" * 60)
    logger.info(f"每日任务触发: {today}")

    # 交易日检查（周末/节假日跳过）
    try:
        from utils.trade_date_utils import is_trading_day
        if not is_trading_day(today):
            logger.info(f"{today} 非交易日，跳过本次任务")
            return
    except Exception as e:
        logger.warning(f"交易日检查失败: {e}，按交易日处理")

    start = datetime.now()
    run_data_update()
    signals = run_selection(today)
    save_results(signals, today)
    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"每日任务完成，总耗时 {elapsed/60:.1f} 分钟")
    logger.info("=" * 60)


def test_selection():
    """测试模式：只跑选股流程，不更新数据、不保存结果"""
    from utils.global_db import get_global_db
    db = get_global_db()
    latest = db.get_latest_trading_date()
    logger.info(f"测试模式：使用最新交易日 {latest} 的数据（不更新、不保存）")
    signals = run_selection(latest)
    for sig in signals[:20]:
        print(f"  {sig['code']} {sig['name']} <- {'+'.join(sig['strategies'])}")
    logger.info(f"测试完成: 共 {len(signals)} 只（未保存）")


def main():
    parser = argparse.ArgumentParser(description='KHunter 每日定时任务调度器')
    parser.add_argument('--now', action='store_true', help='立即执行一次每日任务')
    parser.add_argument('--test', action='store_true', help='仅测试选股流程（不更新不保存）')
    args = parser.parse_args()

    if args.test:
        test_selection()
        return
    if args.now:
        daily_task()
        return

    # 常驻调度模式
    try:
        import schedule
    except ImportError:
        logger.error("缺少 schedule 库: pip install schedule")
        sys.exit(1)

    schedule_time = load_schedule_time()
    logger.info("=" * 60)
    logger.info(f"⏰ KHunter 每日调度器已启动")
    logger.info(f"   执行时间: 每天 {schedule_time}（自动跳过非交易日）")
    logger.info(f"   日志文件: {LOG_FILE}")
    logger.info("=" * 60)

    schedule.every().day.at(schedule_time).do(daily_task)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == '__main__':
    main()
