"""
金三角策略（有效买托）- 均线金叉三角形形态选股策略

理论基础（唐能通《短线是银》价托理论）：
- 均线 = 平均持仓成本。MA5/MA10/MA20 分别代表短线客、波段客、中线客的成本。
- A点：5日均线上穿10日均线（短线客成本抬升，第一道支撑）
- B点：5日均线上穿20日均线
- C点：10日均线上穿20日均线（波段资金认可，第二、三道支撑形成）
- A、B、C三点按时间顺序形成封闭三角形，即"买托"。

特殊形态：
- 金蜘蛛：A、B、C三点汇聚于同一天（ac_interval=0），多线共振，为最强形态。

剔除规则（买托质量校验）：
- 买托时效内（A→C 窗口）出现连续两个涨停：剔除（追高透支）
- 5日线上穿10日线后必须保持上升趋势，不得下拐：否则剔除（买托不结实）
- C日换手率低于下限（默认3%）：剔除（交易冷清，资金未关注）
- C日成交量低于前N日均量的指定倍数（默认1.5倍）：剔除（无量金叉多为假信号）
- C日收盘价相对前低涨幅过大：剔除（高位三角，非低吸区）
- MA20/MA60 陡峭下跌中形成的金叉：剔除（长期趋势未扭转，金叉多为反弹噪音）
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from strategy.base_strategy import BaseStrategy


class GoldenTriangleStrategy(BaseStrategy):
    """金三角策略（有效买托）"""

    def __init__(self, params=None):
        default_params = {
            # 均线参数
            'short_period': 5,
            'mid_period': 10,
            'long_period': 20,
            'super_long_period': 60,
            # 形态参数
            'ac_interval': 3,
            'c_point_valid_days': 2,
            'exclude_xd': True,
            'lookback_days': 30,
            'require_ascending_cross_points': True,  # 金叉点逐级抬高：B>A，C>A且C>B
            # C点条件
            'c_cross_min_gain': 0.01,
            'c_cross_min_volume_ratio': 1.5,
            'volume_ma_days': 5,
            # 买托质量过滤（笔记规则）
            'min_turnover_rate': 3.0,
            'exclude_consecutive_limit_up': True,
            'limit_up_gain': 0.095,
            'require_ma5_rising': True,
            'ma5_rising_tolerance': 0.001,
            # 趋势过滤（研报规则）
            'max_rise_from_low': 0.35,
            'ma_long_slope_days': 5,
            'ma_long_min_slope': -0.02,
            'ma_super_long_slope_days': 10,
            'ma_super_long_min_slope': -0.05,
            'require_price_above_ma_long': True,
            # 权重
            'strategy_weight': 50,
        }
        if params:
            default_params.update(params)
        super().__init__("金三角策略", default_params)

    # ------------------------------------------------------------------
    # 指标计算
    # ------------------------------------------------------------------
    def calculate_indicators(self, df) -> pd.DataFrame:
        """计算技术指标"""
        result = df.copy()

        # 检测数据是否为倒序
        is_reversed = len(result) > 1 and str(result['date'].iloc[0]) > str(result['date'].iloc[1])

        # 如果是倒序，先反转成正序以便正确计算
        if is_reversed:
            result = result.iloc[::-1].reset_index(drop=True)

        short_period = int(self.params['short_period'])
        mid_period = int(self.params['mid_period'])
        long_period = int(self.params['long_period'])
        super_long_period = int(self.params['super_long_period'])
        volume_ma_days = int(self.params.get('volume_ma_days', 5))

        result['sma_short'] = result['close'].rolling(window=short_period).mean()
        result['sma_mid'] = result['close'].rolling(window=mid_period).mean()
        result['sma_long'] = result['close'].rolling(window=long_period).mean()
        result['sma_super_long'] = result['close'].rolling(window=super_long_period).mean()
        # 前 N 日均量（不含当日）：shift(1) 避免当日放量自我稀释分母
        result['volume_ma_prev'] = result['volume'].rolling(window=volume_ma_days).mean().shift(1)

        result['prev_close'] = result['close'].shift(1)
        result['gain'] = (result['close'] - result['prev_close']) / result['prev_close']

        # 换手率（近似）：成交量(手)×100×收盘价 ÷ 总市值
        # 以总股本代替流通股本，结果偏保守（实际换手率只会更高）
        if 'turnover_rate' in result.columns:
            pass  # 数据层若已提供精确换手率，直接使用
        elif 'market_cap' in result.columns and pd.to_numeric(result['market_cap'], errors='coerce').fillna(0).gt(0).any():
            mc = pd.to_numeric(result['market_cap'], errors='coerce')
            result['turnover_rate'] = np.where(
                (mc > 0) & (result['close'] > 0),
                result['volume'] * 100 * result['close'] / mc.replace(0, np.nan) * 100,
                np.nan
            )
        else:
            # K线数据无市值时，回退查询 stock_basic 表的最新总市值
            mc = self._lookup_market_cap_from_db(result)
            if mc and mc > 0:
                result['turnover_rate'] = np.where(
                    result['close'] > 0,
                    result['volume'] * 100 * result['close'] / mc * 100,
                    np.nan
                )
            else:
                result['turnover_rate'] = np.nan

        # 注意：不使用ffill()向前填充，避免引入未来函数
        # ffill会使用未来数据填充NaN，导致回测结果失真
        # 如果需要处理缺失数据，应使用bfill()向后填充（使用历史数据）
        # result = result.ffill()  # ⚠️ 这是未来函数！

        # 只有原始数据是倒序时才反转回去
        # 如果原始数据是正序，保持正序返回
        if is_reversed:
            result = result.iloc[::-1].reset_index(drop=True)

        return result

    def _lookup_market_cap_from_db(self, df) -> Optional[float]:
        """从 stock_basic 表查询股票最新总市值（元），带实例缓存

        用于 K 线数据缺失 market_cap 时的换手率近似计算。
        查询失败或数据缺失时返回 None（调用方跳过换手率校验，不误杀）。
        """
        try:
            if not hasattr(self, '_market_cap_cache'):
                self._market_cap_cache = {}
            code = None
            if 'code' in df.columns and len(df) > 0:
                code = str(df['code'].iloc[0])
            if not code:
                return None
            if code in self._market_cap_cache:
                return self._market_cap_cache[code]
            from utils.global_db import get_global_db
            row = get_global_db().query_one(
                "SELECT market_cap FROM stock_basic WHERE code = ?", (code,))
            mc = None
            if row and row.get('market_cap'):
                mc = float(row['market_cap'])
                if mc <= 0:
                    mc = None
                elif mc < 1e7:
                    # 单位归一化：stock_basic.market_cap 存在双写入口，
                    # 有的写“元”（如 2.19e10），有的写“亿”（如 219.1）。
                    # A股最小市值也超过 1000万元，小于 1e7 的值必然是“亿”，统一转为“元”
                    mc = mc * 1e8
            self._market_cap_cache[code] = mc
            return mc
        except Exception:
            return None

    def get_selection_criteria(self):
        """获取选股条件描述"""
        p = self.params
        return [
            f"1. A点形成：{p['short_period']}日均线上穿{p['mid_period']}日均线",
            f"2. B点形成：{p['short_period']}日均线上穿{p['long_period']}日均线",
            f"3. C点形成：{p['mid_period']}日均线上穿{p['long_period']}日均线（A→B→C 按序形成）",
            f"4. C点涨幅 >= {p['c_cross_min_gain']*100}%（C点允许落在最近{int(p.get('c_point_valid_days', 2))}个交易日内）",
            f"5. C日成交量 >= 前{int(p.get('volume_ma_days', 5))}日均量 × {p.get('c_cross_min_volume_ratio', 1.5)}",
            f"6. A-C间隔 <= {p['ac_interval']}天",
            f"7. 均线多头排列：MA{p['short_period']} >= MA{p['mid_period']} >= MA{p['long_period']} >= MA{p['super_long_period']}",
            f"8. C日换手率 >= {p.get('min_turnover_rate', 3.0)}%（市值数据缺失时跳过）",
            f"9. A→C 期间 MA{p['short_period']} 必须持续上升，不得下拐" if p.get('require_ma5_rising', True) else "9. （已关闭）MA5持续上升校验",
            f"10. A→C 窗口内出现连续两个涨停（≥{p.get('limit_up_gain', 0.095)*100}%）则剔除" if p.get('exclude_consecutive_limit_up', True) else "10. （已关闭）两连板剔除",
            f"11. C日收盘相对前{int(p.get('lookback_days', 30))}日最低价涨幅 <= {p.get('max_rise_from_low', 0.35)*100}%（低位买托）",
            f"12. MA{p['long_period']} 近{int(p.get('ma_long_slope_days', 5))}日斜率 >= {p.get('ma_long_min_slope', -0.02)*100}%（走平或拐头）",
            f"13. MA{p['super_long_period']} 近{int(p.get('ma_super_long_slope_days', 10))}日斜率 >= {p.get('ma_super_long_min_slope', -0.05)*100}%（长期趋势未崩塌）",
            f"14. C日收盘价站上 MA{p['long_period']}" if p.get('require_price_above_ma_long', True) else "14. （已关闭）收盘价站上MA20",
            f"15. 信号日剔除除权股票（XD/XR/DR 前缀）" if p.get('exclude_xd', True) else "15. （已关闭）除权日剔除",
            f"16. 金叉点逐级抬高：B点高于A点，C点高于A点和B点（金蜘蛛豁免）" if p.get('require_ascending_cross_points', True) else "16. （已关闭）金叉点逐级抬高校验",
        ]

    def quick_filter(self, df):
        """快速过滤：检查数据是否足够并进行涨幅过滤"""
        if df is None or df.empty:
            self._reject_reason = '无K线数据'
            return False

        # 数据量检查
        min_length = max(int(self.params['super_long_period']), 60)
        if len(df) < min_length:
            self._reject_reason = f'K线数据不足{min_length}条（实际{len(df)}条）'
            return False

        # 获取C点涨幅阈值作为快速过滤标准
        min_gain = float(self.params.get('c_cross_min_gain', 0.01))
        # C点允许落在最近 c_point_valid_days 天内，任一天满足涨幅要求即可
        c_valid_days = max(1, int(self.params.get('c_point_valid_days', 2)))

        # 近期涨幅过滤：最近 c_valid_days 天中至少一天满足最小涨幅要求
        if len(df) >= 2:
            check_n = min(c_valid_days, len(df) - 1)
            # 检查日期顺序
            is_reversed = str(df['date'].iloc[0]) > str(df['date'].iloc[1])
            any_gain_ok = False
            for k in range(check_n):
                if is_reversed:
                    # 倒序排列
                    latest = df.iloc[k]
                    prev_close = df.iloc[k + 1]['close']
                else:
                    # 正序排列
                    latest = df.iloc[-1 - k]
                    prev_close = df.iloc[-2 - k]['close']

                if prev_close > 0:
                    day_gain = (latest['close'] - prev_close) / prev_close
                    if day_gain >= min_gain:
                        any_gain_ok = True
                        break
            if not any_gain_ok:
                self._reject_reason = f'最近{check_n}个交易日涨幅均不足{min_gain*100:.0f}%'
                return False

        return True

    # ------------------------------------------------------------------
    # 选股主逻辑
    # ------------------------------------------------------------------
    def select_stocks(self, df, stock_name='') -> list:
        """选股逻辑"""
        # 快速过滤：先排除明显不符合条件的股票
        if not self.quick_filter(df):
            return []

        if stock_name and not self._validate_stock_name(stock_name):
            self._reject_reason = 'ST/退市股票，按规则剔除'
            return []

        # 除权日剔除：信号日名称含 XD/XR/DR 前缀的股票跳过（价格跳变扭曲均线交叉）
        if self.params.get('exclude_xd', True) and stock_name:
            if stock_name.upper().startswith(('XD', 'XR', 'DR')):
                self._reject_reason = '除权除息日股票（XD/XR/DR），按规则剔除'
                return []

        df = self.calculate_indicators(df.copy())

        latest_idx = 0
        latest = df.iloc[latest_idx]

        cross_points = self._find_cross_points(df, latest_idx)
        if cross_points is None:
            c_valid_days = max(1, int(self.params.get('c_point_valid_days', 2)))
            self._reject_reason = f'最近{c_valid_days}个交易日内无MA10×MA20金叉（无C点），或A/B点未按序形成'
            return []

        a_date, b_date, c_date, a_idx, b_idx, c_idx = cross_points

        # 金叉点逐级抬高校验：B点高于A点，C点高于A点和B点（价托向上倾斜）
        # 点位高度用交叉点均线值衡量：A点取MA10，B/C点取MA20
        # 金蜘蛛（A/B/C三点同日重合）豁免：点位天然重合，视为最强形态
        if self.params.get('require_ascending_cross_points', True) and not (a_idx == b_idx == c_idx):
            a_height = df.iloc[a_idx]['sma_mid']
            b_height = df.iloc[b_idx]['sma_long']
            c_height = df.iloc[c_idx]['sma_long']
            if not (pd.isna(a_height) or pd.isna(b_height) or pd.isna(c_height)):
                if not (b_height > a_height and c_height > a_height and c_height > b_height):
                    self._reject_reason = f'金叉点未逐级抬高（A={a_height:.2f}, B={b_height:.2f}, C={c_height:.2f}）'
                    return []

        # 使用 index 差值计算交易日间隔（数据倒序排列，index越大日期越早）
        ac_interval_days = a_idx - c_idx
        if ac_interval_days > int(self.params['ac_interval']):
            self._reject_reason = f"A→C间隔{ac_interval_days}天，超过上限{int(self.params['ac_interval'])}天"
            return []

        c_day_data = df.iloc[c_idx]
        c_gain = c_day_data['gain'] if not pd.isna(c_day_data['gain']) else 0
        if c_gain < float(self.params['c_cross_min_gain']):
            self._reject_reason = f"C日涨幅不足{float(self.params['c_cross_min_gain'])*100:.0f}%（实际{c_gain*100:.1f}%）"
            return []

        # 量比：C日成交量 / 前 N 日均量（不含当日）
        c_volume_ratio = self._calc_volume_ratio(c_day_data)
        if c_volume_ratio < float(self.params.get('c_cross_min_volume_ratio', 1.5)):
            self._reject_reason = f"C日量比不足{float(self.params.get('c_cross_min_volume_ratio', 1.5))}（实际{c_volume_ratio:.2f}）"
            return []

        # ---- 买托质量过滤（笔记规则） ----
        # 换手率：C日换手率必须达到下限；市值数据缺失（NaN）时跳过不误杀
        turnover_rate = self._get_turnover_rate(c_day_data)
        min_turnover = float(self.params.get('min_turnover_rate', 3.0))
        if min_turnover > 0 and not pd.isna(turnover_rate):
            if turnover_rate < min_turnover:
                self._reject_reason = f'C日换手率不足{min_turnover:.0f}%（实际{turnover_rate:.1f}%）'
                return []

        # 两连板剔除：A→C 窗口内出现连续两个涨停（防追高透支）
        if self.params.get('exclude_consecutive_limit_up', True):
            if self._has_consecutive_limit_up(df, c_idx, a_idx):
                self._reject_reason = 'A→C窗口内出现连续两个涨停（追高透支，剔除）'
                return []

        # MA5 持续上升校验：A点→C点期间 MA5 不得下拐（买托必须结实）
        if self.params.get('require_ma5_rising', True):
            if not self._is_ma5_rising(df, c_idx, a_idx):
                self._reject_reason = 'A→C期间MA5下拐（买托不结实）'
                return []

        # ---- 趋势过滤（研报规则） ----
        # 低位过滤：C日收盘相对前低涨幅不能过大（低位买托才可靠）
        if not self._is_low_position(df, c_idx):
            max_rise = float(self.params.get('max_rise_from_low', 0.35))
            lookback = int(self.params.get('lookback_days', 30))
            self._reject_reason = f'C日收盘相对前{lookback}日最低价涨幅超过{max_rise*100:.0f}%（非低位）'
            return []

        # MA20 斜率：必须走平或拐头向上（陡峭下跌中的金叉多为反弹噪音）
        ma_long_slope = self._calc_ma_slope(df, c_idx, 'sma_long',
                                            int(self.params.get('ma_long_slope_days', 5)))
        if ma_long_slope is not None and ma_long_slope < float(self.params.get('ma_long_min_slope', -0.02)):
            self._reject_reason = f"MA20近{int(self.params.get('ma_long_slope_days', 5))}日斜率{ma_long_slope*100:.1f}%，低于下限{float(self.params.get('ma_long_min_slope', -0.02))*100:.0f}%（下跌趋势未扭转）"
            return []

        # MA60 斜率：长期趋势不能崩塌（数据不足时自动跳过）
        ma_super_long_slope = self._calc_ma_slope(df, c_idx, 'sma_super_long',
                                                  int(self.params.get('ma_super_long_slope_days', 10)))
        if ma_super_long_slope is not None and ma_super_long_slope < float(self.params.get('ma_super_long_min_slope', -0.05)):
            self._reject_reason = f"MA60近{int(self.params.get('ma_super_long_slope_days', 10))}日斜率{ma_super_long_slope*100:.1f}%，低于下限{float(self.params.get('ma_super_long_min_slope', -0.05))*100:.0f}%（长期趋势崩塌）"
            return []

        # 收盘价必须站上 MA20
        if self.params.get('require_price_above_ma_long', True):
            if pd.isna(c_day_data['sma_long']) or c_day_data['close'] < c_day_data['sma_long']:
                self._reject_reason = 'C日收盘价未站上MA20'
                return []

        # ---- 多头排列（原条件保留） ----
        sma_short = latest['sma_short']
        sma_mid = latest['sma_mid']
        sma_long = latest['sma_long']
        sma_super_long = latest['sma_super_long']

        if not (sma_short >= sma_mid >= sma_long >= sma_super_long):
            self._reject_reason = f'均线非多头排列（MA{int(self.params["short_period"])}={sma_short:.2f}, MA{int(self.params["mid_period"])}={sma_mid:.2f}, MA{int(self.params["long_period"])}={sma_long:.2f}, MA{int(self.params["super_long_period"])}={sma_super_long:.2f}）'
            return []

        triangle_type = 'golden_spider' if ac_interval_days == 0 else 'golden_triangle'

        # 三角形高度：C 点处三线最大相对离散度（越低越收敛越可靠）
        triangle_height = self._calc_triangle_height(c_day_data)

        # 信号强度评分（基础 0.6，封顶 1.0）
        signal_strength = self._calc_signal_strength(
            triangle_type=triangle_type,
            c_volume_ratio=c_volume_ratio,
            ma_long_slope=ma_long_slope,
            triangle_height=triangle_height,
            close=latest['close'],
            sma_super_long=sma_super_long,
        )

        reason_text = self._build_reason(
            triangle_type=triangle_type,
            ac_interval_days=ac_interval_days,
            c_gain=c_gain,
            c_volume_ratio=c_volume_ratio,
            turnover_rate=turnover_rate,
            ma_long_slope=ma_long_slope,
        )

        return [{
            'signal': 'buy',
            'reason': reason_text,
            'reasons': [reason_text],
            'date': latest['date'],
            'key_date': c_date,
            'key_date_type': '金三角C点' if triangle_type == 'golden_triangle' else '金蜘蛛',
            'price': float(latest['close']),
            'close': latest['close'],
            'J': None,
            'volume_ratio': round(c_volume_ratio, 2),
            'turnover_rate': None if pd.isna(turnover_rate) else round(turnover_rate, 2),
            'signal_strength': signal_strength,
            'stock_code': '',
            'stock_name': stock_name,
            'triangle_type': triangle_type,
            'cross_details': {
                'a_cross_date': a_date,
                'b_cross_date': b_date,
                'c_cross_date': c_date,
                'c_cross_gain': c_gain,
                'c_cross_volume_ratio': c_volume_ratio,
                'ac_interval_days': ac_interval_days,
            },
            'ma_details': {
                'sma_short': sma_short,
                'sma_mid': sma_mid,
                'sma_long': sma_long,
                'sma_super_long': sma_super_long,
            },
            'details': {
                'triangle_height': triangle_height,
                'ma_long_slope': ma_long_slope,
                'ma_super_long_slope': ma_super_long_slope,
                'signal_strength': signal_strength,
            },
            'pattern_confirmed': True,
            'strategy_weight': self.params['strategy_weight'],
        }]

    # ------------------------------------------------------------------
    # 金叉点查找
    # ------------------------------------------------------------------
    def _find_cross_points(self, df, latest_idx) -> Optional[Tuple]:
        """查找A、B、C三个金叉点

        逻辑：C点允许落在最近 c_point_valid_days 天内（默认2天，取最新的一次金叉）
        - C点：MA10 上穿 MA20（新鲜金叉：前一天 MA10 < MA20）
        - A点（向前查找ac_interval天）：MA5 >= MA10
        - B点（向前查找ac_interval天）：MA5 >= MA20

        时间顺序校验（经典价托理论：金叉必须按 A→B→C 顺序形成）：
        - a_idx >= b_idx >= c_idx（倒序数据，索引越大时间越早）
        - A、B、C三点可以在同一天（金蜘蛛）
        """
        ac_interval = int(self.params['ac_interval'])
        c_valid_days = max(1, int(self.params.get('c_point_valid_days', 2)))

        # 在最近 c_valid_days 个交易日内寻找最新的 C 点（新鲜 MA10×MA20 金叉）
        c_idx = None
        search_c_end = min(latest_idx + c_valid_days, len(df) - 1)
        for i in range(latest_idx, search_c_end):
            if i + 1 >= len(df):
                break
            curr_i = df.iloc[i]
            prev_i = df.iloc[i + 1]
            if prev_i['sma_mid'] < prev_i['sma_long'] and curr_i['sma_mid'] >= curr_i['sma_long']:
                c_idx = i
                break

        if c_idx is None:
            return None

        curr = df.iloc[c_idx]
        prev = df.iloc[c_idx + 1]

        sma_mid_curr = curr['sma_mid']
        sma_long_curr = curr['sma_long']
        sma_short_curr = curr['sma_short']
        sma_short_prev = prev['sma_short']
        sma_mid_prev = prev['sma_mid']
        sma_long_prev = prev['sma_long']

        # 检查C日当天是否满足A点和B点条件（用于支持ABC同一天或AB=C的情况）
        is_a_today = sma_short_prev < sma_mid_prev and sma_short_curr >= sma_mid_curr
        is_b_today = sma_short_prev < sma_long_prev and sma_short_curr >= sma_long_curr

        # 初始化A、B点索引
        a_idx, b_idx = None, None

        # 如果C日当天满足A点条件，优先使用当天
        if is_a_today:
            a_idx = c_idx

        # 如果C日当天满足B点条件，优先使用当天
        if is_b_today:
            b_idx = c_idx

        # 如果A或B点还未找到，向前查找（从c_idx + 1开始）
        if a_idx is None or b_idx is None:
            search_end = min(c_idx + ac_interval + 2, len(df))
            for i in range(c_idx + 1, search_end):
                if i + 1 >= len(df):
                    continue

                curr_i = df.iloc[i]
                prev_i = df.iloc[i + 1]

                sma_short_curr_i = curr_i['sma_short']
                sma_mid_curr_i = curr_i['sma_mid']
                sma_long_curr_i = curr_i['sma_long']

                sma_short_prev_i = prev_i['sma_short']
                sma_mid_prev_i = prev_i['sma_mid']
                sma_long_prev_i = prev_i['sma_long']

                if a_idx is None:
                    if sma_short_prev_i < sma_mid_prev_i and sma_short_curr_i >= sma_mid_curr_i:
                        a_idx = i

                if b_idx is None:
                    if sma_short_prev_i < sma_long_prev_i and sma_short_curr_i >= sma_long_curr_i:
                        b_idx = i

        # 检查是否找到A、B点
        if a_idx is None or b_idx is None:
            return None

        # 时间顺序校验：A → B → C 依次形成（倒序数据，索引越大时间越早）
        # a_idx >= b_idx >= c_idx，允许相等（同日金叉/金蜘蛛）
        if not (a_idx >= b_idx >= c_idx):
            return None

        return (
            str(df.iloc[a_idx]['date']).split()[0],
            str(df.iloc[b_idx]['date']).split()[0],
            str(df.iloc[c_idx]['date']).split()[0],
            a_idx, b_idx, c_idx
        )

    # ------------------------------------------------------------------
    # 过滤与评分的辅助方法
    # ------------------------------------------------------------------
    def _calc_volume_ratio(self, c_day_data) -> float:
        """C日量比：C日成交量 / 前 N 日均量（不含当日）"""
        prev_ma = c_day_data.get('volume_ma_prev')
        if prev_ma is None or pd.isna(prev_ma) or prev_ma <= 0:
            return 0
        return c_day_data['volume'] / prev_ma

    def _get_turnover_rate(self, c_day_data) -> float:
        """获取C日换手率（%），缺失时返回 NaN"""
        tr = c_day_data.get('turnover_rate')
        if tr is None:
            return np.nan
        try:
            return float(tr)
        except (TypeError, ValueError):
            return np.nan

    def _has_consecutive_limit_up(self, df, c_idx, a_idx) -> bool:
        """检查 A→C 窗口内是否出现连续两个涨停（笔记剔除规则⑥）

        倒序数据：c_idx <= a_idx，窗口为 [c_idx, a_idx]（含端点）。
        连续两日在时间上相邻 = 索引相邻。
        """
        limit_up_gain = float(self.params.get('limit_up_gain', 0.095))
        gains = df['gain'].values
        for i in range(c_idx, a_idx):
            # i 与 i+1 在时间上相邻（i+1 为 i 的前一交易日）
            g1 = gains[i] if i < len(gains) else np.nan
            g2 = gains[i + 1] if i + 1 < len(gains) else np.nan
            if not pd.isna(g1) and not pd.isna(g2):
                if g1 >= limit_up_gain and g2 >= limit_up_gain:
                    return True
        return False

    def _is_ma5_rising(self, df, c_idx, a_idx) -> bool:
        """校验 A 点→C 点期间 MA5 持续上升，不得下拐（笔记剔除规则⑦）

        倒序数据：从 a_idx（最早）走向 c_idx（最晚），MA5 应逐日非下降。
        允许单日微跌 ma5_rising_tolerance（默认 0.1%）以内的波动。
        """
        tolerance = float(self.params.get('ma5_rising_tolerance', 0.001))
        sma = df['sma_short'].values
        # 从最早（索引大）向最新（索引小）逐日检查
        for i in range(a_idx, c_idx, -1):
            prev_ma = sma[i]       # 前一交易日（时间更早）
            curr_ma = sma[i - 1]   # 当日（时间更晚）
            if pd.isna(prev_ma) or pd.isna(curr_ma):
                continue
            if prev_ma > 0 and (curr_ma - prev_ma) / prev_ma < -tolerance:
                return False
        return True

    def _is_low_position(self, df, c_idx) -> bool:
        """低位过滤：C日收盘相对 lookback_days 窗口内最低价的涨幅不能过大

        倒序数据：窗口为 [c_idx, c_idx + lookback_days]，即 C 日及之前 N 天。
        """
        max_rise = float(self.params.get('max_rise_from_low', 0.35))
        lookback = int(self.params.get('lookback_days', 30))
        end = min(c_idx + lookback + 1, len(df))
        window_low = df['low'].iloc[c_idx:end].min()
        if pd.isna(window_low) or window_low <= 0:
            return True  # 数据异常时不误杀
        rise = df.iloc[c_idx]['close'] / window_low - 1
        return rise <= max_rise

    def _calc_ma_slope(self, df, idx, ma_col, slope_days) -> Optional[float]:
        """计算均线近 slope_days 日变化率；数据不足返回 None（调用方跳过检查）

        倒序数据：idx + slope_days 为 idx 日前 slope_days 个交易日。
        """
        end_idx = idx + slope_days
        if end_idx >= len(df):
            return None
        ma_now = df[ma_col].iloc[idx]
        ma_then = df[ma_col].iloc[end_idx]
        if pd.isna(ma_now) or pd.isna(ma_then) or ma_then <= 0:
            return None
        return (ma_now - ma_then) / ma_then

    def _calc_triangle_height(self, c_day_data) -> Optional[float]:
        """三角形高度：C 点处三线（MA5/10/20）的最大相对离散度"""
        values = [c_day_data['sma_short'], c_day_data['sma_mid'], c_day_data['sma_long']]
        if any(pd.isna(v) for v in values):
            return None
        lo, hi = min(values), max(values)
        if lo <= 0:
            return None
        return (hi - lo) / lo

    def _calc_signal_strength(self, triangle_type, c_volume_ratio, ma_long_slope,
                              triangle_height, close, sma_super_long) -> float:
        """信号强度评分：基础 0.6，封顶 1.0"""
        strength = 0.6
        if triangle_type == 'golden_spider':
            strength += 0.15          # 金蜘蛛：三线共振，最强形态
        if c_volume_ratio >= 2.0:
            strength += 0.10          # 放量 2 倍以上
        if ma_long_slope is not None and ma_long_slope > 0:
            strength += 0.05          # MA20 已拐头向上
        if triangle_height is not None and triangle_height < 0.02:
            strength += 0.05          # 三角形高度收敛（经典理论：越矮越可靠）
        if not pd.isna(sma_super_long) and close >= sma_super_long:
            strength += 0.05          # 站上 MA60
        return round(min(strength, 1.0), 2)

    def _build_reason(self, triangle_type, ac_interval_days, c_gain,
                      c_volume_ratio, turnover_rate, ma_long_slope) -> str:
        """构建信号理由文本"""
        type_name = '金蜘蛛' if triangle_type == 'golden_spider' else '金三角'
        parts = [
            f'{type_name}形态(A→C间隔{ac_interval_days}天)',
            f'C日涨幅{c_gain*100:.1f}%',
            f'量比{c_volume_ratio:.1f}',
        ]
        if not pd.isna(turnover_rate):
            parts.append(f'换手{turnover_rate:.1f}%')
        if ma_long_slope is not None and ma_long_slope > 0:
            parts.append('MA20拐头向上')
        return '，'.join(parts)
