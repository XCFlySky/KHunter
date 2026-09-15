# -*- coding: utf-8 -*-
"""
企业微信群机器人通知模块

用于每日选股结果 / 模拟盘结算的推送。

Webhook 属于密钥，不进 Git。按以下优先级读取：
  1. 环境变量 KHUNTER_WECHAT_WEBHOOK
  2. config/notify.local.yaml（已 gitignore，服务器/本机各自维护）：
       wechat_webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  3. config/config.yaml 的 notify.wechat_webhook 节（不推荐放主配置）

企业微信 markdown 消息仅支持有限语法（标题/加粗/链接/列表/字体颜色），
单条消息不超过 4096 字节，超长内容需截断。
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 10
MAX_BYTES = 3800  # 留余量，官方上限 4096 字节


def load_webhook() -> Optional[str]:
    """按优先级读取企业微信 webhook 地址"""
    url = os.environ.get('KHUNTER_WECHAT_WEBHOOK', '').strip()
    if url:
        return url

    root = Path(__file__).resolve().parent.parent
    local_cfg = root / 'config' / 'notify.local.yaml'
    if local_cfg.exists():
        try:
            import yaml
            with open(local_cfg, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            url = str(cfg.get('wechat_webhook', '')).strip()
            if url:
                return url
        except Exception as e:
            logger.warning(f"读取 notify.local.yaml 失败: {e}")

    try:
        import yaml
        main_cfg = root / 'config' / 'config.yaml'
        with open(main_cfg, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        url = str((cfg.get('notify') or {}).get('wechat_webhook', '')).strip()
        return url or None
    except Exception as e:
        logger.warning(f"读取 config.yaml notify 配置失败: {e}")
        return None


def _truncate_bytes(text: str, max_bytes: int = MAX_BYTES) -> str:
    """按 UTF-8 字节数截断（不断多字节字符）"""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode('utf-8', errors='ignore') + '\n…（内容过长已截断）'


def send_markdown(content: str, webhook: str = None) -> bool:
    """发送 markdown 消息到企业微信群

    Returns:
        bool: 是否发送成功
    """
    url = (webhook or load_webhook() or '').strip()
    if not url:
        logger.warning("未配置企业微信 webhook（KHUNTER_WECHAT_WEBHOOK 或 config/notify.local.yaml），跳过推送")
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": _truncate_bytes(content)}
    }
    try:
        resp = requests.post(url, json=payload, timeout=TIMEOUT)
        data = resp.json()
        if data.get('errcode') == 0:
            logger.info("企业微信推送成功")
            return True
        logger.error(f"企业微信推送失败: errcode={data.get('errcode')}, errmsg={data.get('errmsg')}")
        return False
    except Exception as e:
        logger.error(f"企业微信推送异常: {e}")
        return False


def build_daily_message(trade_date: str, signals: list, sim_summary: dict = None,
                        web_url: str = None) -> str:
    """构建每日推送内容（选股结果 + 模拟盘结算摘要）

    Args:
        trade_date: 交易日
        signals: 选股结果 [{'code','name','strategies',...}]
        sim_summary: 模拟盘结算摘要（SimAccount.run_daily 返回），可为 None
        web_url: Web 系统地址（消息末尾附详情链接）
    """
    lines = [f"## 📅 KHunter 每日选股 {trade_date}", ""]

    # ---- 选股结果 ----
    if signals:
        lines.append(f"**今日选出 <font color=\"info\">{len(signals)}</font> 只：**")
        # 被更多策略选中的排前面
        ranked = sorted(signals,
                        key=lambda s: (len(s.get('strategies', [])), len(s.get('signals', []))),
                        reverse=True)
        for sig in ranked[:15]:
            strategies = '+'.join(sig.get('strategies', []))
            lines.append(f"> {sig['code']} {sig.get('name', '')}　<font color=\"comment\">{strategies}</font>")
        if len(ranked) > 15:
            lines.append(f"> ……等共 {len(ranked)} 只")
    else:
        lines.append("**今日无选股结果**")
    lines.append("")

    # ---- 模拟盘结算 ----
    if sim_summary and not sim_summary.get('skipped'):
        lines.append("**💰 模拟盘**")
        lines.append(f"> 总资产 ¥{sim_summary.get('total_assets', 0):,.2f}"
                     f"（累计收益 {sim_summary.get('cum_return', 0) * 100:+.2f}%）")
        lines.append(f"> 今日成交：买 {sim_summary.get('filled_buys', 0)} / 卖 {sim_summary.get('filled_sells', 0)}"
                     f"　持仓 {sim_summary.get('positions', 0)} 只"
                     f"　待执行 买{sim_summary.get('new_buy_orders', 0)}/卖{sim_summary.get('new_sell_orders', 0)}")
        lines.append("")

    if web_url:
        lines.append(f"[📊 查看详情]({web_url})")

    return '\n'.join(lines)


def send_daily_notification(trade_date: str, signals: list, sim_summary: dict = None,
                            web_url: str = None) -> bool:
    """构建并发送每日推送"""
    content = build_daily_message(trade_date, signals, sim_summary, web_url)
    return send_markdown(content)
