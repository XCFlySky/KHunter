# -*- coding: utf-8 -*-
"""申万行业板块映射加载器

背景：
    板块数据源原本依赖 Tushare 同花顺接口（ths_index/ths_member/ths_daily/
    moneyflow_cnt_ths），需要高积分权限。当前账号无权限，导致
    stock_sector / stock_sector_mapping 长期为空，板块名称解析失败（显示"未知"）。

方案：
    改用有权限的申万行业分类接口（index_classify + index_member，SW2021 二级行业）
    构建 股票→板块 映射，写入 stock_sector / stock_sector_mapping 表，
    供板块评分（sector_scorer）与排名（ranking_manager）解析板块名称。

刷新策略：
    板块成分变化极少，默认每周一刷新一次；映射表为空时强制刷新。
    全量约 134 个行业、5500+ 条映射，刷新耗时约 1 分钟（带限流间隔）。
"""

import json
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# index_member 调用间隔（秒），防止触发 Tushare 限流
_MEMBER_CALL_SLEEP = 0.35


def _load_tushare_pro():
    """从配置文件加载 Tushare pro API"""
    import tushare as ts
    with open("config/tushare_config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    token = config.get("token") or config.get("api_key", "")
    return ts.pro_api(token)


def needs_refresh(db_manager) -> bool:
    """判断是否需要刷新：映射表为空，或最近刷新日期早于本周一"""
    try:
        rows = db_manager.query(
            "SELECT MAX(mapping_date) AS latest, COUNT(*) AS cnt FROM stock_sector_mapping"
        )
        if not rows or not rows[0]['cnt']:
            return True
        latest = rows[0]['latest']
        if not latest:
            return True
        latest_date = datetime.strptime(latest, '%Y-%m-%d').date()
        today = datetime.now().date()
        monday = today.fromordinal(today.toordinal() - today.weekday())
        return latest_date < monday
    except Exception as e:
        logger.warning(f"检查板块映射刷新状态失败: {e}")
        return True


def refresh_sw_sector_mapping(db_manager, force: bool = False) -> dict:
    """从申万行业分类刷新 股票→板块 映射

    参数：
        db_manager: 数据库管理器
        force: 为 True 时忽略刷新策略强制全量刷新

    返回：
        统计信息 dict
    """
    if not force and not needs_refresh(db_manager):
        logger.info("板块映射本周已刷新，跳过")
        return {'success': True, 'skipped': True}

    logger.info("开始刷新申万行业板块映射...")
    pro = _load_tushare_pro()

    # 1. 获取申万二级行业分类
    df = pro.index_classify(level='L2', src='SW2021')
    if df is None or df.empty:
        raise RuntimeError("获取申万行业分类失败：index_classify 返回空")

    today = datetime.now().strftime('%Y-%m-%d')
    sectors = []   # (sector_code, sector_name, stock_count)
    mappings = []  # (stock_code, sector_code)

    total = len(df)
    for i, row in df.iterrows():
        index_code = row['index_code']
        industry_name = row['industry_name']
        try:
            members = pro.index_member(index_code=index_code)
        except Exception as e:
            logger.warning(f"获取行业成分失败 {index_code} {industry_name}: {e}")
            time.sleep(_MEMBER_CALL_SLEEP)
            continue
        count = 0
        if members is not None and not members.empty:
            for con_code in members['con_code'].unique():
                stock_code = str(con_code).split('.')[0]
                mappings.append((stock_code, index_code))
                count += 1
        sectors.append((index_code, industry_name, count))
        if (i + 1) % 20 == 0:
            logger.info(f"板块映射刷新进度: {i + 1}/{total}")
        time.sleep(_MEMBER_CALL_SLEEP)

    # 2. 全量替换写入数据库
    conn = db_manager.connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stock_sector_mapping")
    cursor.execute("DELETE FROM stock_sector")
    cursor.executemany(
        "INSERT INTO stock_sector (sector_code, sector_name, sector_type, stock_count, created_date, updated_date)"
        " VALUES (?, ?, 'SW', ?, ?, ?)",
        [(code, name, cnt, today, today) for code, name, cnt in sectors])
    cursor.executemany(
        "INSERT INTO stock_sector_mapping (stock_code, sector_code, mapping_date, created_date)"
        " VALUES (?, ?, ?, ?)",
        [(sc, sec, today, today) for sc, sec in mappings])
    conn.commit()

    stats = {'success': True, 'sectors': len(sectors), 'mappings': len(mappings)}
    logger.info(f"申万行业板块映射刷新完成: {stats['sectors']} 个行业, {stats['mappings']} 条映射")
    return stats
