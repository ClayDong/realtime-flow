"""
资金流分析引擎
算法专家 + 分析专家 + 股票专家 多方视角：
- 行业轮动检测
- 个股资金流强度评分
- 主力 + 北向共振信号
- 异常资金流预警
- 顶底背离检测
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from collections import defaultdict

from config import CONFIG
from db.models import db

logger = logging.getLogger(__name__)


class FlowAnalyzer:
    """
    资金流分析引擎
    分析专家视角：多维度打分、排序、异常检测
    """

    def __init__(self):
        self.stock_cache: Dict[str, Dict] = {}

    # ═══════════════════════════════════════════════
    # 1. 行业轮动分析
    # ═══════════════════════════════════════════════
    def analyze_sector_rotation(self, sector_data: List[Dict]) -> Dict[str, Any]:
        """
        行业轮动分析
        股票专家视角：
        - 主力净流入 TOP 行业 → 资金聚集方向
        - 主力净流出 TOP 行业 → 资金撤离方向
        - 超大单占比高的行业 → 机构行为
        - 行业涨跌幅与资金流背离检测
        
        返回: {
            "inflow_top": [...],    # 流入前N
            "outflow_top": [...],   # 流出前N
            "institutional_focus": [...],  # 机构关注（超大单占比高）
            "divergence": [...],    # 背离预警
            "rotation_score": float,  # 轮动强度
        }
        """
        result = {
            "inflow_top": [],
            "outflow_top": [],
            "institutional_focus": [],
            "divergence": [],
            "rotation_score": 0,
            "analyzed_at": datetime.now().isoformat(),
        }

        if not sector_data:
            return result

        # 排序：按主力净流入排序
        sorted_data = sorted(
            sector_data,
            key=lambda x: self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
            reverse=True,
        )

        top_n = CONFIG.analysis.SIGNAL_TOP_N

        # 流入TOP
        result["inflow_top"] = [
            {
                "name": x.get("行业名称", x.get("板块名称", "")),
                "rank": i + 1,
                "main_inflow": self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
                "main_ratio": self._safe_float(x.get("主力净流入-净占比", x.get("f184", 0))),
                "price_change": self._safe_float(x.get("涨跌幅", x.get("f3", 0))),
                "current_price": self._safe_float(x.get("最新价", x.get("f2", 0))),
            }
            for i, x in enumerate(sorted_data[:top_n])
            if self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))) > 0
        ]

        # 流出TOP（反向排序）
        sorted_desc = sorted(
            sector_data,
            key=lambda x: self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
        )
        result["outflow_top"] = [
            {
                "name": x.get("行业名称", x.get("板块名称", "")),
                "rank": i + 1,
                "main_inflow": self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
                "main_ratio": self._safe_float(x.get("主力净流入-净占比", x.get("f184", 0))),
                "price_change": self._safe_float(x.get("涨跌幅", x.get("f3", 0))),
            }
            for i, x in enumerate(sorted_desc[:top_n])
            if self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))) < 0
        ]

        # 机构关注：超大单净流入占比高
        institution_focus = sorted(
            sector_data,
            key=lambda x: self._safe_float(x.get("超大单净流入-净额", x.get("f66", 0))),
            reverse=True,
        )
        result["institutional_focus"] = [
            {
                "name": x.get("行业名称", x.get("板块名称", "")),
                "super_large_inflow": self._safe_float(x.get("超大单净流入-净额", x.get("f66", 0))),
                "super_large_ratio": self._safe_float(x.get("超大单净流入-净占比", x.get("f66_ratio", 0))),
                "main_inflow": self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
            }
            for i, x in enumerate(institution_focus[:top_n])
        ]

        # 背离检测：资金流入但股价下跌（底背离吸筹）或 资金流出但股价上涨（顶背离出货）
        for x in sector_data:
            main_in = self._safe_float(x.get("主力净流入-净额", x.get("f62", 0)))
            pct = self._safe_float(x.get("涨跌幅", x.get("f3", 0)))
            name = x.get("行业名称", x.get("板块名称", ""))

            if main_in > 1 and pct < -1:  # 资金大幅流入但跌
                result["divergence"].append({
                    "name": name,
                    "type": "底背离（资金流入但下跌）",
                    "main_inflow": main_in,
                    "price_change": pct,
                })
            elif main_in < -1 and pct > 1:  # 资金大幅流出但涨
                result["divergence"].append({
                    "name": name,
                    "type": "顶背离（资金流出但上涨）",
                    "main_inflow": main_in,
                    "price_change": pct,
                })

        # 轮动强度评分：前5名流入总和 vs 后5名流出总和的比值
        top5_inflow = sum(
            self._safe_float(x.get("主力净流入-净额", x.get("f62", 0)))
            for x in sorted_data[:5]
        )
        bottom5_outflow = abs(sum(
            self._safe_float(x.get("主力净流入-净额", x.get("f62", 0)))
            for x in sorted_desc[:5]
        ))
        # 修复边界：无流出时不应返回 99.0（那是普涨，不是轮动）
        if bottom5_outflow > 0.01:  # 至少有 0.01 亿流出才算
            result["rotation_score"] = round(top5_inflow / bottom5_outflow, 2)
        elif top5_inflow > 0 and bottom5_outflow <= 0.01:
            result["rotation_score"] = 0.0  # 普涨无轮动
            result["rotation_note"] = "市场普涨，无明显轮动"
        else:
            result["rotation_score"] = 0.0

        # 保存信号
        for s in result["divergence"]:
            db.save_signal(
                signal_type="sector_divergence",
                signal_name=s["type"],
                description=f"行业[{s['name']}] {s['type']}",
                value=s["main_inflow"],
                sector_name=s["name"],
            )

        return result

    # ═══════════════════════════════════════════════
    # 2. 个股资金流评分
    # ═══════════════════════════════════════════════
    def analyze_stock_flow(self, stock_data: List[Dict]) -> Dict[str, Any]:
        """
        个股资金流深度分析
        股票专家视角：
        - 综合评分（主力+超大单+大单三维度）
        - 资金流强度分级（强/中/弱/负）
        - 排名跃升检测
        - 主力净占比异常
    
        返回: {
            "ranked_stocks": [...],   # 综合评分排序
            "strong_inflow": [...],   # 强资金流入
            "ranking_jump": [...],    # 排名跃升
            "top_by_ratio": [...],    # 按净占比排序
        }
        """
        result = {
            "ranked_stocks": [],
            "strong_inflow": [],
            "ranking_jump": [],
            "top_by_ratio": [],
            "analyzed_at": datetime.now().isoformat(),
        }

        if not stock_data:
            return result

        scored = []
        for x in stock_data:
            main_in = self._safe_float(x.get("主力净流入-净额", x.get("f62", 0)))
            main_ratio = self._safe_float(x.get("主力净流入-净占比", x.get("f184", 0)))
            super_large = self._safe_float(x.get("超大单净流入-净额", x.get("f66", 0)))
            large = self._safe_float(x.get("大单净流入-净额", x.get("f69", 0)))
            pct = self._safe_float(x.get("涨跌幅", x.get("f3", 0)))
            price = self._safe_float(x.get("最新价", x.get("f2", 0)))
            code = str(x.get("代码", x.get("f12", "")))
            name = str(x.get("名称", x.get("f14", "")))

            # 过滤涨跌停股票（涨停资金流入是虚假信号，跌停无法卖出）
            # 主板 ±10%，科创板/创业板 ±20%，ST ±5%
            is_st = "ST" in name or "*ST" in name
            limit_pct = 5.0 if is_st else (20.0 if code.startswith(("300", "301", "688", "8")) else 10.0)
            if abs(pct) >= limit_pct - 0.01:
                continue  # 跳过涨跌停股

            # 综合评分算法（股票专家优化）：
            # 主力净占比已是相对值（净额/成交额），天然归一化，权重最高
            # 主力净额用对数归一化避免大/小盘股失真
            # 超大单占比 = 超大单/主力，衡量机构参与度
            score = (
                0.45 * self._normalize(main_ratio, -10, 10)        # 主力净占比（相对值，最可靠）
                + 0.25 * self._normalize_log(main_in)               # 主力净额（对数归一化，避免大盘股霸榜）
                + 0.20 * self._normalize(super_large, -5, 5)        # 超大单净额
                + 0.10 * self._normalize(large, -3, 3)              # 大单净额
            )

            # 强度分级
            if main_ratio > CONFIG.analysis.STRONG_INFLOW_RATIO:
                strength = "强流入"
            elif main_ratio > 2:
                strength = "温和流入"
            elif main_ratio > -2:
                strength = "中性"
            elif main_ratio > CONFIG.analysis.STRONG_OUTFLOW_RATIO:
                strength = "温和流出"
            else:
                strength = "强流出"

            # 机构参与度：超大单占比
            total_main = abs(main_in)
            institutional_ratio = (abs(super_large) / total_main * 100) if total_main > 0 else 0

            scored.append({
                "code": code,
                "name": name,
                "price": price,
                "price_change": pct,
                "main_inflow": main_in,
                "main_ratio": main_ratio,
                "super_large_inflow": super_large,
                "large_inflow": large,
                "score": round(score, 2),
                "strength": strength,
                "institutional_ratio": round(institutional_ratio, 1),
            })

        # 按综合评分排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        result["ranked_stocks"] = scored[:CONFIG.analysis.SIGNAL_TOP_N * 3]

        # 强流入过滤
        result["strong_inflow"] = [
            s for s in scored
            if s["main_ratio"] > CONFIG.analysis.STRONG_INFLOW_RATIO
        ][:CONFIG.analysis.SIGNAL_TOP_N]

        # 按主力净占比排序
        ratio_sorted = sorted(
            scored, key=lambda x: x["main_ratio"], reverse=True
        )
        result["top_by_ratio"] = ratio_sorted[:CONFIG.analysis.SIGNAL_TOP_N]

        return result

    # ═══════════════════════════════════════════════
    # 3. 市场全局分析
    # ═══════════════════════════════════════════════
    def analyze_market_overview(self, market_data: Optional[Dict],
                                 north_data: Optional[Dict]) -> Dict[str, Any]:
        """
        市场全局分析
        分析专家视角：
        - 大盘资金流趋势
        - 主力 vs 散户博弈
        - 北向资金动向
        """
        result = {
            "market_trend": "neutral",
            "main_vs_retail": "neutral",
            "north_bound_analysis": {},
            "signals": [],
        }

        if market_data:
            main_in = market_data.get("main_net_inflow", 0)
            small_in = market_data.get("small_inflow", 0)
            super_large = market_data.get("super_large_inflow", 0)

            # 主力 vs 散户博弈分析（股票专家：需结合位置判断，不能绝对化）
            if main_in > 0 and small_in < 0:
                result["main_vs_retail"] = "主力买入，散户卖出（可能健康，需结合位置判断）"
            elif main_in < 0 and small_in > 0:
                result["main_vs_retail"] = "主力卖出，散户接盘（警惕出货）"
            elif main_in > 0 and small_in > 0:
                result["main_vs_retail"] = "主力散户同时买入（情绪一致）"
            else:
                result["main_vs_retail"] = "主力散户同时卖出（恐慌或调整）"

        if north_data:
            total = north_data.get("total", 0)
            result["north_bound_analysis"] = {
                "total": total,
                "direction": "流入" if total > 0 else "流出",
                "significance": "显著" if abs(total) > CONFIG.analysis.NORTH_BOUND_DAILY_THRESHOLD else "一般",
            }
            if abs(total) > CONFIG.analysis.NORTH_BOUND_DAILY_THRESHOLD:
                result["signals"].append(
                    f"北向资金{'大幅流入' if total > 0 else '大幅流出'}{abs(total):.1f}亿"
                )

        return result

    # ═══════════════════════════════════════════════
    # 4. 概念热点分析
    # ═══════════════════════════════════════════════
    def analyze_concept_hotspot(self, concept_data: List[Dict]) -> Dict[str, Any]:
        """概念热点分析"""
        result = {
            "hot_concepts": [],
            "concept_rotation": False,
        }
        if not concept_data:
            return result

        sorted_c = sorted(
            concept_data,
            key=lambda x: self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
            reverse=True,
        )
        result["hot_concepts"] = [
            {
                "name": x.get("概念名称", x.get("板块名称", "")),
                "main_inflow": self._safe_float(x.get("主力净流入-净额", x.get("f62", 0))),
                "main_ratio": self._safe_float(x.get("主力净流入-净占比", x.get("f184", 0))),
                "price_change": self._safe_float(x.get("涨跌幅", x.get("f3", 0))),
            }
            for x in sorted_c[:10]
        ]
        return result

    # ═══════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════
    @staticmethod
    def _safe_float(v, default=0.0) -> float:
        if v is None:
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _normalize(v: float, min_v: float, max_v: float) -> float:
        """归一化到 0-1 范围"""
        if max_v <= min_v:
            return 0.5
        clipped = max(min(v, max_v), min_v)
        return (clipped - min_v) / (max_v - min_v)

    @staticmethod
    def _normalize_log(v: float) -> float:
        """对数归一化（适用于资金净额，避免大盘股霸榜）
        将值映射到 0-1：负值用 -log(|v|+1)，正值用 log(v+1)，再归一化
        """
        if v == 0:
            return 0.5
        import math
        if v > 0:
            # 正值：log(v+1) 映射到 [0.5, 1]，上限 10亿 → log(11)≈2.4
            return 0.5 + min(math.log10(v + 1) / 2.4, 1.0) * 0.5
        else:
            # 负值：-log(|v|+1) 映射到 [0, 0.5]
            return 0.5 - min(math.log10(abs(v) + 1) / 2.4, 1.0) * 0.5


# 全局单例
analyzer = FlowAnalyzer()
