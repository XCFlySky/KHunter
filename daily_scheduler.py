# -*- coding: utf-8 -*-
"""
每日定时任务调度器

每天定时（默认 17:00，可在 config/config.yaml 的 schedule.time 修改）自动执行：
  1. 数据增量更新（K线/资金流向/市值，复用 DataCollectionService 完整更新流程）
  2. 全策略选股（复用与 Web 端完全相同的策略注册表和分析逻辑）
  3. 保存选股结果到 stock_selection_record 表（后续可在 Web 端做排名/狩猎场）
  4. 模拟盘每日结算（trading/sim_account.py：成交昨日订单→卖出检查→生成买单→记净值）

特性：
  - 自动跳过非交易日（周末/节假日不执行）
  - 选股结果按当日日期保存，Web 端「选股排名/狩猎场」可直接使用
  - 模拟盘账户独立存储在 data/sim_account.db，支持收益率/回撤/胜率等指标统计
  - 日志输出到 logs/daily_scheduler.log

用法：
  python daily_scheduler.py            # 启动常驻调度（每天定时执行）
  python daily_scheduler.py --now      # 立即执行一次（仍检查是否交易日）
  python daily_scheduler.py --test     # 仅测试选股流程（不更新数据、不保存结果）
  python daily_scheduler.py --sim      # 仅对最新交易日跑一次模拟盘结算（用当日已保存选股结果）
  python daily_scheduler.py --notify   # 仅发送一条企业微信测试消息（验证 webhook 配置）
  python daily_scheduler.py --notify-alert  # 发送一条模拟的卖出信号提醒（虚构数据，验证提醒样式）
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

    logger.info('[1/5] 开始数据增量更新...')
    try:
        service = DataCollectionService('data')
        task_id = f"SCHEDULED_UPDATE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        # 直接调用内部方法同步执行（start_update 是异步线程版，不适合脚本）
        service._run_update(task_id, None)  # None = 全部类型（K线/资金流/市值）
        status = service.update_status.get('status')
        if status == 'completed':
            stats = service.update_status.get('totalStats', {})
            logger.info(f"[1/5] 数据更新完成: {stats}")
            return True
        else:
            logger.warning(f"[1/5] 数据更新结束，状态: {status}，继续执行选股")
            return False
    except Exception as e:
        logger.error(f"[1/5] 数据更新异常: {e}，继续执行选股", exc_info=True)
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

    logger.info('[2/5] 开始全策略选股...')
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
    # 限制每只股票加载的K线条数，避免全量历史数据一次性载入导致内存暴涨(OOM)
    # 策略最多需要约70条，250条≈1年交易日，与 web_server 的 SELECTION_KLINE_LIMIT 保持一致
    KLINE_LIMIT = 250
    stock_codes = db.list_all_stocks()
    stock_names = db.get_all_stock_names()
    stock_data = {}
    for code in stock_codes:
        try:
            df = db.read_stock(code, end_date=end_date, limit=KLINE_LIMIT)
            if not df.empty and len(df) >= 30:
                df = df.sort_values('date', ascending=False)
                stock_data[code] = (stock_names.get(code, '未知'), df)
        except Exception:
            continue
    logger.info(f"[2/5] 加载 {len(stock_data)} 只股票K线数据，截止 {end_date}")

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
            logger.info(f"[2/5]   {display_name}: 选中 {count} 只")

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
    logger.info(f"[2/5] 选股完成: 共 {len(result)} 只股票（去重后）")
    return result


def save_results(signals: list, end_date: str):
    """保存选股结果到 stock_selection_record"""
    from utils.selection_record_manager import SelectionRecordManager

    logger.info('[3/5] 保存选股结果...')
    if not signals:
        logger.info('[3/5] 无选股结果，跳过保存')
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
    logger.info(f"[3/5] 保存完成: {result}")


def run_sim_account(end_date: str, signals: list) -> dict:
    """模拟盘每日结算（成交昨日订单 → 卖出检查 → 生成买单 → 记录净值）

    失败不影响主流程，仅记录日志。

    Args:
        end_date: 交易日（YYYY-MM-DD）
        signals: 当日选股结果（run_selection 的返回）

    Returns:
        dict: 结算摘要；失败返回 None
    """
    logger.info('[4/5] 模拟盘每日结算...')
    try:
        from trading.sim_account import SimAccount
        sim = SimAccount()
        result = sim.run_daily(end_date, signals)
        logger.info(f"[4/5] 模拟盘结算完成: {result}")
        return result
    except Exception as e:
        logger.error(f"[4/5] 模拟盘结算异常: {e}", exc_info=True)
        return None


def run_daily_notify(end_date: str, signals: list, sim_summary: dict = None) -> bool:
    """企业微信群推送每日选股结果与模拟盘结算摘要

    失败不影响主流程，仅记录日志。
    """
    logger.info('[5/5] 企业微信推送...')
    try:
        from utils.wechat_notifier import send_daily_notification, send_sell_alert
        # 卖出信号（止损/止盈等）时效性最强，单独即时推送一条
        sell_alerts = (sim_summary or {}).get('sell_alerts') or []
        if sell_alerts:
            alert_ok = send_sell_alert(end_date, sell_alerts)
            logger.info(f"[5/5] 卖出信号提醒（{len(sell_alerts)} 只）{'已推送' if alert_ok else '推送失败'}")
        ok = send_daily_notification(end_date, signals, sim_summary,
                                     web_url='http://47.254.123.6:5001')
        logger.info(f"[5/5] 企业微信推送{'成功' if ok else '未发送（未配置或失败）'}")
        return ok
    except Exception as e:
        logger.error(f"[5/5] 企业微信推送异常: {e}", exc_info=True)
        return False


def daily_task():
    """每日任务主流程：交易日检查 → 更新 → 选股 → 保存 → 模拟盘结算 → 企业微信推送"""
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
    sim_summary = run_sim_account(today, signals)
    run_daily_notify(today, signals, sim_summary)
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


def test_sim():
    """模拟盘测试模式：对最新交易日重新选股（不保存）并执行一次模拟盘结算"""
    from utils.global_db import get_global_db
    db = get_global_db()
    latest = db.get_latest_trading_date()
    logger.info(f"模拟盘测试模式：使用最新交易日 {latest}（不更新数据、不保存选股结果）")
    signals = run_selection(latest)
    run_sim_account(latest, signals)


def test_notify():
    """通知测试模式：发送一条企业微信测试消息（验证 webhook 配置）"""
    from utils.wechat_notifier import send_markdown, load_webhook
    webhook = load_webhook()
    if not webhook:
        logger.error("未找到 webhook 配置（config/notify.local.yaml 或环境变量 KHUNTER_WECHAT_WEBHOOK）")
        return
    today = datetime.now().strftime('%Y-%m-%d')
    ok = send_markdown(
        f"## ✅ KHunter 推送测试\n"
        f"> 每日选股推送通道已打通（{today}）\n"
        f"> 每个交易日收盘后将自动推送选股结果与模拟盘结算摘要"
    )
    logger.info(f"测试消息发送{'成功' if ok else '失败'}")


def test_notify_alert():
    """卖出提醒测试模式：构造模拟止损/止盈信号，发送一条测试提醒"""
    from utils.wechat_notifier import send_sell_alert, load_webhook
    if not load_webhook():
        logger.error("未找到 webhook 配置（config/notify.local.yaml 或环境变量 KHUNTER_WECHAT_WEBHOOK）")
        return
    today = datetime.now().strftime('%Y-%m-%d')
    mock_alerts = [
        {'code': '600519', 'name': '贵州茅台', 'reason': '止损 (收益率 -5.32%)',
         'buy_price': 1478.00, 'current_price': 1399.37, 'return_rate': -0.0532,
         'strategy': '金三角策略'},
        {'code': '000858', 'name': '五粮液', 'reason': '止盈 (收益率 +15.41%)',
         'buy_price': 128.50, 'current_price': 148.30, 'return_rate': 0.1541,
         'strategy': '仙人指路策略'},
    ]
    ok = send_sell_alert(today, mock_alerts)
    logger.info(f"模拟卖出提醒发送{'成功' if ok else '失败'}（内容为虚构测试数据）")


def main():
    parser = argparse.ArgumentParser(description='KHunter 每日定时任务调度器')
    parser.add_argument('--now', action='store_true', help='立即执行一次每日任务')
    parser.add_argument('--test', action='store_true', help='仅测试选股流程（不更新不保存）')
    parser.add_argument('--sim', action='store_true', help='仅对最新交易日跑一次模拟盘结算')
    parser.add_argument('--notify', action='store_true', help='仅发送一条企业微信测试消息')
    parser.add_argument('--notify-alert', action='store_true', help='发送一条模拟的卖出信号提醒（虚构数据）')
    args = parser.parse_args()

    if args.test:
        test_selection()
        return
    if args.sim:
        test_sim()
        return
    if args.notify:
        test_notify()
        return
    if args.notify_alert:
        test_notify_alert()
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
