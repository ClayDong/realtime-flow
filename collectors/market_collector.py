"""
大盘资金流 + 沪深港通采集器
数据专家视角：多数据源聚合，归一化输出
"""
import logging
from typing import Dict, Optional, Any
import pandas as pd
import akshare as ak

from .base import BaseCollector
from config import CONFIG

logger = logging.getLogger(__name__)


class MarketCollector(BaseCollector):
    """
    大盘资金流采集器
    采集：上证+深证 大盘资金流、北向/南向资金
    """

    def __init__(self):
        super().__init__("大盘资金流")

    def fetch(self) -> Optional[Dict[str, Any]]:
        """采集大盘数据"""
        result = {}

        # 1. 大盘资金流历史（最近一日）
        try:
            df = ak.stock_market_fund_flow()
            if df is not None and len(df) > 0:
                # 取最新一天
                latest = df.iloc[-1].to_dict()
                result["market"] = {
                    "date": str(latest.get("日期", "")),
                    "sh_close": self._safe_float(latest.get("上证-收盘价")),
                    "sh_change": self._safe_float(latest.get("上证-涨跌幅")),
                    "sz_close": self._safe_float(latest.get("深证-收盘价")),
                    "sz_change": self._safe_float(latest.get("深证-涨跌幅")),
                    "main_net_inflow": self._safe_float(latest.get("主力净流入-净额")),
                    "main_net_ratio": self._safe_float(latest.get("主力净流入-净占比")),
                    "super_large_inflow": self._safe_float(latest.get("超大单净流入-净额")),
                    "large_inflow": self._safe_float(latest.get("大单净流入-净额")),
                    "medium_inflow": self._safe_float(latest.get("中单净流入-净额")),
                    "small_inflow": self._safe_float(latest.get("小单净流入-净额")),
                }
                logger.info(f"大盘数据: 日期={result['market']['date']}, "
                           f"主力净流入={result['market']['main_net_inflow']:.2f}亿")
        except Exception as e:
            logger.warning(f"大盘资金流采集失败（非交易时段或网络问题）: {e}")

        # 2. 北向资金（盘中实时分钟级）
        if CONFIG.data.NORTH_SOUTH_BOUND_ENABLED:
            try:
                df_n = ak.stock_hsgt_fund_min_em(symbol="北向资金")
                if df_n is not None and len(df_n) > 0:
                    latest_n = df_n.iloc[-1].to_dict()
                    result["north_bound"] = {
                        "date": str(latest_n.get("日期", "")),
                        "time": str(latest_n.get("时间", "")),
                        "sh_connect": self._safe_float(latest_n.get("港股通(沪)", 0)),
                        "sz_connect": self._safe_float(latest_n.get("港股通(深)", 0)),
                        "total": self._safe_float(latest_n.get("北向资金", 0)),
                    }
                    logger.info(f"北向资金: {result['north_bound']['total']:.2f}亿")
            except Exception as e:
                logger.warning(f"北向资金采集失败: {e}")

        return result if result else None

    @staticmethod
    def _safe_float(v, default=0.0) -> float:
        if v is None:
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default
