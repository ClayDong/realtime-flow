"""
数据模型 + SQLite DAO
架构专家视角：
- 分表存储，按时间分区
- 支持自动清理
- 运维专家：表结构设计合理，字段命名规范
"""
import sqlite3
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

from config import CONFIG

logger = logging.getLogger(__name__)


def get_db_path() -> str:
    return CONFIG.storage.DB_PATH


@contextmanager
def get_conn():
    """获取数据库连接（上下文管理器）"""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class Database:
    """数据库操作层"""

    def __init__(self):
        self._init_tables()

    def _init_tables(self):
        """初始化表结构 - 架构专家：设计合理的主键和索引"""
        with get_conn() as conn:
            # 大盘资金流日表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_flow (
                    date TEXT PRIMARY KEY,
                    sh_close REAL,
                    sh_change REAL,
                    sz_close REAL,
                    sz_change REAL,
                    main_net_inflow REAL,
                    main_net_ratio REAL,
                    super_large_inflow REAL,
                    large_inflow REAL,
                    medium_inflow REAL,
                    small_inflow REAL,
                    north_bound_total REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 行业资金流快照表（每次采集记录）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sector_flow_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sector_name TEXT NOT NULL,
                    tag TEXT DEFAULT '今日',
                    rank_idx INTEGER,
                    current_price REAL,
                    price_change REAL,
                    main_net_inflow REAL,
                    main_net_ratio REAL,
                    super_large_inflow REAL,
                    large_inflow REAL,
                    medium_inflow REAL,
                    small_inflow REAL,
                    raw_json TEXT
                )
            """)
            # 索引：按快照时间查询
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sector_snapshot_time 
                ON sector_flow_snapshot(snapshot_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sector_name_tag 
                ON sector_flow_snapshot(sector_name, tag)
            """)

            # 概念资金流快照表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS concept_flow_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    concept_name TEXT NOT NULL,
                    rank_idx INTEGER,
                    current_price REAL,
                    price_change REAL,
                    main_net_inflow REAL,
                    main_net_ratio REAL,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_concept_snapshot_time 
                ON concept_flow_snapshot(snapshot_time)
            """)

            # 个股资金流排行快照表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_flow_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    tag TEXT DEFAULT '今日',
                    rank_idx INTEGER,
                    current_price REAL,
                    price_change REAL,
                    main_net_inflow REAL,
                    main_net_ratio REAL,
                    super_large_inflow REAL,
                    large_inflow REAL,
                    medium_inflow REAL,
                    small_inflow REAL,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stock_snapshot_time 
                ON stock_flow_snapshot(snapshot_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_stock_code_tag 
                ON stock_flow_snapshot(stock_code, tag)
            """)

            # 信号/预警表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    signal_type TEXT NOT NULL,
                    signal_name TEXT,
                    stock_code TEXT,
                    stock_name TEXT,
                    sector_name TEXT,
                    value REAL,
                    description TEXT,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_time
                ON signals(signal_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signal_type
                ON signals(signal_type)
            """)

            # 自选股表（支持 UI 增删改）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL UNIQUE,
                    market TEXT NOT NULL,
                    display_name TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sort_order INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_watchlist_code
                ON watchlist(stock_code)
            """)

            logger.info("数据库表初始化完成")

    # ─── 大盘 ─────────────────────────────────────────

    def save_market_flow(self, data: Dict):
        """保存大盘资金流"""
        with get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO market_flow
                (date, sh_close, sh_change, sz_close, sz_change,
                 main_net_inflow, main_net_ratio,
                 super_large_inflow, large_inflow, medium_inflow, small_inflow,
                 north_bound_total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("date"),
                data.get("sh_close"), data.get("sh_change"),
                data.get("sz_close"), data.get("sz_change"),
                data.get("main_net_inflow"), data.get("main_net_ratio"),
                data.get("super_large_inflow"), data.get("large_inflow"),
                data.get("medium_inflow"), data.get("small_inflow"),
                data.get("north_bound_total"),
            ))

    def get_market_flow_recent(self, days: int = 30) -> List[Dict]:
        """获取最近N天的大盘资金流"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM market_flow 
                ORDER BY date DESC LIMIT ?
            """, (days,)).fetchall()
            return [dict(r) for r in rows]

    # ─── 行业快照 ─────────────────────────────────────

    def save_sector_snapshot(self, records: List[Dict], tag: str = "今日"):
        """保存行业资金流快照"""
        with get_conn() as conn:
            for i, rec in enumerate(records):
                sector_name = str(rec.get(f"行业名称", rec.get("板块名称", f"未知行业_{i}")))
                raw_json = json.dumps(rec, ensure_ascii=False)
                conn.execute("""
                    INSERT INTO sector_flow_snapshot
                    (sector_name, tag, rank_idx, current_price, price_change,
                     main_net_inflow, main_net_ratio,
                     super_large_inflow, large_inflow, medium_inflow, small_inflow,
                     raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sector_name,
                    tag,
                    i + 1,
                    self._safe_float(rec.get("最新价", rec.get("f2", 0))),
                    self._safe_float(rec.get("涨跌幅", rec.get("f3", 0))),
                    self._safe_float(rec.get("主力净流入-净额", rec.get("f62", 0))),
                    self._safe_float(rec.get("主力净流入-净占比", rec.get("f184", 0))),
                    self._safe_float(rec.get("超大单净流入-净额", rec.get("f66", 0))),
                    self._safe_float(rec.get("大单净流入-净额", rec.get("f69", 0))),
                    self._safe_float(rec.get("中单净流入-净额", rec.get("f72", 0))),
                    self._safe_float(rec.get("小单净流入-净额", rec.get("f78", 0))),
                    raw_json,
                ))

    def get_latest_sector_snapshot(self, tag: str = "今日") -> List[Dict]:
        """获取最新的行业快照（去重按行业名取最新）"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT s.* FROM sector_flow_snapshot s
                INNER JOIN (
                    SELECT sector_name, MAX(snapshot_time) as max_time
                    FROM sector_flow_snapshot
                    WHERE tag = ?
                    GROUP BY sector_name
                ) latest ON s.sector_name = latest.sector_name
                    AND s.snapshot_time = latest.max_time
                WHERE s.tag = ?
                ORDER BY s.rank_idx ASC
            """, (tag, tag)).fetchall()
            return [dict(r) for r in rows]

    def get_sector_history(self, sector_name: str, days: int = 30) -> List[Dict]:
        """获取某行业的历史资金流时间序列（本地 DB）"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT snapshot_time, sector_name, tag, rank_idx, current_price,
                       price_change, main_net_inflow, main_net_ratio,
                       super_large_inflow, large_inflow, medium_inflow, small_inflow
                FROM sector_flow_snapshot
                WHERE sector_name = ? AND snapshot_time >= ?
                ORDER BY snapshot_time ASC
            """, (sector_name, cutoff)).fetchall()
            return [dict(r) for r in rows]

    def get_sector_daily_history(self, sector_name: str, days: int = 30) -> List[Dict]:
        """获取某行业的日级聚合历史（按天取最后一条快照）"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT date(snapshot_time) as date, sector_name,
                       MAX(snapshot_time) as last_time,
                       AVG(main_net_inflow) as avg_main_inflow,
                       main_net_inflow as last_main_inflow,
                       main_net_ratio as last_main_ratio,
                       price_change as last_price_change
                FROM sector_flow_snapshot
                WHERE sector_name = ? AND snapshot_time >= ? AND tag = '今日'
                GROUP BY date(snapshot_time), sector_name
                ORDER BY date ASC
            """, (sector_name, cutoff)).fetchall()
            return [dict(r) for r in rows]

    def get_sector_list(self) -> List[str]:
        """获取所有采集过的行业名（用于历史查询下拉框）"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT sector_name FROM sector_flow_snapshot
                WHERE tag = '今日'
                ORDER BY sector_name
            """).fetchall()
            return [r["sector_name"] for r in rows]

    # ─── 个股快照 ─────────────────────────────────────

    def save_stock_snapshot(self, records: List[Dict], tag: str = "今日"):
        """保存个股资金流快照"""
        with get_conn() as conn:
            for i, rec in enumerate(records):
                code = str(rec.get("代码", rec.get("f12", f"unknown_{i}")))
                name = str(rec.get("名称", rec.get("f14", "")))
                raw_json = json.dumps(rec, ensure_ascii=False)
                conn.execute("""
                    INSERT INTO stock_flow_snapshot
                    (stock_code, stock_name, tag, rank_idx, current_price, price_change,
                     main_net_inflow, main_net_ratio,
                     super_large_inflow, large_inflow, medium_inflow, small_inflow,
                     raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    code, name, tag, i + 1,
                    self._safe_float(rec.get("最新价", rec.get("f2", 0))),
                    self._safe_float(rec.get("涨跌幅", rec.get("f3", 0))),
                    self._safe_float(rec.get("主力净流入-净额", rec.get("f62", 0))),
                    self._safe_float(rec.get("主力净流入-净占比", rec.get("f184", 0))),
                    self._safe_float(rec.get("超大单净流入-净额", rec.get("f66", 0))),
                    self._safe_float(rec.get("大单净流入-净额", rec.get("f69", 0))),
                    self._safe_float(rec.get("中单净流入-净额", rec.get("f72", 0))),
                    self._safe_float(rec.get("小单净流入-净额", rec.get("f78", 0))),
                    raw_json,
                ))

    def get_latest_stock_snapshot(self, tag: str = "今日", top_n: int = 50) -> List[Dict]:
        """获取最新的个股排行快照"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT s.* FROM stock_flow_snapshot s
                INNER JOIN (
                    SELECT stock_code, MAX(snapshot_time) as max_time
                    FROM stock_flow_snapshot
                    WHERE tag = ?
                    GROUP BY stock_code
                ) latest ON s.stock_code = latest.stock_code
                    AND s.snapshot_time = latest.max_time
                WHERE s.tag = ?
                ORDER BY s.rank_idx ASC
                LIMIT ?
            """, (tag, tag, top_n)).fetchall()
            return [dict(r) for r in rows]

    def get_stock_history(self, stock_code: str, days: int = 30) -> List[Dict]:
        """获取某只个股的历史资金流时间序列（本地 DB）"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT snapshot_time, stock_code, stock_name, tag, rank_idx,
                       current_price, price_change, main_net_inflow, main_net_ratio,
                       super_large_inflow, large_inflow, medium_inflow, small_inflow
                FROM stock_flow_snapshot
                WHERE stock_code = ? AND snapshot_time >= ?
                ORDER BY snapshot_time ASC
            """, (stock_code, cutoff)).fetchall()
            return [dict(r) for r in rows]

    def get_stock_daily_history(self, stock_code: str, days: int = 30) -> List[Dict]:
        """获取某只个股的日级聚合历史"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT date(snapshot_time) as date, stock_code, stock_name,
                       MAX(snapshot_time) as last_time,
                       AVG(main_net_inflow) as avg_main_inflow,
                       main_net_inflow as last_main_inflow,
                       main_net_ratio as last_main_ratio,
                       price_change as last_price_change,
                       current_price as last_price
                FROM stock_flow_snapshot
                WHERE stock_code = ? AND snapshot_time >= ? AND tag = '今日'
                GROUP BY date(snapshot_time), stock_code
                ORDER BY date ASC
            """, (stock_code, cutoff)).fetchall()
            return [dict(r) for r in rows]

    def get_stock_list(self, top_n: int = 200) -> List[Dict]:
        """获取最近采集过的个股列表（用于历史查询下拉框）"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT s.stock_code, s.stock_name
                FROM stock_flow_snapshot s
                INNER JOIN (
                    SELECT stock_code, MAX(snapshot_time) as max_time
                    FROM stock_flow_snapshot WHERE tag = '今日'
                    GROUP BY stock_code
                ) latest ON s.stock_code = latest.stock_code
                    AND s.snapshot_time = latest.max_time
                WHERE s.tag = '今日'
                ORDER BY s.rank_idx ASC
                LIMIT ?
            """, (top_n,)).fetchall()
            return [dict(r) for r in rows]

    def get_market_flow_history(self, days: int = 30) -> List[Dict]:
        """获取大盘资金流历史（按日）"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT date, sh_close, sh_change, sz_close, sz_change,
                       main_net_inflow, main_net_ratio,
                       super_large_inflow, large_inflow, medium_inflow, small_inflow,
                       north_bound_total
                FROM market_flow
                ORDER BY date DESC LIMIT ?
            """, (days,)).fetchall()
            return [dict(r) for r in rows]

    # ─── 概念快照 ─────────────────────────────────────

    def save_concept_snapshot(self, records: List[Dict]):
        """保存概念资金流快照"""
        with get_conn() as conn:
            for i, rec in enumerate(records):
                name = str(rec.get(f"概念名称", rec.get("板块名称", f"未知概念_{i}")))
                raw_json = json.dumps(rec, ensure_ascii=False)
                conn.execute("""
                    INSERT INTO concept_flow_snapshot
                    (concept_name, rank_idx, current_price, price_change,
                     main_net_inflow, main_net_ratio, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    name, i + 1,
                    self._safe_float(rec.get("最新价", rec.get("f2", 0))),
                    self._safe_float(rec.get("涨跌幅", rec.get("f3", 0))),
                    self._safe_float(rec.get("主力净流入-净额", rec.get("f62", 0))),
                    self._safe_float(rec.get("主力净流入-净占比", rec.get("f184", 0))),
                    raw_json,
                ))

    # ─── 信号 ─────────────────────────────────────────

    def save_signal(self, signal_type: str, signal_name: str,
                    description: str, value: float = 0,
                    stock_code: str = "", stock_name: str = "",
                    sector_name: str = "", raw_data: Dict = None):
        """保存分析信号/预警（同日去重，避免每次轮询都写入重复信号）"""
        with get_conn() as conn:
            # 去重检查：同一天同类型同名称同板块的信号不重复写入
            existing = conn.execute("""
                SELECT id FROM signals
                WHERE signal_type = ? AND signal_name = ? AND sector_name = ?
                  AND date(signal_time) = date('now', 'localtime')
                LIMIT 1
            """, (signal_type, signal_name, sector_name)).fetchone()
            if existing:
                return  # 已存在，跳过

            conn.execute("""
                INSERT INTO signals
                (signal_type, signal_name, stock_code, stock_name,
                 sector_name, value, description, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_type, signal_name, stock_code, stock_name,
                sector_name, value, description,
                json.dumps(raw_data, ensure_ascii=False) if raw_data else None,
            ))

    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        """获取最近信号"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM signals
                ORDER BY signal_time DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ─── 自选股管理 ───────────────────────────────────

    def get_watchlist(self) -> List[Dict]:
        """获取自选股列表（按 sort_order 排序）"""
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT stock_code, market, display_name, sort_order
                FROM watchlist
                ORDER BY sort_order ASC, added_at ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def add_watchlist(self, stock_code: str, market: str, display_name: str = "") -> bool:
        """添加自选股（已存在则忽略）"""
        with get_conn() as conn:
            # 检查是否已存在
            existing = conn.execute(
                "SELECT id FROM watchlist WHERE stock_code = ?", (stock_code,)
            ).fetchone()
            if existing:
                return False
            # 取最大 sort_order
            max_order = conn.execute(
                "SELECT MAX(sort_order) FROM watchlist"
            ).fetchone()[0] or 0
            conn.execute("""
                INSERT INTO watchlist (stock_code, market, display_name, sort_order)
                VALUES (?, ?, ?, ?)
            """, (stock_code, market, display_name, max_order + 1))
            return True

    def remove_watchlist(self, stock_code: str) -> bool:
        """删除自选股"""
        with get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM watchlist WHERE stock_code = ?", (stock_code,)
            )
            return cursor.rowcount > 0

    def init_watchlist_if_empty(self, default_list: list):
        """如果 watchlist 表为空，用默认列表初始化"""
        with get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
            if count > 0:
                return
            for i, (code, market, name) in enumerate(default_list):
                conn.execute("""
                    INSERT INTO watchlist (stock_code, market, display_name, sort_order)
                    VALUES (?, ?, ?, ?)
                """, (code, market, name, i + 1))
            logger.info(f"自选股表初始化: {len(default_list)} 只")

    # ─── 维护 ─────────────────────────────────────────

    def cleanup_old_data(self):
        """清理旧数据 - 运维专家：控制磁盘空间"""
        if not CONFIG.storage.AUTO_CLEANUP:
            return
        cutoff = (datetime.now() - timedelta(days=CONFIG.storage.RETENTION_DAYS)).isoformat()
        with get_conn() as conn:
            # 快照表使用 snapshot_time 字段
            for table in ["sector_flow_snapshot", "stock_flow_snapshot",
                          "concept_flow_snapshot"]:
                conn.execute(f"DELETE FROM {table} WHERE snapshot_time < ?", (cutoff,))
            # signals 表使用 signal_time 字段（修复：原代码误用 snapshot_time）
            conn.execute("DELETE FROM signals WHERE signal_time < ?", (cutoff,))
            logger.info(f"数据清理完成，保留 {CONFIG.storage.RETENTION_DAYS} 天")

    @staticmethod
    def _safe_float(v, default=0.0) -> float:
        if v is None:
            return default
        try:
            return round(float(v), 4)
        except (ValueError, TypeError):
            return default


# 全局单例
db = Database()
