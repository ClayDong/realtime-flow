"""
realtime-flow 配置模块
从各个专家维度设计的配置：
- 运维专家：可调参数全部集中，环境变量覆盖
- 架构专家：模块化配置，职责分离
- 股票专家：交易时段、轮询频率符合A股特性
"""
import os
from dataclasses import dataclass, field
from typing import List


# ─── 交易时间配置（股票专家） ─────────────────────────────────
# A股交易时段：上午 9:30-11:30，下午 13:00-15:00
TRADE_START_AM = 9 * 60 + 30   # 9:30
TRADE_END_AM = 11 * 60 + 30    # 11:30
TRADE_START_PM = 13 * 60       # 13:00
TRADE_END_PM = 15 * 60         # 15:00

# 集合竞价阶段的特殊数据可忽略，盘前9:00后可开始连接预热
PREHEAT_START = 9 * 60         # 9:00


def is_holiday(date_obj) -> bool:
    """判断是否为法定假日
    优先使用 chinese_calendar 库（精确到每年调休安排），降级到内置简化判断。
    """
    # 优先使用 chinese_calendar 库（精确）
    try:
        import chinese_calendar as cc
        # chinese_calendar 仅覆盖到一定年份范围，超出则降级
        on_holiday, holiday_name = cc.get_holiday_detail(date_obj)
        return bool(on_holiday)
    except (ImportError, NotImplementedError, ValueError):
        pass

    # 降级方案：内置简化判断（覆盖主要节假日区间）
    m, d = date_obj.month, date_obj.day
    if m == 1 and d <= 3:  # 元旦
        return True
    if m == 1 and d >= 20 or m == 2 and d <= 10:  # 春节区间
        return True
    if m == 4 and 4 <= d <= 6:  # 清明
        return True
    if m == 5 and 1 <= d <= 5:  # 劳动节
        return True
    if m == 6 and 8 <= d <= 15:  # 端午区间
        return True
    if m == 9 and 28 <= d <= 30:  # 中秋
        return True
    if m == 10 and 1 <= d <= 7:  # 国庆
        return True
    return False


@dataclass
class DataCollectionConfig:
    """数据采集配置 - 数据专家视角"""
    # 轮询间隔（秒）- 运维/数据专家：平衡数据新鲜度与反爬风险
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL", "120"))  # 2分钟

    # 个股资金流排名取前多少只
    STOCK_RANK_TOP_N: int = 200

    # 行业资金流排名数量（东方财富约 70+ 个行业）
    SECTOR_RANK_ALL: bool = True

    # 概念资金流是否采集
    CONCEPT_FLOW_ENABLED: bool = True

    # 沪深港通采集
    NORTH_SOUTH_BOUND_ENABLED: bool = True

    # 大单交易采集（数据量大，默认关）
    BIG_DEAL_ENABLED: bool = False

    # HTTP 请求超时（秒）
    REQUEST_TIMEOUT: int = 15

    # 重试次数
    REQUEST_RETRIES: int = 3


@dataclass
class AnalysisConfig:
    """分析引擎配置 - 算法专家/分析专家视角"""
    # 资金流信号阈值
    
    # 主力净占比 > 该值视为"强资金流入"
    STRONG_INFLOW_RATIO: float = 5.0  # %
    
    # 主力净占比 < 该值视为"强资金流出"
    STRONG_OUTFLOW_RATIO: float = -5.0  # %
    
    # 资金流入流出排名 TOP N
    SIGNAL_TOP_N: int = 10

    # 轮动检测：行业排名变化超过多少位视为"轮动"
    SECTOR_RANKING_CHANGE_THRESHOLD: int = 10

    # 北向资金日净流入阈值（亿元），超过视为显著
    NORTH_BOUND_DAILY_THRESHOLD: float = 30.0

    # 主力与北向共振：都大于各自阈值
    RESONANCE_ENABLED: bool = True


@dataclass
class StorageConfig:
    """存储配置 - 架构/运维专家视角"""
    DB_PATH: str = os.path.join(os.path.dirname(__file__), "db", "fund_flow.db")
    
    # 数据保留天数（运维专家：控制磁盘占用）
    RETENTION_DAYS: int = 180

    # 是否自动清理旧数据
    AUTO_CLEANUP: bool = True

    # 日终聚合时间（秒，15:00 后 n 秒做日终写入）
    EOD_DELAY_SECONDS: int = 60


@dataclass
class WebConfig:
    """Web 服务配置 - 用户体验/运维专家视角"""
    HOST: str = "0.0.0.0"
    PORT: int = 8899
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # WebSocket 推送间隔（秒）
    WS_PUSH_INTERVAL: int = 30

    # 页面自动刷新周期（秒）
    PAGE_REFRESH_INTERVAL: int = 30


@dataclass
class PortfolioConfig:
    """自选股/持仓配置 - 用户体验专家视角"""
    WATCHLIST: list = None
    HOLDINGS: dict = None

    def __post_init__(self):
        if self.WATCHLIST is None:
            self.WATCHLIST = [
                ("600519", "sh", "贵州茅台"),
                ("000858", "sz", "五粮液"),
                ("300750", "sz", "宁德时代"),
                ("601318", "sh", "中国平安"),
                ("000333", "sz", "美的集团"),
                ("600036", "sh", "招商银行"),
                ("002594", "sz", "比亚迪"),
                ("688981", "sh", "中芯国际"),
            ]
        if self.HOLDINGS is None:
            self.HOLDINGS = {}


@dataclass
class AppConfig:
    """应用总配置"""
    data: DataCollectionConfig = field(default_factory=DataCollectionConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)


# 全局单例
CONFIG = AppConfig()
