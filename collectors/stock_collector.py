"""
个股资金流采集器
股票专家视角：主力资金、超大单、大单、中单、小单 多维度
数据专家视角：排行+明细双层架构
"""
import logging
from typing import List, Dict, Optional, Any
import pandas as pd
import akshare as ak

from .base import BaseCollector
from config import CONFIG

logger = logging.getLogger(__name__)


class StockCollector(BaseCollector):
    """
    个股资金流采集器
    两个维度：
    1. stock_individual_fund_flow_rank - 全市场排行（今日/3日/5日/10日）
    2. stock_individual_fund_flow      - 单只个股明细历史
    """

    def __init__(self):
        super().__init__("个股资金流")

    def fetch(self) -> Optional[Dict[str, Any]]:
        """采集全市场个股资金流排行"""
        result = {}

        # 今日排行
        try:
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            if df is not None and len(df) > 0:
                result["today"] = self._normalize_rank_df(df)
                logger.info(f"个股今日排行: {len(result['today'])} 只")
        except Exception as e:
            logger.warning(f"个股今日排行采集失败: {e}")

        # 5日排行（用于趋势判断）
        try:
            df5 = ak.stock_individual_fund_flow_rank(indicator="5日")
            if df5 is not None and len(df5) > 0:
                result["5d"] = self._normalize_rank_df(df5)
                logger.info(f"个股5日排行: {len(result['5d'])} 只")
        except Exception as e:
            logger.warning(f"个股5日排行采集失败: {e}")

        # 主力净流入排名（独立接口，数据维度更丰富）
        try:
            df_main = ak.stock_main_fund_flow(symbol="全部股票")
            if df_main is not None and len(df_main) > 0:
                result["main_force"] = self._normalize_main_df(df_main)
                logger.info(f"主力净流入排行: {len(result['main_force'])} 只")
        except Exception as e:
            logger.warning(f"主力净流入排行采集失败: {e}")

        return result if result else None

    def _normalize_rank_df(self, df: pd.DataFrame) -> List[Dict]:
        """标准化排行数据"""
        records = []
        for _, row in df.iterrows():
            rec = {}
            for col in df.columns:
                val = row[col]
                if isinstance(val, (pd.Timestamp, pd.Period, pd.Timedelta)):
                    val = str(val)
                rec[str(col)] = val
            records.append(rec)
        return records

    def _normalize_main_df(self, df: pd.DataFrame) -> List[Dict]:
        """标准化主力排行数据"""
        records = []
        for _, row in df.iterrows():
            rec = {}
            for col in df.columns:
                val = row[col]
                if isinstance(val, (pd.Timestamp, pd.Period)):
                    val = str(val)
                rec[str(col)] = val
            records.append(rec)
        return records

    def fetch_stock_detail(self, stock_code: str, market: str = "sh") -> Optional[List[Dict]]:
        """获取单只个股的历史资金流明细"""
        try:
            df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            if df is not None and len(df) > 0:
                records = df.to_dict("records")
                for r in records:
                    for k, v in r.items():
                        if isinstance(v, (pd.Timestamp, pd.Period)):
                            r[k] = str(v)
                logger.info(f"个股[{stock_code}]明细: {len(records)} 条记录")
                return records
        except Exception as e:
            logger.warning(f"个股[{stock_code}]明细采集失败: {e}")
        return None

    def fetch_stock_detail_for_list(self, stocks: List[tuple]) -> Dict[str, List[Dict]]:
        """
        批量获取多只个股明细
        stocks: [(code, market), ...]
        """
        result = {}
        for code, market in stocks[:20]:  # 限制20只，避免反爬
            detail = self.fetch_stock_detail(code, market)
            if detail:
                result[f"{market}.{code}"] = detail
        return result
