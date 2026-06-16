"""
备用数据源采集器（新浪财经 + 腾讯财经）
架构专家视角：多数据源冗余，主源失败时自动降级
数据专家视角：保持输出结构与主源一致
"""
import logging
import time
import json
from typing import Dict, Optional, Any, List

import httpx

from .base import BaseCollector

logger = logging.getLogger(__name__)


# ─── 新浪财经 HTTP 客户端 ────────────────────────────
SINA_BASE = "https://hq.sinajs.cn"
TENCENT_BASE = "https://qt.gtimg.cn"


def _http_get(url: str, headers: dict = None, timeout: int = 10) -> Optional[str]:
    """统一 HTTP GET，失败返回 None"""
    try:
        with httpx.Client(timeout=timeout, headers=headers or {}) as client:
            r = client.get(url)
            if r.status_code == 200:
                return r.text
            logger.warning(f"HTTP {r.status_code}: {url}")
    except Exception as e:
        logger.warning(f"HTTP 请求失败 {url}: {e}")
    return None


class SinaStockCollector(BaseCollector):
    """
    新浪财经个股行情采集器（备用源）
    用于东方财富采集失败时降级获取自选股最新价
    接口：https://hq.sinajs.cn/list=sh600519
    """

    def __init__(self):
        super().__init__("新浪个股行情")

    def fetch(self) -> Optional[Dict[str, Any]]:
        """采集器接口要求，本类主要用于 fetch_batch"""
        return None

    def fetch_batch(self, stocks: List[tuple]) -> List[Dict]:
        """
        批量获取个股最新行情
        stocks: [(code, market, name), ...]
        返回：[{code, market, name, 收盘价, 涨跌幅, ...}, ...]
        """
        results = []
        # 新浪支持批量查询：list=sh600519,sz000858
        codes = [f"{m}{c}" for c, m, n in stocks]
        url = f"{SINA_BASE}?list={','.join(codes)}"
        # 新浪必须带 Referer
        text = _http_get(url, headers={"Referer": "https://finance.sina.com.cn"})
        if not text:
            logger.warning("新浪批量行情获取失败")
            return results

        lines = text.strip().split("\n")
        code_map = {f"{m}{c}": (c, m, n) for c, m, n in stocks}

        for line in lines:
            try:
                # var hq_str_sh600519="贵州茅台,1800.00,1790.00,..."
                if "=" not in line:
                    continue
                key = line.split("=")[0].split("_")[-1].strip()
                content = line.split('"')[1] if '"' in line else ""
                fields = content.split(",")
                if len(fields) < 32:
                    continue

                code, market, name = code_map.get(key, (key[2:], key[:2], ""))
                # 新浪行情字段：0=名称,1=今开,2=昨收,3=当前价,4=最高,5=最低
                # 30=日期,31=时间
                current_price = float(fields[3]) if fields[3] else 0
                prev_close = float(fields[2]) if fields[2] else 0
                pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                results.append({
                    "code": code,
                    "market": market,
                    "display_name": name or fields[0],
                    "收盘价": current_price,
                    "涨跌幅": round(pct, 2),
                    "日期": fields[30] if len(fields) > 30 else "",
                    "source": "sina",
                })
            except (IndexError, ValueError) as e:
                continue

        logger.info(f"新浪批量行情: {len(results)}/{len(stocks)}")
        return results


class TencentStockCollector(BaseCollector):
    """
    腾讯财经个股行情采集器（备用源2）
    接口：https://qt.gtimg.cn/q=sh600519
    """

    def __init__(self):
        super().__init__("腾讯个股行情")

    def fetch(self) -> Optional[Dict[str, Any]]:
        return None

    def fetch_batch(self, stocks: List[tuple]) -> List[Dict]:
        codes = [f"{m}{c}" for c, m, n in stocks]
        url = f"{TENCENT_BASE}/q={','.join(codes)}"
        text = _http_get(url)
        if not text:
            return []

        results = []
        code_map = {f"{m}{c}": (c, m, n) for c, m, n in stocks}
        lines = text.strip().split(";")
        for line in lines:
            line = line.strip()
            if "=" not in line:
                continue
            try:
                key = line.split("=")[0].split("_")[-1].strip().strip('"')
                content = line.split('"')[1] if '"' in line else ""
                fields = content.split("~")
                if len(fields) < 35:
                    continue

                code, market, name = code_map.get(key, (key[2:], key[:2], ""))
                # 腾讯字段：1=名称,4=当前价,5=昨收,32=涨跌幅
                current_price = float(fields[4]) if fields[4] else 0
                prev_close = float(fields[5]) if fields[5] else 0
                pct = float(fields[32]) if fields[32] else 0

                results.append({
                    "code": code,
                    "market": market,
                    "display_name": name or fields[1],
                    "收盘价": current_price,
                    "涨跌幅": round(pct, 2),
                    "日期": fields[30] if len(fields) > 30 else "",
                    "source": "tencent",
                })
            except (IndexError, ValueError):
                continue

        logger.info(f"腾讯批量行情: {len(results)}/{len(stocks)}")
        return results


# ─── 降级管理器 ─────────────────────────────────────
class FallbackManager:
    """
    数据源降级管理器
    策略：主源(东方财富) → 备用1(新浪) → 备用2(腾讯)
    """

    def __init__(self):
        self.sina = SinaStockCollector()
        self.tencent = TencentStockCollector()
        # 主源失败计数，连续失败 N 次后跳过主源一段时间
        self._main_fail_count = 0
        self._main_skip_until = 0  # timestamp

    def should_skip_main(self) -> bool:
        """是否应该跳过主源（连续失败后短暂跳过）"""
        return time.time() < self._main_skip_until

    def record_main_success(self):
        self._main_fail_count = 0
        self._main_skip_until = 0

    def record_main_failure(self):
        self._main_fail_count += 1
        if self._main_fail_count >= 3:
            # 连续失败 3 次，跳过主源 5 分钟
            self._main_skip_until = time.time() + 300
            logger.warning(f"主源连续失败 {self._main_fail_count} 次，5 分钟内跳过主源")

    def fetch_watchlist_with_fallback(self, stocks: List[tuple],
                                       primary_fetcher=None) -> List[Dict]:
        """
        带降级的自选股行情获取
        primary_fetcher: 主源获取函数（同步），返回 List[Dict]
        """
        # 1. 尝试主源
        if primary_fetcher and not self.should_skip_main():
            try:
                result = primary_fetcher()
                if result:
                    self.record_main_success()
                    return result
            except Exception as e:
                logger.warning(f"主源获取失败: {e}")
            self.record_main_failure()

        # 2. 降级到新浪
        logger.info("降级到新浪数据源")
        result = self.sina.fetch_batch(stocks)
        if result:
            return result

        # 3. 降级到腾讯
        logger.info("降级到腾讯数据源")
        result = self.tencent.fetch_batch(stocks)
        if result:
            return result

        logger.error("所有数据源均失败")
        return []


# 全局单例
fallback_manager = FallbackManager()
