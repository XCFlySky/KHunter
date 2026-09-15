# -*- coding: utf-8 -*-
"""
模拟盘账户模块（paper trading）

每日结算流程（由 daily_scheduler 在选股完成后调用）：
  1. 成交昨日挂出的待执行订单（以当日开盘价成交，先卖后买，停牌顺延）
  2. 对持仓检查卖出规则（止损/止盈/移动止损/持仓到期），生成次日执行的卖单
  3. 从当日选股结果生成买单（评分排序、等权分配、单票仓位上限），次日开盘价成交
  4. 以当日收盘价记录账户净值（NAV）

特点：
  - 信号当日生成、次交易日开盘成交，避免「用今日收盘信号买今日收盘价」的前视偏差
  - 幂等：同一交易日重复执行不会重复成交（sim_nav 已有当日记录则跳过）
  - 与 PTrade 实盘（run_mode=auto）完全隔离，使用独立 SQLite 库 data/sim_account.db

数据表（data/sim_account.db，运行时数据，不进 Git）：
  sim_meta       账户元信息（初始资金等）
  sim_positions  当前持仓
  sim_orders     待执行订单（次日开盘成交）
  sim_trades     已成交明细（卖单含单笔盈亏 profit）
  sim_nav        每日净值（现金/市值/总资产/日收益/累计收益）
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ==================== 默认参数（可被 config/config.yaml 的 sim_account 节覆盖） ====================
DEFAULT_CONFIG = {
    'initial_capital': 300000,     # 初始资金（与现有 Web 持仓默认值一致）
    'max_positions': 5,            # 最大持仓数
    'stop_loss': 0.05,             # 止损：跌破买入价 5%
    'take_profit': 0.15,           # 止盈：涨超买入价 15%
    'trailing_trigger': 0.05,      # 移动止损触发线：最高收益 ≥5% 后启用
    'trailing_stop': 0.08,         # 移动止损：从最高价回撤 8%
    'expire_days': 10,             # 持仓到期天数（交易日）
    'expire_min_return': 0.03,     # 到期时收益率低于 3% 则离场
    'max_new_buys_per_day': 3,     # 每日最多新开仓数
}

# 交易成本（固定值，与 backtest_engine.calculate_backtest_cost 口径一致）
COMMISSION_RATE = 0.00015    # 佣金 0.015%，双向
MIN_COMMISSION = 5.0         # 最低佣金 5 元
STAMP_TAX_RATE = 0.001       # 印花税 0.1%，仅卖出
TRANSFER_FEE_RATE = 0.00001  # 过户费 0.001%，仅沪市（6 开头），双向


def calc_trade_cost(stock_code: str, price: float, quantity: int, is_buy: bool) -> float:
    """计算单边交易费用合计"""
    amount = price * quantity
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    transfer = amount * TRANSFER_FEE_RATE if stock_code.startswith('6') else 0.0
    stamp = 0.0 if is_buy else amount * STAMP_TAX_RATE
    return round(commission + transfer + stamp, 2)


class SimAccount:
    """模拟盘账户：状态持久化在独立 SQLite 库，每日增量结算"""

    def __init__(self, db_path: str = None, config: Dict = None):
        root = Path(__file__).resolve().parent.parent
        self.db_path = Path(db_path) if db_path else root / 'data' / 'sim_account.db'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(self._load_yaml_config())
        if config:
            self.config.update(config)
        self._init_tables()
        self._ensure_meta()

    # ==================== 初始化 ====================

    def _load_yaml_config(self) -> Dict:
        """读取 config/config.yaml 的 sim_account 节（可选，不存在则用默认值）"""
        try:
            import yaml
            cfg_file = Path(__file__).resolve().parent.parent / 'config' / 'config.yaml'
            if cfg_file.exists():
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                section = cfg.get('sim_account') or {}
                return {k: v for k, v in section.items() if k in DEFAULT_CONFIG}
        except Exception as e:
            logger.warning(f"读取 sim_account 配置失败，使用默认值: {e}")
        return {}

    @contextmanager
    def _connect(self):
        """连接上下文管理器：正常退出时 commit，异常时 rollback，确保关闭连接。

        注意：sqlite3.Connection 自带的 with 只管理事务、不关闭连接，
        在 Windows 上会导致文件锁残留，故必须显式 close。
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sim_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS sim_positions (
                    code TEXT PRIMARY KEY,
                    name TEXT,
                    quantity INTEGER,
                    buy_price REAL,
                    buy_date TEXT,
                    highest_price REAL,
                    strategy TEXT
                );
                CREATE TABLE IF NOT EXISTS sim_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_date TEXT,
                    code TEXT,
                    name TEXT,
                    side TEXT,               -- buy / sell
                    alloc_amount REAL,       -- 买单的拟分配金额（成交时按实际开盘价换算股数）
                    reason TEXT,
                    strategy TEXT,
                    status TEXT DEFAULT 'pending'   -- pending / filled / cancelled
                );
                CREATE TABLE IF NOT EXISTS sim_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT,
                    code TEXT,
                    name TEXT,
                    side TEXT,
                    price REAL,
                    quantity INTEGER,
                    amount REAL,
                    fee REAL,
                    profit REAL,             -- 仅卖单：扣除双边费用后的单笔盈亏
                    reason TEXT,
                    strategy TEXT
                );
                CREATE TABLE IF NOT EXISTS sim_nav (
                    nav_date TEXT PRIMARY KEY,
                    cash REAL,
                    market_value REAL,
                    total_assets REAL,
                    daily_return REAL,
                    cum_return REAL
                );
            """)

    def _ensure_meta(self):
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM sim_meta WHERE key='initial_capital'").fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO sim_meta(key, value) VALUES('initial_capital', ?)",
                    (str(self.config['initial_capital']),)
                )
                conn.execute(
                    "INSERT INTO sim_meta(key, value) VALUES('created_at', ?)",
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),)
                )
                logger.info(f"模拟盘账户初始化: 初始资金 ¥{self.config['initial_capital']:,.0f}")

    # ==================== 状态读写 ====================

    def _get_cash(self, conn) -> float:
        row = conn.execute("SELECT cash FROM sim_nav ORDER BY nav_date DESC LIMIT 1").fetchone()
        if row:
            return float(row['cash'])
        return float(conn.execute("SELECT value FROM sim_meta WHERE key='initial_capital'").fetchone()['value'])

    def _get_positions(self, conn) -> Dict[str, Dict]:
        rows = conn.execute("SELECT * FROM sim_positions").fetchall()
        return {r['code']: dict(r) for r in rows}

    def _get_pending_orders(self, conn) -> List[Dict]:
        rows = conn.execute("SELECT * FROM sim_orders WHERE status='pending'").fetchall()
        return [dict(r) for r in rows]

    # ==================== 行情读取 ====================

    def _read_kline(self, code: str, end_date: str, limit: int = 60):
        """读取 K 线（date 升序，截止 end_date）"""
        from utils.global_db import get_global_db
        db = get_global_db()
        df = db.read_stock(code, end_date=end_date, limit=limit, order='desc')
        if df is None or df.empty:
            return None
        return df.sort_values('date').reset_index(drop=True)

    def _get_bar(self, code: str, trade_date: str) -> Optional[Dict]:
        """获取 trade_date 当日的 OHLC；无数据（停牌等）返回 None"""
        df = self._read_kline(code, trade_date, limit=5)
        if df is None:
            return None
        row = df[df['date'].dt.strftime('%Y-%m-%d') == trade_date]
        if row.empty:
            return None
        r = row.iloc[-1]
        return {'open': float(r['open']), 'high': float(r['high']),
                'low': float(r['low']), 'close': float(r['close'])}

    def _get_latest_close(self, code: str, trade_date: str) -> float:
        """获取截止 trade_date 的最新收盘价（用于停牌股估值）"""
        df = self._read_kline(code, trade_date, limit=30)
        if df is None or df.empty:
            return 0.0
        return float(df.iloc[-1]['close'])

    def _count_hold_trading_days(self, code: str, buy_date: str, trade_date: str) -> int:
        """统计 buy_date（不含）到 trade_date（含）之间的交易日数（以该股K线为准）"""
        df = self._read_kline(code, trade_date, limit=60)
        if df is None:
            return 0
        dates = df['date'].dt.strftime('%Y-%m-%d')
        return int(((dates > buy_date) & (dates <= trade_date)).sum())

    # ==================== 每日结算主流程 ====================

    def run_daily(self, trade_date: str, candidates: List[Dict]) -> Dict:
        """每日结算入口

        Args:
            trade_date: 交易日 YYYY-MM-DD
            candidates: 当日选股结果 [{'code','name','signals','strategies'}, ...]

        Returns:
            结算摘要 dict
        """
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM sim_nav WHERE nav_date=?", (trade_date,)).fetchone():
                logger.info(f"模拟盘 {trade_date} 已结算过，跳过（幂等）")
                return {'date': trade_date, 'skipped': True}

        summary = {'date': trade_date, 'skipped': False, 'filled_sells': 0, 'filled_buys': 0,
                   'new_sell_orders': 0, 'new_buy_orders': 0, 'sell_alerts': []}

        with self._connect() as conn:
            cash = self._get_cash_live(conn)
            positions = self._get_positions(conn)

            # ---- 1. 成交待执行订单（先卖后买，开盘价成交）----
            for order in self._get_pending_orders(conn):
                cash = self._fill_order(conn, order, trade_date, positions, cash, summary)

            # ---- 2. 持仓卖出规则检查（用当日收盘价，生成次日卖单）----
            for code, pos in list(positions.items()):
                bar = self._get_bar(code, trade_date)
                if bar:
                    # 更新历史最高价（用于移动止损）
                    if bar['high'] > pos['highest_price']:
                        conn.execute("UPDATE sim_positions SET highest_price=? WHERE code=?",
                                     (bar['high'], code))
                        pos['highest_price'] = bar['high']
                    reason = self._check_sell_rules(pos, bar['close'],
                                                    self._count_hold_trading_days(code, pos['buy_date'], trade_date))
                else:
                    reason = None  # 停牌无法估值，暂不触发卖出
                if reason:
                    self._create_order(conn, trade_date, code, pos['name'], 'sell', 0,
                                       reason, pos.get('strategy', ''))
                    summary['new_sell_orders'] += 1
                    # 记录卖出信号明细，供结算后即时推送提醒
                    summary['sell_alerts'].append({
                        'code': code,
                        'name': pos['name'],
                        'reason': reason,
                        'buy_price': pos['buy_price'],
                        'current_price': bar['close'],
                        'return_rate': round(bar['close'] / pos['buy_price'] - 1, 4)
                            if pos['buy_price'] > 0 else 0,
                        'strategy': pos.get('strategy', ''),
                    })

            # ---- 3. 从选股结果生成买单 ----
            cash = self._get_cash_live(conn)  # 重读实时现金（含当日成交变动）
            positions = self._get_positions(conn)
            pending_buys = {o['code'] for o in self._get_pending_orders(conn) if o['side'] == 'buy'}
            pending_sells = {o['code'] for o in self._get_pending_orders(conn) if o['side'] == 'sell'}

            market_value_now = 0.0
            for c, p in positions.items():
                b = self._get_bar(c, trade_date)
                market_value_now += p['quantity'] * (b['close'] if b else self._get_latest_close(c, trade_date))
            total_assets = cash + market_value_now
            slots = self.config['max_positions'] - len(positions) - len(pending_buys)
            slots = min(slots, self.config['max_new_buys_per_day'])

            if slots > 0 and candidates:
                # 排序：被更多策略选中的优先，其次信号数量
                ranked = sorted(candidates,
                                key=lambda s: (len(s.get('strategies', [])), len(s.get('signals', []))),
                                reverse=True)
                # 持仓数（含即将买入）确定后等权分配
                target_count = min(self.config['max_positions'],
                                   len(positions) + len(pending_buys) + slots)
                alloc = total_assets / max(target_count, 1)
                for sig in ranked:
                    if slots <= 0:
                        break
                    code = sig['code']
                    if code in positions or code in pending_buys or code in pending_sells:
                        continue
                    bar = self._get_bar(code, trade_date)
                    if not bar or bar['close'] <= 0:
                        continue
                    # 至少买得起 100 股才挂买单（按当日收盘价估算）
                    if alloc < bar['close'] * 100 + MIN_COMMISSION:
                        continue
                    strategy_names = '+'.join(sig.get('strategies', []))
                    self._create_order(conn, trade_date, code, sig.get('name', ''), 'buy',
                                       round(alloc, 2), f"选股信号: {strategy_names}", strategy_names)
                    pending_buys.add(code)
                    slots -= 1
                    summary['new_buy_orders'] += 1

            # ---- 4. 记录当日净值（收盘价估值）----
            cash = self._get_cash_live(conn)
            positions = self._get_positions(conn)
            market_value = 0.0
            for code, pos in positions.items():
                bar = self._get_bar(code, trade_date)
                price = bar['close'] if bar else self._get_latest_close(code, trade_date)
                market_value += pos['quantity'] * price

            total = cash + market_value
            initial = float(conn.execute("SELECT value FROM sim_meta WHERE key='initial_capital'").fetchone()['value'])
            prev = conn.execute("SELECT total_assets FROM sim_nav ORDER BY nav_date DESC LIMIT 1").fetchone()
            daily_ret = (total / float(prev['total_assets']) - 1) if prev else 0.0
            cum_ret = total / initial - 1

            conn.execute(
                "INSERT INTO sim_nav(nav_date, cash, market_value, total_assets, daily_return, cum_return) "
                "VALUES(?,?,?,?,?,?)",
                (trade_date, round(cash, 2), round(market_value, 2), round(total, 2),
                 round(daily_ret, 6), round(cum_ret, 6))
            )
            # NAV 落库后同步实时现金基准，供下一交易日读取
            conn.execute("INSERT OR REPLACE INTO sim_meta(key, value) VALUES('cash_pending', ?)",
                         (str(round(cash, 2)),))

        summary.update({'cash': round(cash, 2), 'market_value': round(market_value, 2),
                        'total_assets': round(total, 2), 'cum_return': round(cum_ret, 4),
                        'positions': len(positions)})
        logger.info(f"模拟盘 {trade_date} 结算: 总资产 ¥{total:,.2f} "
                    f"(累计收益 {cum_ret*100:+.2f}%), 持仓 {len(positions)} 只, "
                    f"成交 买{summary['filled_buys']}/卖{summary['filled_sells']}, "
                    f"新挂 买{summary['new_buy_orders']}/卖{summary['new_sell_orders']}")
        return summary

    # ==================== 订单与成交 ====================

    def _create_order(self, conn, created_date: str, code: str, name: str, side: str,
                      alloc_amount: float, reason: str, strategy: str):
        conn.execute(
            "INSERT INTO sim_orders(created_date, code, name, side, alloc_amount, reason, strategy, status) "
            "VALUES(?,?,?,?,?,?,?, 'pending')",
            (created_date, code, name, side, alloc_amount, reason, strategy)
        )

    def _fill_order(self, conn, order: Dict, trade_date: str, positions: Dict, cash: float,
                    summary: Dict) -> float:
        """以当日开盘价成交订单；停牌则保留待执行。返回最新现金（内存值）"""
        code = order['code']
        bar = self._get_bar(code, trade_date)
        if not bar or bar['open'] <= 0:
            logger.info(f"  {code} 当日无行情（停牌？），订单顺延")
            return cash
        price = bar['open']

        if order['side'] == 'sell':
            pos = positions.get(code)
            if not pos:
                conn.execute("UPDATE sim_orders SET status='cancelled' WHERE id=?", (order['id'],))
                return cash
            qty = pos['quantity']
            fee = calc_trade_cost(code, price, qty, is_buy=False)
            amount = round(price * qty, 2)
            profit = round((price - pos['buy_price']) * qty - fee, 2)
            conn.execute(
                "INSERT INTO sim_trades(trade_date, code, name, side, price, quantity, amount, fee, profit, reason, strategy) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (trade_date, code, pos['name'], 'sell', price, qty, amount, fee, profit,
                 order.get('reason', ''), order.get('strategy', ''))
            )
            conn.execute("DELETE FROM sim_positions WHERE code=?", (code,))
            conn.execute("UPDATE sim_orders SET status='filled' WHERE id=?", (order['id'],))
            cash += amount - fee
            positions.pop(code, None)
            summary['filled_sells'] += 1
            logger.info(f"  成交卖出 {code} {pos['name']} x{qty} @ ¥{price:.2f}, "
                        f"盈亏 {profit:+.2f} ({order.get('reason', '')})")

        else:  # buy
            alloc = min(order['alloc_amount'], cash)
            qty = int(alloc / price / 100) * 100
            if qty <= 0:
                conn.execute("UPDATE sim_orders SET status='cancelled' WHERE id=?", (order['id'],))
                logger.info(f"  {code} 资金不足 100 股，买单取消")
                return cash
            fee = calc_trade_cost(code, price, qty, is_buy=True)
            amount = round(price * qty, 2)
            if amount + fee > cash:
                qty -= 100
                if qty <= 0:
                    conn.execute("UPDATE sim_orders SET status='cancelled' WHERE id=?", (order['id'],))
                    return cash
                fee = calc_trade_cost(code, price, qty, is_buy=True)
                amount = round(price * qty, 2)
            conn.execute(
                "INSERT INTO sim_trades(trade_date, code, name, side, price, quantity, amount, fee, profit, reason, strategy) "
                "VALUES(?,?,?,?,?,?,?,?,NULL,?,?)",
                (trade_date, code, order['name'], 'buy', price, qty, amount, fee,
                 order.get('reason', ''), order.get('strategy', ''))
            )
            conn.execute(
                "INSERT INTO sim_positions(code, name, quantity, buy_price, buy_date, highest_price, strategy) "
                "VALUES(?,?,?,?,?,?,?)",
                (code, order['name'], qty, price, trade_date, price, order.get('strategy', ''))
            )
            conn.execute("UPDATE sim_orders SET status='filled' WHERE id=?", (order['id'],))
            cash -= amount + fee
            positions[code] = {'code': code, 'name': order['name'], 'quantity': qty,
                               'buy_price': price, 'buy_date': trade_date, 'highest_price': price,
                               'strategy': order.get('strategy', '')}
            summary['filled_buys'] += 1
            logger.info(f"  成交买入 {code} {order['name']} x{qty} @ ¥{price:.2f} "
                        f"(金额 ¥{amount:,.2f}, {order.get('reason', '')})")

        # 现金落库：写入一条临时记录不便，改为在 NAV 记录时统一写入；
        # 这里用 meta 表记录实时现金，保证同一连接内后续读取一致
        conn.execute("INSERT OR REPLACE INTO sim_meta(key, value) VALUES('cash_pending', ?)",
                     (str(round(cash, 2)),))
        return cash

    def _get_cash_live(self, conn) -> float:
        row = conn.execute("SELECT value FROM sim_meta WHERE key='cash_pending'").fetchone()
        if row:
            return float(row['value'])
        return self._get_cash(conn)

    def _check_sell_rules(self, pos: Dict, close: float, hold_days: int) -> Optional[str]:
        """卖出规则：止损 / 止盈 / 移动止损 / 持仓到期。返回原因或 None"""
        buy_price = pos['buy_price']
        ret = close / buy_price - 1
        if ret <= -self.config['stop_loss']:
            return f"止损 (收益率 {ret*100:.2f}%)"
        if ret >= self.config['take_profit']:
            return f"止盈 (收益率 {ret*100:.2f}%)"
        highest_ret = pos['highest_price'] / buy_price - 1
        if highest_ret >= self.config['trailing_trigger'] and \
                close <= pos['highest_price'] * (1 - self.config['trailing_stop']):
            return f"移动止损 (最高收益 {highest_ret*100:.2f}%, 回撤至 {ret*100:.2f}%)"
        if hold_days >= self.config['expire_days'] and ret <= self.config['expire_min_return']:
            return f"持仓到期 (持有{hold_days}个交易日, 收益率 {ret*100:.2f}%)"
        return None

    # ==================== 查询接口（供 Web API 使用） ====================

    def get_nav_series(self, limit: int = 250) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sim_nav ORDER BY nav_date DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_trades(self, limit: int = 100) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sim_trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_positions(self) -> List[Dict]:
        with self._connect() as conn:
            positions = self._get_positions(conn)
            cash = self._get_cash_live(conn)
            latest_nav = conn.execute(
                "SELECT nav_date FROM sim_nav ORDER BY nav_date DESC LIMIT 1").fetchone()
        ref_date = latest_nav['nav_date'] if latest_nav else datetime.now().strftime('%Y-%m-%d')
        result = []
        for code, pos in positions.items():
            current = self._get_latest_close(code, ref_date)
            ret = (current / pos['buy_price'] - 1) if pos['buy_price'] > 0 else 0
            result.append({**pos, 'current_price': current, 'return_rate': round(ret, 4)})
        result.sort(key=lambda p: p['buy_date'])
        return result

    def get_metrics(self) -> Dict:
        """收益指标：累计/年化收益、最大回撤、夏普、胜率、盈亏比"""
        import math
        navs = self.get_nav_series(limit=100000)
        with self._connect() as conn:
            initial = float(conn.execute(
                "SELECT value FROM sim_meta WHERE key='initial_capital'").fetchone()['value'])
            sells = conn.execute(
                "SELECT profit FROM sim_trades WHERE side='sell' AND profit IS NOT NULL").fetchall()
            buy_count = conn.execute("SELECT COUNT(*) c FROM sim_trades WHERE side='buy'").fetchone()['c']

        metrics = {'initial_capital': initial, 'trading_days': len(navs),
                   'buy_count': buy_count, 'sell_count': len(sells)}
        if not navs:
            return {**metrics, 'note': '尚无净值记录'}

        total_assets = [n['total_assets'] for n in navs]
        total_ret = total_assets[-1] / initial - 1
        days = len(navs)
        annual_ret = (1 + total_ret) ** (252 / days) - 1 if days > 0 and total_ret > -1 else -1

        # 最大回撤
        peak, max_dd = total_assets[0], 0.0
        for v in total_assets:
            peak = max(peak, v)
            max_dd = min(max_dd, v / peak - 1)

        # 夏普（日频，无风险利率年化 3%）
        dailies = [n['daily_return'] for n in navs if n['daily_return'] is not None][1:]
        sharpe = 0.0
        if len(dailies) > 1:
            mean = sum(dailies) / len(dailies)
            var = sum((r - mean) ** 2 for r in dailies) / (len(dailies) - 1)
            std = math.sqrt(var)
            rf_daily = 0.03 / 252
            sharpe = (mean - rf_daily) / std * math.sqrt(252) if std > 0 else 0.0

        # 胜率与盈亏比（按已平仓卖单）
        profits = [float(s['profit']) for s in sells]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        win_rate = len(wins) / len(profits) if profits else 0.0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None

        metrics.update({
            'total_assets': round(total_assets[-1], 2),
            'total_return': round(total_ret, 4),
            'annual_return': round(annual_ret, 4),
            'max_drawdown': round(max_dd, 4),
            'sharpe': round(sharpe, 2),
            'win_rate': round(win_rate, 4),
            'profit_factor': round(profit_factor, 2) if profit_factor is not None else None,
            'start_date': navs[0]['nav_date'],
            'end_date': navs[-1]['nav_date'],
        })
        return metrics
