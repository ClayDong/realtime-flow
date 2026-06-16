"""
信号回测引擎
分析专家视角：验证历史信号的准确性
股票专家视角：底背离/顶背离信号后续走势验证
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

from db.models import db
from collectors.sector_collector import SectorCollector

logger = logging.getLogger(__name__)


class SignalBacktester:
    """
    信号回测引擎
    策略：对历史信号，验证其在发出后 N 日的涨跌幅
    - 底背离（资金流入但下跌）→ 预期后续上涨
    - 顶背离（资金流出但上涨）→ 预期后续下跌
    """

    def __init__(self):
        self.sector_collector = SectorCollector()

    def backtest_signals(self, days: int = 30, forward_days: int = 5) -> Dict[str, Any]:
        """
        回测最近 N 天的信号准确率
        参数：
            days: 回测最近多少天的信号
            forward_days: 信号发出后多少天验证结果
        返回：{
            "total_signals": int,
            "validated": int,
            "accuracy": float,  # 准确率 %
            "by_type": {...},   # 按信号类型分组
            "details": [...],   # 明细
        }
        """
        result = {
            "total_signals": 0,
            "validated": 0,
            "correct": 0,
            "accuracy": 0.0,
            "by_type": defaultdict(lambda: {"total": 0, "correct": 0, "accuracy": 0.0}),
            "details": [],
            "forward_days": forward_days,
            "backtest_days": days,
        }

        # 拉取最近 N 天的信号
        cutoff = datetime.now() - timedelta(days=days + forward_days + 5)
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM signals
                WHERE signal_time >= ?
                ORDER BY signal_time DESC
            """, (cutoff.isoformat(),)).fetchall()
            signals = [dict(r) for r in rows]

        result["total_signals"] = len(signals)
        if not signals:
            return result

        # 按板块分组信号（同一板块的信号合并）
        sector_signals = defaultdict(list)
        for s in signals:
            sector = s.get("sector_name", "")
            if sector:
                sector_signals[sector].append(s)

        # 对每个板块，拉取历史资金流数据验证
        for sector, sector_sigs in sector_signals.items():
            try:
                hist = self.sector_collector.fetch_sector_history(sector)
                if not hist or len(hist) < forward_days + 1:
                    continue

                # hist 按日期升序排列
                hist_sorted = sorted(hist, key=lambda x: str(x.get("日期", x.get("date", ""))))

                for sig in sector_sigs:
                    sig_time = sig.get("signal_time", "")
                    sig_date_str = sig_time[:10] if sig_time else ""
                    sig_type = sig.get("signal_name", "")

                    # 找到信号发出当天的索引
                    sig_idx = None
                    for i, h in enumerate(hist_sorted):
                        h_date = str(h.get("日期", h.get("date", "")))[:10]
                        if h_date == sig_date_str:
                            sig_idx = i
                            break

                    if sig_idx is None or sig_idx + forward_days >= len(hist_sorted):
                        continue  # 无法验证

                    # 信号当天的涨跌幅
                    sig_day_pct = self._safe_float(hist_sorted[sig_idx].get("涨跌幅", 0))
                    # N 天后的涨跌幅（累计）
                    end_idx = min(sig_idx + forward_days, len(hist_sorted) - 1)
                    future_pct = self._safe_float(hist_sorted[end_idx].get("涨跌幅", 0))

                    # 判断准确性
                    is_correct = False
                    if "底背离" in sig_type:
                        # 底背离预期后续上涨
                        is_correct = future_pct > 0
                    elif "顶背离" in sig_type:
                        # 顶背离预期后续下跌
                        is_correct = future_pct < 0

                    result["validated"] += 1
                    if is_correct:
                        result["correct"] += 1

                    result["by_type"][sig_type]["total"] += 1
                    if is_correct:
                        result["by_type"][sig_type]["correct"] += 1

                    result["details"].append({
                        "sector": sector,
                        "signal_date": sig_date_str,
                        "signal_type": sig_type,
                        "sig_day_pct": round(sig_day_pct, 2),
                        "future_pct": round(future_pct, 2),
                        "is_correct": is_correct,
                    })

            except Exception as e:
                logger.warning(f"回测板块[{sector}]失败: {e}")
                continue

        # 计算准确率
        if result["validated"] > 0:
            result["accuracy"] = round(result["correct"] / result["validated"] * 100, 1)

        for sig_type, stats in result["by_type"].items():
            if stats["total"] > 0:
                stats["accuracy"] = round(stats["correct"] / stats["total"] * 100, 1)

        # 转换 defaultdict 为普通 dict
        result["by_type"] = dict(result["by_type"])

        return result

    @staticmethod
    def _safe_float(v, default=0.0) -> float:
        if v is None:
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default


# 全局单例
backtester = SignalBacktester()
