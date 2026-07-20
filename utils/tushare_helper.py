# -*- coding: utf-8 -*-
"""Tushare 全局 token 兜底加载

部分模块直接调用 ts.pro_api()（不带 token），依赖进程内已设置全局 token。
若进程启动后尚未有任何代码调用 ts.set_token()，pro_api() 会报 "api init error"。
本模块提供幂等的 ensure_tushare_token()，在裸调 pro_api() 前调用即可。
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_loaded = False


def ensure_tushare_token():
    """确保 tushare 全局 token 已从 config/tushare_config.json 加载（幂等）"""
    global _loaded
    if _loaded:
        return
    try:
        import tushare as ts
        # 已有全局 token 则无需重复设置
        try:
            if ts.get_token():
                _loaded = True
                return
        except Exception:
            pass
        cfg = Path(__file__).parent.parent / 'config' / 'tushare_config.json'
        if cfg.exists():
            with open(cfg, 'r', encoding='utf-8') as f:
                data = json.load(f)
            key = data.get('api_key') or data.get('token')
            if key:
                ts.set_token(key)
                logger.info("已从 tushare_config.json 加载全局 token")
        _loaded = True
    except Exception as e:
        logger.warning(f"加载 tushare token 失败: {e}")
