"""
行业/概念资金流采集器
数据专家视角：统一行业概念地域三大板块资金流采集
股票专家视角：行业排名、历史资金流、板块内个股
"""
import logging
from typing import List, Dict, Optional, Any
import pandas as pd
import akshare as ak

from .base import BaseCollector
from config import CONFIG

logger = logging.getLogger(__name__)


class SectorCollector(BaseCollector):
    """
    行业资金流采集器
    采集：
    1. 行业资金流排名（今日/5日/10日）
    2. 概念资金流排名
    3. 各行业历史资金流
    """

    def __init__(self):
        super().__init__("行业资金流")

    def fetch(self) -> Optional[Dict[str, Any]]:
        """采集行业+概念资金流"""
        result = {}

        # 1. 行业资金流排名（今日）
        try:
            df = ak.stock_sector_fund_flow_rank(
                indicator="今日", sector_type="行业资金流"
            )
            if df is not None and len(df) > 0:
                # 标准化字段名（东方财富的字段名是中文）
                cols = df.columns.tolist()
                logger.info(f"行业资金流字段: {cols}")
                result["sector_today"] = self._normalize_sector_df(df, "今日")
        except Exception as e:
            logger.warning(f"行业资金流(今日)采集失败: {e}")

        # 2. 行业5日排名（用于趋势判断）
        try:
            df5 = ak.stock_sector_fund_flow_rank(
                indicator="5日", sector_type="行业资金流"
            )
            if df5 is not None and len(df5) > 0:
                result["sector_5d"] = self._normalize_sector_df(df5, "5日")
        except Exception as e:
            logger.warning(f"行业资金流(5日)采集失败: {e}")

        # 3. 概念资金流排名（今日）
        if CONFIG.data.CONCEPT_FLOW_ENABLED:
            try:
                df_c = ak.stock_sector_fund_flow_rank(
                    indicator="今日", sector_type="概念资金流"
                )
                if df_c is not None and len(df_c) > 0:
                    result["concept_today"] = self._normalize_sector_df(df_c, "概念")
            except Exception as e:
                logger.warning(f"概念资金流采集失败: {e}")

        if result:
            counts = {k: len(v) for k, v in result.items() if isinstance(v, list)}
            logger.info(f"行业采集完成: {counts}")

        return result if result else None

    def _normalize_sector_df(self, df: pd.DataFrame, tag: str) -> List[Dict]:
        """统一标准化行业数据"""
        records = []
        for _, row in df.iterrows():
            rec = {"tag": tag}
            for col in df.columns:
                val = row[col]
                if isinstance(val, (pd.Timestamp, pd.Period)):
                    val = str(val)
                rec[str(col)] = val
            records.append(rec)
        return records

    def fetch_sector_history(self, sector_name: str) -> Optional[List[Dict]]:
        """获取单个行业的历史资金流"""
        try:
            df = ak.stock_sector_fund_flow_hist(symbol=sector_name)
            if df is not None and len(df) > 0:
                return df.to_dict("records")
        except Exception as e:
            logger.warning(f"行业[{sector_name}]历史采集失败: {e}")
        return None


class ConceptCollector(BaseCollector):
    """概念资金流采集器（独立方式）"""

    def __init__(self):
        super().__init__("概念资金流")

    def fetch(self) -> Optional[List[Dict]]:
        try:
            df = ak.stock_fund_flow_concept()
            if df is not None and len(df) > 0:
                return df.to_dict("records")
        except Exception as e:
            logger.warning(f"概念资金流采集失败: {e}")
        return None
