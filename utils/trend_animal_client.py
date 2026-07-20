"""
趋势动物 API 客户端

封装趋势动物（TrendAnimal）HTTP API：
- apiKey 仅从 config/trend_animal_config.json 读取，不出现在日志/返回值中
- 按接口限流（文档：1次/s 或 5次/s）
- tmId 本地缓存（data/trend_tmid_cache.json），避免重复 searchTicker 扣费

接口/参数/计费以官方文档实时返回为准（getApiDocIntro）。
"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

CONFIG_PATH = Path('config/trend_animal_config.json')
TMID_CACHE_PATH = Path('data/trend_tmid_cache.json')

# 接口限流（次/秒），以官方接口文档为准
RATE_LIMITS = {
    'getUpdateStatus': 1, 'getApiDocIntro': 1, 'getAccountBalance': 1,
    'getChangeLog': 1, 'getFavoritesCategory': 1, 'getFavoritesTicker': 1,
    'getSnapshotColumnBilling': 1, 'postApiFeedback': 1,
    'searchTicker': 5, 'getComponentTicker': 5, 'getTickerSnapshot': 5,
    'getTickerTrendPlot': 5,
}


class TrendAnimalClient:
    """趋势动物 API 客户端"""

    def __init__(self, config_path: str = None):
        self.api_key = ''
        self.base_url = 'https://www.trendtrader.cn/apiData/data'
        self.timeout = 20
        self._load_config(config_path or str(CONFIG_PATH))
        self._rate_lock = threading.Lock()
        self._last_call = {}  # api_name -> timestamp
        self._tmid_cache = self._load_tmid_cache()

    # -------------------- 配置与缓存 --------------------
    def _load_config(self, path: str):
        try:
            p = Path(path)
            if p.exists():
                with open(p, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.api_key = cfg.get('api_key', '')
                self.base_url = cfg.get('base_url', self.base_url).rstrip('/')
                self.timeout = int(cfg.get('timeout', self.timeout))
        except Exception as e:
            logger.warning(f"趋势动物配置加载失败: {e}")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def update_api_key(self, api_key: str, persist: bool = True):
        """更新 apiKey 并持久化到配置文件（运行时生效，无需重启服务）"""
        api_key = (api_key or '').strip()
        self.api_key = api_key
        if persist:
            cfg = {}
            p = Path(CONFIG_PATH)
            try:
                if p.exists():
                    with open(p, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
            except Exception:
                cfg = {}
            cfg['api_key'] = api_key
            cfg.setdefault('base_url', self.base_url)
            cfg.setdefault('timeout', self.timeout)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        logger.info('趋势动物 apiKey 已更新（日志不记录密钥内容）')

    def masked_key(self) -> str:
        """返回打码后的密钥（仅用于界面显示）"""
        if not self.api_key:
            return ''
        if len(self.api_key) <= 10:
            return self.api_key[:2] + '****'
        return f"{self.api_key[:6]}****{self.api_key[-4:]}"

    def _load_tmid_cache(self) -> Dict[str, int]:
        try:
            if TMID_CACHE_PATH.exists():
                with open(TMID_CACHE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_tmid_cache(self):
        try:
            TMID_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TMID_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._tmid_cache, f, ensure_ascii=False, indent=1)
        except Exception as e:
            logger.debug(f"tmId缓存保存失败: {e}")

    # -------------------- 基础调用 --------------------
    def _throttle(self, api_name: str):
        limit = RATE_LIMITS.get(api_name, 1)
        min_interval = 1.0 / limit
        with self._rate_lock:
            last = self._last_call.get(api_name, 0)
            wait = min_interval - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_call[api_name] = time.time()

    def _call(self, api_name: str, params: dict = None) -> dict:
        """统一调用入口。返回原始JSON；失败时返回 {'_error': msg}"""
        if not self.configured:
            return {'_error': '未配置趋势动物API Key（config/trend_animal_config.json）'}
        self._throttle(api_name)
        url = f"{self.base_url}/{api_name}"
        query = {'apiKey': self.api_key}
        if params:
            query.update(params)
        try:
            resp = requests.get(url, params=query, timeout=self.timeout)
            data = resp.json()
            # 日志不记录 URL（含 apiKey）
            code = data.get('code')
            if code != '00000':
                logger.warning(f"趋势动物 {api_name} 返回异常: code={code} msg={data.get('msg')}")
            return data
        except Exception as e:
            logger.warning(f"趋势动物 {api_name} 调用失败: {e}")
            return {'_error': str(e)}

    @staticmethod
    def ok(data: dict) -> bool:
        return isinstance(data, dict) and data.get('code') == '00000' and data.get('success')

    # -------------------- 免费接口 --------------------
    def get_update_status(self) -> dict:
        return self._call('getUpdateStatus')

    def get_account_balance(self, view_level: str = 'summary') -> dict:
        return self._call('getAccountBalance', {'viewLevel': view_level})

    def get_column_billing(self) -> dict:
        return self._call('getSnapshotColumnBilling')

    def get_favorites_category(self) -> dict:
        return self._call('getFavoritesCategory')

    def get_favorites_ticker(self, fav_category: str = None) -> dict:
        params = {'favCategory': fav_category} if fav_category else None
        return self._call('getFavoritesTicker', params)

    # -------------------- 付费接口 --------------------
    def search_ticker(self, keyword: str) -> dict:
        return self._call('searchTicker', {'keyword': keyword})

    def get_component_ticker(self, tm_id: int, get_all_basic: bool = False) -> dict:
        params = {'tmId': tm_id}
        if get_all_basic:
            params['getAllBasicComponentsFlag'] = 1
        return self._call('getComponentTicker', params)

    def get_snapshot(self, tm_ids: List[int], fields: List[str] = None) -> dict:
        params = {'tmIds': ','.join(str(t) for t in tm_ids)}
        if fields:
            params['fields'] = ','.join(fields)
        return self._call('getTickerSnapshot', params)

    def get_trend_plot(self, tm_id: int, seq: int = 1, selected: int = 1,
                       color_id: int = 0, order_type: int = 3, trend_scale: int = 1) -> dict:
        return self._call('getTickerTrendPlot', {
            'tmId': tm_id, 'seq': seq, 'selected': selected,
            'colorId': color_id, 'orderType': order_type, 'trendScale': trend_scale
        })

    # -------------------- tmId 映射（带缓存） --------------------
    def resolve_tmid(self, code: str, name: str = '') -> Optional[int]:
        """股票代码 → tmId，优先本地缓存，未命中调 searchTicker（0.01元/次）"""
        code = str(code).strip()
        if code in self._tmid_cache:
            return self._tmid_cache[code]

        # 搜索关键词：优先用带后缀的代码（如 600519.SH），其次纯代码，最后名称
        suffix = '.SH' if code.startswith(('6', '9')) else '.SZ'
        candidates = [f"{code}{suffix}", code] + ([name] if name else [])
        for kw in candidates:
            result = self.search_ticker(kw)
            if not self.ok(result):
                continue
            for item in result.get('data') or []:
                symbol = str(item.get('tickerSymbol') or '')
                if symbol.startswith(code):
                    tmid = item.get('tmId')
                    if tmid:
                        self._tmid_cache[code] = int(tmid)
                        self._save_tmid_cache()
                        return int(tmid)
        logger.debug(f"未能解析tmId: {code} {name}")
        return None

    def resolve_tmids(self, stocks: List[Dict]) -> Dict[str, int]:
        """批量解析：[{code, name}] -> {code: tmId}"""
        mapping = {}
        for s in stocks:
            code = str(s.get('code', '')).strip()
            if not code:
                continue
            tmid = self.resolve_tmid(code, s.get('name', ''))
            if tmid:
                mapping[code] = tmid
        return mapping


# 全局单例
_client = None
_client_lock = threading.Lock()


def get_trend_client(force_reload: bool = False) -> TrendAnimalClient:
    global _client
    if _client is None or force_reload:
        with _client_lock:
            if _client is None or force_reload:
                _client = TrendAnimalClient()
    return _client
