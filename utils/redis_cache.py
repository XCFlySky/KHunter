# -*- coding: utf-8 -*-
"""Redis API 缓存层

用途：为 Web 查询类接口（首页速览/市场温度/列表等）提供响应缓存。

特性：
- 优先使用 Redis（跨进程共享、服务重启后缓存仍在）
- Redis 不可用时自动降级为进程内 TTL 缓存，并定期尝试重连
- 所有键统一前缀（默认 khunter:api:），支持一键失效
- 配置读取 config/config.yaml 的 redis 节，可用环境变量覆盖：
  KHUNTER_REDIS_HOST / KHUNTER_REDIS_PORT / KHUNTER_REDIS_PASSWORD / KHUNTER_REDIS_DB
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Redis 断线后的重连间隔（秒）
_RECONNECT_INTERVAL = 30
# 进程内降级缓存的最大条目数（超出后淘汰最旧条目）
_FALLBACK_MAX_ENTRIES = 1000
# Redis 操作超时（秒），避免慢节点拖垮接口
_SOCKET_TIMEOUT = 2


class RedisApiCache:
    """Redis 缓存（带进程内降级）"""

    def __init__(self):
        self._client = None
        self._redis_ok = False
        self._last_connect_try = 0.0
        self._connect_lock = threading.Lock()
        self._fallback = {}
        self._fallback_lock = threading.Lock()
        self._load_config()

    # ---------- 配置与连接 ----------

    def _load_config(self):
        cfg = {}
        try:
            import yaml
            cfg_path = Path('config/config.yaml')
            if cfg_path.exists():
                with open(cfg_path, encoding='utf-8') as f:
                    cfg = (yaml.safe_load(f) or {}).get('redis', {}) or {}
        except Exception as e:
            logger.warning(f"读取 redis 配置失败，使用默认配置: {e}")

        self._enabled = bool(cfg.get('enabled', True))
        self._host = os.environ.get('KHUNTER_REDIS_HOST') or cfg.get('host', '127.0.0.1')
        self._port = int(os.environ.get('KHUNTER_REDIS_PORT') or cfg.get('port', 6379))
        self._db = int(os.environ.get('KHUNTER_REDIS_DB') or cfg.get('db', 0))
        self._password = os.environ.get('KHUNTER_REDIS_PASSWORD') or cfg.get('password') or None
        self._prefix = cfg.get('key_prefix', 'khunter') + ':api:'

    def _ensure_client(self):
        """按需建立/恢复 Redis 连接（带重连节流）"""
        if not self._enabled:
            return None
        if self._redis_ok and self._client is not None:
            return self._client
        now = time.time()
        if now - self._last_connect_try < _RECONNECT_INTERVAL:
            return None
        with self._connect_lock:
            if self._redis_ok and self._client is not None:
                return self._client
            self._last_connect_try = now
            try:
                import redis
                client = redis.Redis(
                    host=self._host, port=self._port, db=self._db,
                    password=self._password,
                    socket_timeout=_SOCKET_TIMEOUT,
                    socket_connect_timeout=_SOCKET_TIMEOUT,
                )
                client.ping()
                self._client = client
                self._redis_ok = True
                logger.info(f"Redis 缓存已连接: {self._host}:{self._port}/db{self._db}")
            except Exception as e:
                self._client = None
                self._redis_ok = False
                logger.warning(f"Redis 不可用，降级为进程内缓存: {e}")
        return self._client if self._redis_ok else None

    def _on_redis_error(self, e):
        logger.warning(f"Redis 操作失败，临时降级为进程内缓存: {e}")
        self._redis_ok = False
        self._client = None

    # ---------- 键与序列化 ----------

    def _full_key(self, key: str) -> str:
        return self._prefix + key

    # ---------- 对外接口 ----------

    def get(self, key: str):
        """获取缓存值（字符串），不存在返回 None"""
        client = self._ensure_client()
        if client is not None:
            try:
                value = client.get(self._full_key(key))
                if value is not None:
                    return value.decode('utf-8')
                return None
            except Exception as e:
                self._on_redis_error(e)
        # 降级：进程内缓存
        now = time.time()
        with self._fallback_lock:
            entry = self._fallback.get(key)
            if entry and now - entry['ts'] < entry['ttl']:
                return entry['value']
            if entry:
                self._fallback.pop(key, None)
        return None

    def set(self, key: str, value: str, ttl: int):
        """写入缓存"""
        client = self._ensure_client()
        if client is not None:
            try:
                client.setex(self._full_key(key), ttl, value)
                return
            except Exception as e:
                self._on_redis_error(e)
        # 降级：进程内缓存
        with self._fallback_lock:
            if len(self._fallback) >= _FALLBACK_MAX_ENTRIES:
                oldest = min(self._fallback, key=lambda k: self._fallback[k]['ts'])
                self._fallback.pop(oldest, None)
            self._fallback[key] = {'ts': time.time(), 'ttl': ttl, 'value': value}

    def clear(self):
        """清空本应用的所有 API 缓存（数据更新/结果保存后调用）"""
        client = self._ensure_client()
        if client is not None:
            try:
                keys = list(client.scan_iter(match=self._full_key('*'), count=500))
                if keys:
                    client.delete(*keys)
                logger.info(f"Redis API 缓存已清空（{len(keys)} 个键）")
            except Exception as e:
                self._on_redis_error(e)
        with self._fallback_lock:
            self._fallback.clear()

    def backend(self) -> str:
        """当前缓存后端：redis / memory（用于健康检查）"""
        return 'redis' if self._ensure_client() is not None else 'memory'

    def stats(self) -> dict:
        """缓存状态信息（用于健康检查接口）"""
        info = {'backend': self.backend(), 'prefix': self._prefix}
        client = self._ensure_client()
        if client is not None:
            try:
                info['keys'] = sum(1 for _ in client.scan_iter(match=self._full_key('*'), count=500))
            except Exception as e:
                self._on_redis_error(e)
                info['keys'] = -1
        else:
            with self._fallback_lock:
                info['keys'] = len(self._fallback)
        return info


# 全局单例
api_cache = RedisApiCache()
