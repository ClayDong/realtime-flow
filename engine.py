"""
系统核心调度引擎
架构专家视角：数据流编排
运维专家视角：可观测性、异常自愈
数据专家视角：各采集器协同工作
"""
import logging
import time
from datetime import datetime, time as dtime
from typing import Dict, Optional, Any, List
from collections import defaultdict

from config import CONFIG, TRADE_START_AM, TRADE_END_AM, TRADE_START_PM, TRADE_END_PM, PREHEAT_START, is_holiday
from collectors.market_collector import MarketCollector
from collectors.sector_collector import SectorCollector, ConceptCollector
from collectors.stock_collector import StockCollector
from analyzers.engine import analyzer
from db.models import db

logger = logging.getLogger(__name__)


class FlowEngine:
    """
    资金流数据处理引擎
    负责：调度采集、数据持久化、运行分析、缓存最新数据
    """

    def __init__(self):
        self.market_collector = MarketCollector()
        self.sector_collector = SectorCollector()
        self.concept_collector = ConceptCollector()
        self.stock_collector = StockCollector()

        # 最新数据缓存（用于Web实时推送）
        self.latest_data: Dict[str, Any] = {
            "market": None,
            "sectors": None,
            "concepts": None,
            "stocks": None,
            "sector_analysis": None,
            "stock_analysis": None,
            "market_analysis": None,
            "concept_analysis": None,
            "updated_at": None,
        }

        # 运行统计（运维专家：可观测性）
        self.stats = {
            "total_polls": 0,
            "successful_polls": 0,
            "failed_polls": 0,
            "last_poll_time": None,
            "errors": [],
        }

    def is_trade_time(self) -> bool:
        """判断当前是否为交易时段 - 股票专家视角"""
        now = datetime.now()
        if now.weekday() >= 5:  # 周六日
            return False
        if is_holiday(now):  # 法定假日
            return False
        minutes = now.hour * 60 + now.minute
        return (TRADE_START_AM <= minutes <= TRADE_END_AM or
                TRADE_START_PM <= minutes <= TRADE_END_PM)

    def is_market_hours(self) -> bool:
        """判断是否在盘前准备时段或盘中"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        if is_holiday(now):  # 法定假日不预热
            return False
        minutes = now.hour * 60 + now.minute
        return PREHEAT_START <= minutes <= TRADE_END_PM

    def poll_once(self) -> Dict[str, Any]:
        """
        一次完整的轮询：采集 → 存储 → 分析 → 缓存
        返回本次轮询结果
        """
        result: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "market_hours": self.is_market_hours(),
            "trade_time": self.is_trade_time(),
        }
        errors = []

        self.stats["total_polls"] += 1

        # ─── Step 1: 采集大盘 ───────────────────────
        try:
            market_data = self.market_collector.safe_fetch()
            if market_data:
                result["market"] = market_data
                # 持久化
                if "market" in market_data:
                    db.save_market_flow(market_data.get("market", {}))
                # 北向数据附在market下
                if "north_bound" in market_data:
                    result["north_bound"] = market_data["north_bound"]
        except Exception as e:
            errors.append(f"market: {e}")

        # ─── Step 2: 采集行业 ───────────────────────
        try:
            sector_data = self.sector_collector.safe_fetch()
            if sector_data:
                result["sectors"] = sector_data
                # 持久化行业快照
                if "sector_today" in sector_data:
                    db.save_sector_snapshot(sector_data["sector_today"], "今日")
                if "sector_5d" in sector_data:
                    db.save_sector_snapshot(sector_data["sector_5d"], "5日")
                if "concept_today" in sector_data:
                    db.save_sector_snapshot(sector_data["concept_today"], "概念_今日")
        except Exception as e:
            errors.append(f"sector: {e}")

        # ─── Step 3: 采集概念（独立方式） ───────────
        try:
            concept_data = self.concept_collector.safe_fetch()
            if concept_data:
                result["concepts"] = concept_data
                db.save_concept_snapshot(concept_data)
        except Exception as e:
            errors.append(f"concept: {e}")

        # ─── Step 4: 采集个股排行 ───────────────────
        try:
            stock_data = self.stock_collector.safe_fetch()
            if stock_data:
                result["stocks"] = stock_data
                if "today" in stock_data:
                    db.save_stock_snapshot(stock_data["today"], "今日")
                if "5d" in stock_data:
                    db.save_stock_snapshot(stock_data["5d"], "5日")
        except Exception as e:
            errors.append(f"stock: {e}")

        # ─── Step 5: 分析引擎 ───────────────────────
        try:
            # 行业分析
            if result.get("sectors") and "sector_today" in result["sectors"]:
                sector_analysis = analyzer.analyze_sector_rotation(
                    result["sectors"]["sector_today"]
                )
                result["sector_analysis"] = sector_analysis

            # 个股分析
            if result.get("stocks") and "today" in result["stocks"]:
                stock_analysis = analyzer.analyze_stock_flow(
                    result["stocks"]["today"]
                )
                result["stock_analysis"] = stock_analysis

            # 市场分析
            market_data = result.get("market", {})
            north_data = market_data.get("north_bound") if market_data else None
            result["market_analysis"] = analyzer.analyze_market_overview(
                market_data.get("market") if market_data else None,
                north_data,
            )

            # 概念分析
            if result.get("concepts"):
                result["concept_analysis"] = analyzer.analyze_concept_hotspot(
                    result["concepts"]
                )

        except Exception as e:
            errors.append(f"analysis: {e}")

        # ─── Step 6: 更新缓存 ───────────────────────
        self.latest_data = {
            "market": result.get("market", {}),
            "market_analysis": result.get("market_analysis"),
            "sectors": result.get("sectors"),
            "sector_analysis": result.get("sector_analysis"),
            "concepts": result.get("concepts"),
            "concept_analysis": result.get("concept_analysis"),
            "stocks": result.get("stocks"),
            "stock_analysis": result.get("stock_analysis"),
            "updated_at": datetime.now().isoformat(),
        }

        # ─── 统计 ────────────────────────────────
        if errors:
            self.stats["failed_polls"] += 1
            self.stats["errors"] = errors[-10:]  # 保留最近10条
            logger.warning(f"轮询完成但有错误: {errors}")
        else:
            self.stats["successful_polls"] += 1

        self.stats["last_poll_time"] = datetime.now().isoformat()
        result["errors"] = errors
        result["status"] = "ok" if not errors else "partial"

        logger.info(
            f"轮询完成: market={'✓' if 'market' in result else '✗'} "
            f"sector={'✓' if 'sectors' in result else '✗'} "
            f"stock={'✓' if 'stocks' in result else '✗'} "
            f"errors={len(errors)}"
        )

        return result

    def get_cache(self) -> Dict[str, Any]:
        """获取最新缓存数据（优先缓存，无数据时从数据库回退）"""
        if self.latest_data.get("updated_at") and self.latest_data.get("sector_analysis") is not None:
            return self.latest_data
        
        # 回退：从数据库加载最近的数据
        logger.info("缓存为空，从数据库加载历史数据重建...")
        import json
        try:
            sectors = db.get_latest_sector_snapshot("今日")
            stocks = db.get_latest_stock_snapshot("今日", 50)
            concepts_rows = db.get_latest_sector_snapshot("概念_今日")
            market = db.get_market_flow_recent(1)
            
            if not sectors and not stocks and not market:
                return self.latest_data
            
            cache = {"updated_at": datetime.now().isoformat()}
            
            # 解析行业
            sector_list = []
            for row in (sectors or []):
                raw = row.get("raw_json")
                if raw:
                    try:
                        sector_list.append(json.loads(raw))
                    except:
                        pass
            if sector_list:
                cache["sectors"] = {"sector_today": sector_list}
                cache["sector_analysis"] = analyzer.analyze_sector_rotation(sector_list)
            
            # 解析个股
            stock_list = []
            for row in (stocks or []):
                raw = row.get("raw_json")
                if raw:
                    try:
                        stock_list.append(json.loads(raw))
                    except:
                        pass
            if stock_list:
                cache["stocks"] = {"today": stock_list}
                cache["stock_analysis"] = analyzer.analyze_stock_flow(stock_list)
            
            # 市场
            if market:
                m = dict(market[0])
                cache["market"] = {
                    "market": {
                        "date": m.get("date", ""),
                        "sh_close": m.get("sh_close"),
                        "sh_change": m.get("sh_change"),
                        "sz_close": m.get("sz_close"),
                        "sz_change": m.get("sz_change"),
                        "main_net_inflow": m.get("main_net_inflow"),
                        "main_net_ratio": m.get("main_net_ratio"),
                        "super_large_inflow": m.get("super_large_inflow"),
                        "large_inflow": m.get("large_inflow"),
                        "medium_inflow": m.get("medium_inflow"),
                        "small_inflow": m.get("small_inflow"),
                    },
                    "north_bound": {
                        "total": m.get("north_bound_total", 0),
                        "date": m.get("date", ""),
                    }
                }
                # 市场分析
                cache["market_analysis"] = analyzer.analyze_market_overview(
                    cache["market"]["market"],
                    cache["market"]["north_bound"],
                )
            
            # 概念
            concept_list = []
            for row in (concepts_rows or []):
                raw = row.get("raw_json")
                if raw:
                    try:
                        concept_list.append(json.loads(raw))
                    except:
                        pass
            if concept_list:
                cache["concepts"] = concept_list
                cache["concept_analysis"] = analyzer.analyze_concept_hotspot(concept_list)
            
            logger.info(f"数据库回退: sectors={len(sector_list)}, stocks={len(stock_list)}")
            self.latest_data = cache
            return cache
        except Exception as e:
            logger.warning(f"数据库回退失败: {e}", exc_info=True)
        
        return self.latest_data

    def get_stats(self) -> Dict:
        """获取运行统计 - 运维专家：系统可观测性"""
        return {
            **self.stats,
            "db_size": self._get_db_size(),
            "cache_age": (
                (datetime.now() - datetime.fromisoformat(self.latest_data["updated_at"])).total_seconds()
                if self.latest_data.get("updated_at") else None
            ),
        }

    @staticmethod
    def _get_db_size() -> str:
        """获取数据库文件大小"""
        import os
        db_path = CONFIG.storage.DB_PATH
        if os.path.exists(db_path):
            size = os.path.getsize(db_path)
            if size < 1024:
                return f"{size}B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f}KB"
            else:
                return f"{size / 1024 / 1024:.1f}MB"
        return "0B"



    # ═══════════════════════════════════════════════
    # 自选股/持仓追踪
    # ═══════════════════════════════════════════════
    # 自选股缓存（避免每次 WS 推送都重新拉取）
    _watchlist_cache: List[Dict] = None
    _watchlist_cache_time: float = 0
    _WATCHLIST_CACHE_TTL = 120  # 2 分钟缓存

    def fetch_watchlist_flow(self) -> List[Dict]:
        """
        获取自选股的资金流明细（带 2 分钟缓存 + 多源降级）
        自选股列表优先从数据库读取（支持 UI 增删改），降级到 config.py 默认值
        """
        now_ts = time.time()
        if (self._watchlist_cache is not None and
                now_ts - self._watchlist_cache_time < self._WATCHLIST_CACHE_TTL):
            return self._watchlist_cache

        from config import CONFIG as cfg
        # 优先从数据库读取自选股
        db_watchlist = db.get_watchlist()
        if db_watchlist:
            watchlist = [
                (w["stock_code"], w["market"], w["display_name"] or "")
                for w in db_watchlist
            ]
        else:
            watchlist = cfg.portfolio.WATCHLIST

        # 主源：东方财富（akshare，有资金流明细）
        def primary_fetch():
            results = []
            for code, market, name in watchlist:
                try:
                    detail = self.stock_collector.fetch_stock_detail(code, market)
                    if detail and len(detail) > 0:
                        detail_sorted = sorted(
                            detail,
                            key=lambda x: str(x.get("日期", x.get("date", ""))),
                            reverse=True,
                        )
                        latest = detail_sorted[0]
                        latest["code"] = code
                        latest["market"] = market
                        latest["display_name"] = name
                        latest["source"] = "eastmoney"
                        results.append(latest)
                except Exception as e:
                    logger.warning(f"自选股[{name}]主源采集异常: {e}")
            return results

        # 带降级的获取
        from collectors.fallback import fallback_manager
        results = fallback_manager.fetch_watchlist_with_fallback(
            stocks=watchlist,
            primary_fetcher=primary_fetch,
        )

        logger.info(f"自选股采集完成: {len(results)}/{len(watchlist)}")

        # 更新缓存
        self._watchlist_cache = results
        self._watchlist_cache_time = now_ts
        return results

    def get_watchlist_config(self) -> List[Dict]:
        """获取自选股配置列表（供 UI 展示）"""
        db_list = db.get_watchlist()
        if db_list:
            return db_list
        # 降级到 config.py
        return [
            {"stock_code": c, "market": m, "display_name": n, "sort_order": i + 1}
            for i, (c, m, n) in enumerate(CONFIG.portfolio.WATCHLIST)
        ]

    def add_watchlist_stock(self, code: str, market: str, name: str = "") -> Dict:
        """添加自选股"""
        # 清除缓存
        self._watchlist_cache = None
        market = market.lower()
        if market not in ("sh", "sz", "bj"):
            return {"success": False, "msg": "市场必须是 sh/sz/bj"}
        if not code.isdigit() or len(code) != 6:
            return {"success": False, "msg": "股票代码必须是 6 位数字"}
        added = db.add_watchlist(code, market, name)
        return {"success": True, "added": added, "msg": "添加成功" if added else "已存在"}

    def remove_watchlist_stock(self, code: str) -> Dict:
        """删除自选股"""
        self._watchlist_cache = None
        removed = db.remove_watchlist(code)
        return {"success": True, "removed": removed, "msg": "删除成功" if removed else "不存在"}

    def get_portfolio_summary(self) -> Dict:
        """
        自选股/持仓总体概览（补全持仓盈亏计算）
        """
        holdings = CONFIG.portfolio.HOLDINGS
        summary = {
            "total_watch": len(CONFIG.portfolio.WATCHLIST),
            "total_holding": len(holdings),
            "holding_value": 0.0,
            "holding_cost": 0.0,
            "holding_pnl": 0.0,
            "holding_pnl_pct": 0.0,
            "details": [],
        }

        if not holdings:
            return summary

        # 获取自选股最新价（复用缓存）
        watchlist_data = self.fetch_watchlist_flow()
        price_map = {}
        for item in watchlist_data:
            code = item.get("code", "")
            market = item.get("market", "")
            key = f"{code}.{market}"
            price_map[key] = self._safe_float(item.get("收盘价", item.get("最新价", 0)))

        for key, holding in holdings.items():
            shares = holding.get("shares", 0)
            avg_cost = holding.get("avg_cost", 0)
            current_price = price_map.get(key, 0)
            cost = shares * avg_cost
            value = shares * current_price
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0

            summary["holding_cost"] += cost
            summary["holding_value"] += value
            summary["holding_pnl"] += pnl
            summary["details"].append({
                "code": key,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })

        if summary["holding_cost"] > 0:
            summary["holding_pnl_pct"] = round(
                summary["holding_pnl"] / summary["holding_cost"] * 100, 2
            )
        return summary

    @staticmethod
    def _safe_float(v, default=0.0) -> float:
        if v is None:
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default


# 全局单例
engine = FlowEngine()
