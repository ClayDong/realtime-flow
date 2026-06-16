# Realtime-Flow 资金流监测系统 · 技术文档

> 版本：v2.0.0 · 最后更新：2026-06-17
> 代码行数：约 4,100 行（Python 2,300 行 + JavaScript 700 行 + HTML/CSS 1,000 行 + Shell 85 行）
> 技术栈：Python 3.9+ / FastAPI / SQLite / WebSocket / Chart.js / AKShare / chinese_calendar

---

## 目录

1. [系统架构](#1-系统架构)
2. [技术栈选型](#2-技术栈选型)
3. [项目结构](#3-项目结构)
4. [模块详解](#4-模块详解)
5. [数据模型](#5-数据模型)
6. [API 文档](#6-api-文档)
7. [部署指南](#7-部署指南)
8. [配置指南](#8-配置指南)
9. [运维指南](#9-运维指南)
10. [内网穿透与外网访问](#10-内网穿透与外网访问)
11. [二次开发](#11-二次开发)
12. [常见问题](#12-常见问题)

---

## 1. 系统架构

### 1.1 架构全景图

```
┌────────────────────────────────────────────────────────────────────┐
│                         用户浏览器                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ 综合看板  │  │ 行业资金  │  │ 个股资金  │  │ Chart.js 趋势图   │  │
│  │ index.html│  │sectors.ht│  │stocks.ht │  │ 实时更新          │  │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────────┬─────────┘  │
│        └──────────────┴─────────────┴──────────────────┘            │
│                          │ WebSocket + HTTP                         │
└──────────────────────────┼──────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────┐
│                    FastAPI 服务 (port 8899)                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  main.py                                                     │   │
│  │  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌────────────┐  │   │
│  │  │ HTML Routes │ │ REST API   │ │WebSocket │ │ 后台轮询   │  │   │
│  │  │ GET /       │ │ GET /api/* │ │ /ws      │ │ asyncio    │  │   │
│  │  │ GET /sectors│ │ POST /api/*│ │          │ │ lifespan   │  │   │
│  │  │ GET /stocks │ │            │ │          │ │            │  │   │
│  │  └────────────┘ └────────────┘ └──────────┘ └────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                           │                                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  engine.py — 核心调度引擎                                     │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐  │   │
│  │  │ poll_once()    │ │ get_cache()    │ │ fetch_watchlist  │  │   │
│  │  │ 全流程编排      │ │ 缓存+DB回退    │ │ 自选股+降级      │  │   │
│  │  └───────┬────────┘ └───────┬────────┘ └──────────────────┘  │   │
│  │  ┌────────────────┐ ┌────────────────┐                       │   │
│  │  │get_portfolio() │ │ watchlist CRUD │                       │   │
│  │  │ 持仓盈亏        │ │ 自选股增删改   │                       │   │
│  │  └────────────────┘ └────────────────┘                       │   │
│  └──────────┬──────────────────┬────────────────────────────────┘   │
│             │                  │                                     │
│  ┌──────────▼──────────────────▼────────────────────────────────┐   │
│  │              数据采集层 (collectors/)                          │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐  │   │
│  │  │ MarketCollector│ │ SectorCollector│ │ StockCollector   │  │   │
│  │  │ 大盘+北向资金   │ │ 行业+概念资金   │ │ 个股排行+明细    │  │   │
│  │  └────────────────┘ └────────────────┘ └──────────────────┘  │   │
│  │  ┌────────────────────────────────────────────────────────┐  │   │
│  │  │ FallbackManager（v2.0 新增）                            │  │   │
│  │  │ · SinaStockCollector（新浪备用源）                      │  │   │
│  │  │ · TencentStockCollector（腾讯备用源）                   │  │   │
│  │  │ · 主源失败 3 次自动跳过 5 分钟                          │  │   │
│  │  └────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────┬────────────────────────────────────┘   │
│                             │ akshare / httpx                        │
│                    ┌────────▼────────┐                               │
│                    │  东方财富（主源） │                               │
│                    │  新浪（备用1）   │                               │
│                    │  腾讯（备用2）   │                               │
│                    └─────────────────┘                               │
│                                                                       │
│  ┌──────────────────────────┬────────────────────────────────────┐   │
│  │           分析引擎 (analyzers/)                                 │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐  │   │
│  │  │ 行业轮动分析    │ │ 个股评分      │ │ 市场分析        │  │   │
│  │  │ ·流入/流出TOP   │ │ ·综合评分     │ │ ·主力vs散户     │  │   │
│  │  │ ·机构关注      │ │ ·强度分级     │ │ ·北向分析       │  │   │
│  │  │ ·背离检测      │ │ ·涨跌停过滤   │ │ ·信号生成       │  │   │
│  │  │ ·轮动边界修复  │ │ ·对数归一化   │ │ ·同日去重       │  │   │
│  │  └────────────────┘ └────────────────┘ └──────────────────┘  │   │
│  │  ┌────────────────┐                                              │   │
│  │  │ SignalBacktest │（v2.0 新增）                                 │   │
│  │  │ ·信号准确率统计│                                              │   │
│  │  │ ·N日验证       │                                              │   │
│  │  └────────────────┘                                              │   │
│  └──────────────────────────┬────────────────────────────────────┘   │
│                             │                                         │
│  ┌──────────────────────────▼────────────────────────────────────┐   │
│  │                    数据存储层 (db/)                            │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐  │   │
│  │  │ market_flow    │ │sector_flow_    │ │ stock_flow_      │  │   │
│  │  │ 大盘日表       │ │ snapshot       │ │ snapshot         │  │   │
│  │  └────────────────┘ └────────────────┘ └──────────────────┘  │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐  │   │
│  │  │ signals        │ │concept_flow_   │ │ watchlist（v2.0）│  │   │
│  │  │ 信号(去重)     │ │ snapshot       │ │ 自选股(UI管理)   │  │   │
│  │  └────────────────┘ └────────────────┘ └──────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 数据流时序

```
Browser                    FastAPI                    Engine               Collectors           EastMoney/Sina/Tencent
   │                          │                         │                     │                    │
   │  GET /                   │                         │                     │                    │
   │─────────────────────────►│                         │                     │                    │
   │  index.html              │                         │                     │                    │
   │◄─────────────────────────│                         │                     │                    │
   │                          │                         │                     │                    │
   │  WS /ws                  │                         │                     │                    │
   │══════════════════════════►│                         │                     │                    │
   │                          │                         │                     │                    │
   │                          │  后台轮询 (每 120s)     │                     │                    │
   │                          │────────────────────────►│                     │                    │
   │                          │                         │  poll_once()        │                    │
   │                          │                         │  is_holiday()? ─── 否 ──► 采集             │
   │                          │                         │                     │ GET 东方财富        │
   │                          │                         │                     │───────────────────►│
   │                          │                         │                     │◄───────────────────│
   │                          │                         │                     │ 失败? 降级到新浪/腾讯 │
   │                          │                         │◄────────────────────│                    │
   │                          │                         │                     │                    │
   │                          │                         │  analyze_sector()   │                    │
   │                          │                         │  analyze_stock()    │                    │
   │                          │                         │  analyze_market()   │                    │
   │                          │                         │  save_signal() 去重 │                    │
   │                          │                         │                     │                    │
   │                          │◄────────────────────────│                     │                    │
   │                          │                         │                     │                    │
   │  push data_update        │                         │                     │                    │
   │◄══════════════════════════│                         │                     │                    │
   │                          │                         │                     │                    │
   │  renderAll()             │                         │                     │                    │
   │  ── renderStatusBar() (时效性)                    │                     │                    │
   │  ── renderMarket()       │                         │                     │                    │
   │  ── renderSector()       │                         │                     │                    │
   │  ── renderStock()        │                         │                     │                    │
   │  ── renderSignal()       │                         │                     │                    │
   │  ── renderWatchlist() (含CRUD按钮)                │                     │                    │
```

---

## 2. 技术栈选型

### 2.1 选型决策

| 层级 | 选型 | 版本 | 选型理由 |
|------|------|------|----------|
| 编程语言 | Python | 3.9+ | 数据生态完善，akshare/chinese_calendar 等库支持 |
| Web 框架 | FastAPI | 0.100+ | 原生异步支持、WebSocket 内置、高性能 |
| Web 服务器 | Uvicorn | 0.20+ | ASGI 标准，与 FastAPI 原生集成 |
| 前端 | 原生 HTML/CSS/JS | — | 零依赖、无框架锁定、维护成本最低 |
| 可视化 | Chart.js | 4.4+ (CDN) | 轻量(70KB)、响应式、深色主题友好 |
| 数据库 | SQLite | 3.30+ | 零配置、单文件、适合本地部署 |
| ORM | 原生 sqlite3 | — | 轻量场景不需要 ORM 层 |
| 主数据源 | AKShare | 1.10+ | 覆盖东方财富全接口、社区活跃 |
| 备用数据源 | httpx | 0.24+ | 直接调用新浪/腾讯 HTTP 接口 |
| 节假日判断 | chinese_calendar | 1.9+ | 精确到每年调休安排 |
| 定时调度 | APScheduler + asyncio | 3.10+ | 可靠的定时任务，与异步框架兼容 |
| 进程守护 | Screen + launchd | — | macOS 原生守护、崩溃自动重启 |
| 实时推送 | WebSocket | — | 浏览器原生支持，比 SSE 更通用 |

### 2.2 为什么不选...（决策记录）

| 候选方案 | 淘汰理由 |
|----------|----------|
| **Django** | 太重，本项目是单页应用，不需要 ORM/Admin/Auth |
| **Streamlit** | 版本升级容易 break，自定义程度低，WebSocket 支持弱 |
| **Dash** | 学习曲线陡，调试困难，前端定制不灵活 |
| **React/Vue** | 需要构建工具链，维护成本高，单页场景大材小用 |
| **PostgreSQL** | 单机部署不需要，SQLite 完全够用 |
| **Redis** | 内存缓存非必需，SQLite 加内存缓存已足够 |
| **Docker** | 单机部署增加复杂度，Python 直接运行更简单 |

---

## 3. 项目结构

```
realtime-flow/
│
├── config.py                 # 全局配置（含节假日判断函数）
├── engine.py                 # 核心调度引擎（轮询/缓存/自选股/持仓）
├── main.py                   # FastAPI 入口（路由/WebSocket/生命周期）
├── start.sh                  # 运维管理脚本（start/stop/status/logs/launchd）
├── requirements.txt          # Python 依赖清单
│
├── collectors/               # 数据采集层
│   ├── __init__.py
│   ├── base.py               # BaseCollector 抽象基类
│   ├── market_collector.py   # 大盘资金流 + 北向资金采集器
│   ├── sector_collector.py   # 行业/概念资金流采集器
│   ├── stock_collector.py    # 个股资金流排行+明细采集器
│   └── fallback.py           # v2.0 新增：备用数据源 + 降级管理器
│
├── analyzers/                # 分析引擎层
│   ├── __init__.py
│   ├── engine.py             # 分析引擎（行业轮动/个股评分/市场分析）
│   └── backtest.py           # v2.0 新增：信号回测引擎
│
├── db/                       # 数据存储层
│   ├── __init__.py
│   ├── models.py             # SQLite 模型 + DAO（6 张表）
│   └── fund_flow.db          # SQLite 数据库文件（运行时自动创建）
│
├── static/                   # 前端静态资源
│   ├── css/
│   │   └── style.css         # 深色主题样式
│   └── js/
│       └── app.js            # 前端应用逻辑（WebSocket/渲染/图表/CRUD）
│
├── templates/                # Jinja2 模板
│   ├── index.html            # 综合看板
│   ├── sectors.html          # 行业资金页面
│   └── stocks.html           # 个股资金页面（含分页）
│
├── PRODUCT_DOC.md            # 产品文档
└── TECH_DOC.md               # 技术文档（本文件）
```

---

## 4. 模块详解

### 4.1 config.py — 配置模块

集中管理所有可调参数，按领域拆分为 5 个配置类：

```python
@dataclass
class DataCollectionConfig:   # 数据采集参数
    POLL_INTERVAL_SECONDS: int = 120    # 轮询间隔
    STOCK_RANK_TOP_N: int = 200         # 个股排行取前 N
    REQUEST_TIMEOUT: int = 15           # HTTP 超时
    REQUEST_RETRIES: int = 3            # 重试次数

@dataclass
class AnalysisConfig:         # 分析引擎参数
    STRONG_INFLOW_RATIO: float = 5.0    # 强流入阈值(%)
    SIGNAL_TOP_N: int = 10              # 信号 TOP N
    SECTOR_RANKING_CHANGE_THRESHOLD: int = 10  # 轮动检测阈值

@dataclass
class StorageConfig:          # 存储参数
    RETENTION_DAYS: int = 180           # 数据保留天数
    AUTO_CLEANUP: bool = True           # 自动清理

@dataclass
class WebConfig:              # Web 服务参数
    HOST: str = "0.0.0.0"
    PORT: int = 8899
    WS_PUSH_INTERVAL: int = 30

@dataclass
class PortfolioConfig:        # 自选股配置
    WATCHLIST: list = [... ]            # 预设 8 只股票（启动时初始化到 DB）
    HOLDINGS: dict = {}                  # 持仓（可自定义）
```

**节假日判断函数**（v2.0 新增）：
```python
def is_holiday(date_obj) -> bool:
    """优先使用 chinese_calendar 库，降级到内置简化判断"""
    try:
        import chinese_calendar as cc
        on_holiday, _ = cc.get_holiday_detail(date_obj)
        return bool(on_holiday)
    except (ImportError, NotImplementedError, ValueError):
        # 降级方案：内置简化判断
        ...
```

### 4.2 collectors/ — 数据采集层

#### 设计模式：模板方法模式

```python
class BaseCollector(ABC):
    """抽象基类"""
    def safe_fetch(self):      # 模板方法：异常安全包装
        try:
            return self.fetch()
        except Exception as e:
            logger.error(...)
            return None

    @abstractmethod
    def fetch(self):           # 子类必须实现
        ...
```

#### MarketCollector
- `stock_market_fund_flow()` — 大盘历史资金流（最近一日）
- `stock_hsgt_fund_min_em()` — 北向资金分钟级数据
- 输出：结构化的 `Dict`，包含 `market` 和 `north_bound` 两个子字典

#### SectorCollector
- `stock_sector_fund_flow_rank()` — 行业/概念/地域资金流排名
- `stock_sector_fund_flow_hist()` — 单行业历史资金流
- `stock_fund_flow_concept()` — 概念资金流（独立接口）
- 输出：按 tag（今日/5日/概念）组织的列表

#### StockCollector
- `stock_individual_fund_flow_rank()` — 全市场排行（今日/3日/5日/10日）
- `stock_individual_fund_flow()` — 单只个股历史明细
- `stock_main_fund_flow()` — 主力净流入排名（补充维度）
- 支持批量获取（限制 20 只避免反爬）

#### FallbackManager（v2.0 新增）

**三级降级机制**：
```python
class FallbackManager:
    def fetch_watchlist_with_fallback(self, stocks, primary_fetcher):
        # 1. 尝试主源（东方财富）
        if primary_fetcher and not self.should_skip_main():
            result = primary_fetcher()
            if result:
                self.record_main_success()
                return result
            self.record_main_failure()

        # 2. 降级到新浪
        result = self.sina.fetch_batch(stocks)
        if result: return result

        # 3. 降级到腾讯
        result = self.tencent.fetch_batch(stocks)
        if result: return result
```

**主源失败策略**：连续失败 3 次，跳过主源 5 分钟，避免无效重试。

**备用源接口**：
- 新浪：`https://hq.sinajs.cn/list=sh600519,sz000858`（需 Referer 头）
- 腾讯：`https://qt.gtimg.cn/q=sh600519,sz000858`

### 4.3 analyzers/ — 分析引擎

#### analyzers/engine.py 核心算法

**行业轮动分析**（v2.0 修复边界）：
1. 按 `主力净流入-净额` 排序 → 流入 TOP / 流出 TOP
2. 按 `超大单净流入-净额` 排序 → 机构关注
3. 遍历检测背离
4. 计算轮动强度：
   - 有流出板块：`sum(流入TOP5) / |sum(流出TOP5)|`
   - 无流出板块（普涨）：返回 0.0，提示"市场普涨，无明显轮动"

**个股评分算法**（v2.0 优化权重 + 对数归一化）：
```python
# 过滤涨跌停
limit_pct = 5.0 if is_st else (20.0 if 创科板 else 10.0)
if abs(pct) >= limit_pct - 0.01:
    continue  # 跳过涨跌停股

# 评分（主力净占比权重最高，最可靠）
score = (
    0.45 * normalize(main_ratio, -10, 10)        # 主力净占比（相对值）
    + 0.25 * normalize_log(main_in)               # 主力净额（对数归一化）
    + 0.20 * normalize(super_large, -5, 5)        # 超大单净额
    + 0.10 * normalize(large, -3, 3)              # 大单净额
)
```

**对数归一化**（v2.0 新增）：
```python
def _normalize_log(v: float) -> float:
    """避免大盘股霸榜：正值 log10(v+1)/2.4 映射到 [0.5, 1]"""
    if v > 0:
        return 0.5 + min(math.log10(v + 1) / 2.4, 1.0) * 0.5
    else:
        return 0.5 - min(math.log10(abs(v) + 1) / 2.4, 1.0) * 0.5
```

**市场分析**（v2.0 优化）：不再绝对化判断"健康/危险"，提示需结合位置判断。

#### analyzers/backtest.py 信号回测（v2.0 新增）

```python
class SignalBacktester:
    def backtest_signals(self, days=30, forward_days=5):
        # 1. 拉取最近 N 天的信号
        # 2. 对每个信号，找到发出当天的行业数据
        # 3. 查看信号发出后 forward_days 天的涨跌幅
        # 4. 判断准确性：
        #    - 底背离 → 预期后续上涨，实际 > 0 为正确
        #    - 顶背离 → 预期后续下跌，实际 < 0 为正确
        # 5. 统计总体准确率和分类型准确率
```

### 4.4 engine.py — 核心调度引擎

#### 轮询生命周期

```
is_market_hours()? (含节假日判断)
  ├── 否 → sleep 3600s
  └── 是 →
       ├── market_collector.safe_fetch() → db.save_market_flow()
       ├── sector_collector.safe_fetch() → db.save_sector_snapshot()
       ├── concept_collector.safe_fetch() → db.save_concept_snapshot()
       ├── stock_collector.safe_fetch() → db.save_stock_snapshot()
       ├── analyzer.analyze_sector_rotation()
       ├── analyzer.analyze_stock_flow()
       ├── analyzer.analyze_market_overview()
       ├── analyzer.analyze_concept_hotspot()
       ├── 更新 self.latest_data 缓存
       ├── broadcast() → WebSocket 推送
       └── sleep(POLL_INTERVAL_SECONDS)
```

#### 缓存回退机制

当缓存数据不完整时，自动从 SQLite 数据库重建。

#### 自选股管理（v2.0 新增）

- `fetch_watchlist_flow()` — 带 2 分钟缓存 + 多源降级
- `get_watchlist_config()` — 从 DB 读取自选股列表
- `add_watchlist_stock()` — 添加自选股（含校验）
- `remove_watchlist_stock()` — 删除自选股
- `get_portfolio_summary()` — 持仓盈亏计算

### 4.5 main.py — Web 服务

#### 路由表

| 方法 | 路径 | 功能 | 返回类型 |
|------|------|------|----------|
| GET | `/` | 综合看板 | HTML |
| GET | `/sectors` | 行业资金页面 | HTML |
| GET | `/stocks` | 个股资金页面 | HTML |
| GET | `/api/data` | 最新缓存数据 | JSON |
| GET | `/api/stats` | 系统运行统计 | JSON |
| GET | `/api/watchlist` | 自选股资金流 | JSON |
| GET | `/api/watchlist/config` | v2.0 自选股配置列表 | JSON |
| POST | `/api/watchlist/add` | v2.0 添加自选股 | JSON |
| POST | `/api/watchlist/remove` | v2.0 删除自选股 | JSON |
| GET | `/api/portfolio` | 持仓概览（v2.0 补全盈亏） | JSON |
| GET | `/api/backtest/signals` | v2.0 信号回测 | JSON |
| GET | `/api/db/recent` | 数据库最近记录 | JSON |
| GET | `/api/history/sectors` | 行业历史资金流 | JSON |
| GET | `/api/history/stock` | 个股历史资金流 | JSON |
| GET | `/health` | 健康检查 | JSON |
| WS | `/ws` | 实时推送 | WebSocket |

#### WebSocket 协议

```javascript
// 服务端 → 客户端
{
    "type": "data_update",
    "data": { /* 完整的缓存数据 */ },
    "timestamp": "2026-06-17T00:00:00"
}

// 客户端 → 服务端
"ping"  // 心跳

// 服务端 → 客户端
{"type": "pong"}
```

### 4.6 static/js/app.js — 前端核心

#### 类架构

```
App
├── WSManager          // WebSocket 连接管理
├── TrendChartManager  // Chart.js 图表管理
├── fetchInitialData()
├── fetchWatchlist()
├── renderAll()        // 主渲染入口
│   ├── renderStatusBar() (v2.0 数据时效性)
│   ├── renderMarketOverview()
│   ├── renderSectorAnalysis()
│   ├── renderSectorTrendChart()
│   ├── renderStockAnalysis()
│   ├── renderConceptAnalysis()
│   ├── renderSignals()
│   ├── renderTimestamp()
│   ├── renderWatchlist() (v2.0 含 CRUD 按钮)
│   ├── renderStockFull()     // stocks.html 专用（v2.0 分页）
│   └── renderSectorFullTable() // sectors.html 专用
├── showAddWatchlistDialog()  // v2.0 新增
├── removeWatchlist()         // v2.0 新增
└── utils              // 工具函数
```

---

## 5. 数据模型

### 5.1 表结构

#### market_flow（大盘资金流日表）

| 列名 | 类型 | 说明 |
|------|------|------|
| date | TEXT PK | 日期 |
| sh_close | REAL | 上证收盘价 |
| sh_change | REAL | 上证涨跌幅(%) |
| sz_close | REAL | 深证收盘价 |
| sz_change | REAL | 深证涨跌幅(%) |
| main_net_inflow | REAL | 主力净流入(亿) |
| main_net_ratio | REAL | 主力净占比(%) |
| super_large_inflow | REAL | 超大单净流入(亿) |
| large_inflow | REAL | 大单净流入(亿) |
| medium_inflow | REAL | 中单净流入(亿) |
| small_inflow | REAL | 小单净流入(亿) |
| north_bound_total | REAL | 北向资金合计(亿) |
| updated_at | TIMESTAMP | 更新时间 |

#### sector_flow_snapshot / stock_flow_snapshot / concept_flow_snapshot

（结构同 v1.0，略）

#### signals（信号/预警表，v2.0 增加同日去重）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| signal_time | TIMESTAMP | 信号时间 |
| signal_type | TEXT | 类型(sector_divergence/market_signal) |
| signal_name | TEXT | 信号名称 |
| stock_code | TEXT | 关联股票代码 |
| stock_name | TEXT | 关联股票名称 |
| sector_name | TEXT | 关联行业名称 |
| value | REAL | 数值 |
| description | TEXT | 描述 |
| raw_json | TEXT | 原始数据 |

**去重规则**：同一天同类型同名称同板块的信号不重复写入。

#### watchlist（v2.0 新增：自选股表）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| stock_code | TEXT NOT NULL UNIQUE | 股票代码 |
| market | TEXT NOT NULL | 市场(sh/sz/bj) |
| display_name | TEXT | 显示名称 |
| added_at | TIMESTAMP | 添加时间 |
| sort_order | INTEGER | 排序序号 |

### 5.2 SQLite 运维

```sql
-- 查看数据库大小
SELECT page_count * page_size / 1024 AS size_kb
FROM pragma_page_count(), pragma_page_size();

-- 查看各表记录数
SELECT 'sector' AS tbl, COUNT(*) FROM sector_flow_snapshot
UNION ALL SELECT 'stock', COUNT(*) FROM stock_flow_snapshot
UNION ALL SELECT 'concept', COUNT(*) FROM concept_flow_snapshot
UNION ALL SELECT 'signal', COUNT(*) FROM signals
UNION ALL SELECT 'watchlist', COUNT(*) FROM watchlist;

-- 查看自选股列表
SELECT stock_code, market, display_name FROM watchlist ORDER BY sort_order;

-- 手动清理旧数据
DELETE FROM sector_flow_snapshot WHERE snapshot_time < datetime('now', '-180 days');
DELETE FROM signals WHERE signal_time < datetime('now', '-180 days');
VACUUM;
```

---

## 6. API 文档

### 6.1 数据 API

#### GET /api/data
返回系统最新缓存数据（优先内存缓存，回退到数据库）。

#### GET /api/watchlist
返回自选股资金流明细（带 2 分钟缓存 + 多源降级）。

**响应示例**：
```json
{
  "data": [
    {
      "display_name": "贵州茅台",
      "code": "600519",
      "market": "sh",
      "日期": "2026-06-17",
      "收盘价": 1255.67,
      "涨跌幅": -1.21,
      "主力净流入-净额": 5.2,
      "主力净流入-净占比": 3.47,
      "source": "sina"
    }
  ],
  "count": 8
}
```

#### GET /api/watchlist/config（v2.0 新增）
返回自选股配置列表。

#### POST /api/watchlist/add（v2.0 新增）
添加自选股。

**请求体**：
```json
{"code": "000001", "market": "sz", "name": "平安银行"}
```

**响应**：
```json
{"success": true, "added": true, "msg": "添加成功"}
```

#### POST /api/watchlist/remove（v2.0 新增）
删除自选股。

**请求体**：
```json
{"code": "000001"}
```

#### GET /api/portfolio（v2.0 补全盈亏）
返回持仓概览（含盈亏计算）。

**响应示例**：
```json
{
  "total_watch": 8,
  "total_holding": 2,
  "holding_value": 180000.0,
  "holding_cost": 175000.0,
  "holding_pnl": 5000.0,
  "holding_pnl_pct": 2.86,
  "details": [
    {
      "code": "600519.sh",
      "shares": 100,
      "avg_cost": 1800.0,
      "current_price": 1850.0,
      "pnl": 5000.0,
      "pnl_pct": 2.78
    }
  ]
}
```

#### GET /api/backtest/signals（v2.0 新增）
信号回测验证。

**参数**：
- `days`: 回测最近多少天的信号（默认 30）
- `forward_days`: 信号发出后多少天验证结果（默认 5）

**响应示例**：
```json
{
  "total_signals": 15,
  "validated": 10,
  "correct": 7,
  "accuracy": 70.0,
  "by_type": {
    "底背离（资金流入但下跌）": {"total": 5, "correct": 4, "accuracy": 80.0},
    "顶背离（资金流出但上涨）": {"total": 5, "correct": 3, "accuracy": 60.0}
  },
  "details": [...],
  "forward_days": 5,
  "backtest_days": 30
}
```

#### GET /api/stats
系统运行统计。

#### GET /health
健康检查。

### 6.2 WebSocket API

**连接端点**：`ws://localhost:8899/ws`

**协议**：
- 服务端在数据更新后自动推送 `{"type": "data_update", "data": {...}}`
- 客户端每 30 秒发送 `"ping"` 保持连接
- 服务端回复 `{"type": "pong"}`

---

## 7. 部署指南

### 7.1 环境要求

| 依赖 | 最低版本 | 备注 |
|------|----------|------|
| Python | 3.9+ | 推荐 3.10+ |
| pip | 21+ | 安装依赖用 |
| Screen | 4+ | macOS/Linux 进程守护 |
| 网络 | — | 需要访问东方财富/新浪/腾讯 API |

### 7.2 安装步骤

```bash
# 1. 进入项目目录
cd /path/to/realtime-flow

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 启动服务
bash start.sh start

# 4. 验证
curl http://localhost:8899/health

# 5. 访问
open http://localhost:8899
```

### 7.3 依赖清单（requirements.txt）

```txt
fastapi>=0.100.0
uvicorn>=0.20.0
akshare>=1.10.0
aiosqlite>=0.19.0
APScheduler>=3.10.0
jinja2>=3.1.0
httpx>=0.24.0
pandas>=2.0.0
chinese_calendar>=1.9.0
```

### 7.4 启动方式

| 方式 | 命令 | 特点 |
|------|------|------|
| 前台调试 | `python3 main.py` | 实时看日志，Ctrl+C 停止 |
| Screen 守护 | `bash start.sh start` | 后台运行，SSH 断开不停止 |
| Launchd 开机自启 | `bash start.sh launchd-install` | 重启后自动启动 |
| 手动后台 | `python3 main.py & disown` | 简单但可能被系统回收 |

---

## 8. 配置指南

### 8.1 自选股配置

**方式一：UI 管理（推荐，v2.0 新增）**
- 打开 http://localhost:8899
- 在自选股面板点击"+ 添加"按钮
- 输入代码、市场、名称即可

**方式二：编辑 config.py（初始默认值）**
```python
WATCHLIST = [
    ("600519", "sh", "贵州茅台"),   # (代码, 市场, 显示名称)
    ("000858", "sz", "五粮液"),
    # market: sh=上交所, sz=深交所, bj=北交所
]
```

> 注意：启动时如果 watchlist 表为空，会用 config.py 的值初始化。之后通过 UI 修改的会持久化到数据库。

### 8.2 持仓配置（可选）

```python
HOLDINGS = {
    "600519.sh": {"shares": 100, "avg_cost": 1800.0},  # 100股，成本1800
    "300750.sz": {"shares": 200, "avg_cost": 210.0},
}
```

### 8.3 轮询间隔调整

```bash
# 环境变量方式（推荐，不改代码）
export POLL_INTERVAL=60  # 改为 60 秒轮询一次
python3 main.py
```

### 8.4 Web 端口修改

```bash
# 改 config.py
WebConfig.PORT = 9999

# 或环境变量
export WEB_PORT=9999
```

---

## 9. 运维指南

### 9.1 管理命令

```bash
bash start.sh status          # 查看运行状态
bash start.sh logs            # 实时查看日志
bash start.sh stop            # 停止服务
bash start.sh start           # 启动服务
bash start.sh restart         # 重启服务
bash start.sh launchd-install # 安装开机自启
bash start.sh launchd-remove  # 移除开机自启
```

### 9.2 日志查看

```bash
# 实时日志
tail -f /tmp/realtime-flow.log

# 搜索错误
grep -i "error\|exception\|failed" /tmp/realtime-flow.log

# 查看数据源降级
grep -E "降级|主源|sina|tencent" /tmp/realtime-flow.log

# 查看自选股采集
grep "自选股采集" /tmp/realtime-flow.log
```

### 9.3 数据维护

```bash
# 查看数据库大小
ls -lh db/fund_flow.db

# 手动清理旧数据（保留30天）
sqlite3 db/fund_flow.db "DELETE FROM sector_flow_snapshot WHERE snapshot_time < datetime('now', '-30 days')"
sqlite3 db/fund_flow.db "DELETE FROM signals WHERE signal_time < datetime('now', '-30 days')"
sqlite3 db/fund_flow.db "VACUUM"

# 重置数据库（谨慎！）
rm db/fund_flow.db
```

### 9.4 故障恢复

| 故障现象 | 排查步骤 | 解决方案 |
|----------|----------|----------|
| 服务无法启动 | `tail -20 /tmp/realtime-flow.log` | 检查端口占用或 Python 错误 |
| 端口占用 | `lsof -i :8899` | `kill -9 PID` 或改端口 |
| 页面白屏 | 检查浏览器控制台网络请求 | 确认服务进程存活 |
| 无数据 | `curl /api/data` | 非交易时段正常，等开盘 |
| 主源失败 | 查看日志"降级"关键字 | 自动降级到新浪/腾讯，无需处理 |
| WebSocket 断连 | 查看浏览器 WS 状态 | 自动重连，5 秒后恢复 |
| 数据库过大 | `ls -lh db/fund_flow.db` | 手动清理或调小 RETENTION_DAYS |

---

## 10. 内网穿透与外网访问

本节介绍如何让外网用户通过域名访问本地运行的 realtime-flow 服务。

### 10.1 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **Cloudflare Tunnel** | 免费、无需公网IP、自动HTTPS、隐藏真实IP | 需境外网络通畅 | ★★★★★ |
| **frp** | 开源、可控、支持TCP/UDP | 需要有公网IP的服务器 | ★★★★☆ |
| **ngrok** | 配置简单、免费版可用 | 免费版有带宽限制、URL会变 | ★★★☆☆ |
| **阿里云ECS + 反向代理** | 稳定、带宽可控 | 需付费购买ECS | ★★★★☆ |
| **花生壳** | 国内服务、中文界面 | 免费版限制多 | ★★☆☆☆ |

### 10.2 方案一：Cloudflare Tunnel（推荐）

**适用场景**：你有阿里域名 + 想免费 + 不想买公网IP服务器

#### 前置条件
- 一个域名（你已有阿里域名）
- Cloudflare 账号（免费注册）
- 本地 Mac 能访问 Cloudflare API

#### 步骤 1：域名接入 Cloudflare

1. **注册 Cloudflare 账号**：https://dash.cloudflare.com/sign-up
2. **添加站点**：登录后点击"Add a Site"，输入你的阿里域名
3. **选择 Free 计划**：免费版完全够用
4. **获取 Cloudflare NS 服务器**：Cloudflare 会给你两个 NS 地址，类似：
   ```
   ns1.cloudflare.com
   ns2.cloudflare.com
   ```

#### 步骤 2：在阿里云修改 NS 服务器

1. 登录 **阿里云域名控制台**：https://dc.console.aliyun.com
2. 找到你的域名 → 点击"管理"
3. 点击"DNS 修改" → "修改 DNS 服务器"
4. 将默认的阿里 DNS 改为 Cloudflare 的 NS：
   ```
   dns1.cloudflare.com
   dns2.cloudflare.com
   ```
5. 等待 10 分钟~24 小时生效（通常 30 分钟内）

**验证 NS 是否生效**：
```bash
dig NS yourdomain.com +short
# 应返回 cloudflare 的 NS
```

#### 步骤 3：安装 cloudflared

```bash
# macOS
brew install cloudflared

# 验证
cloudflared --version
```

#### 步骤 4：登录认证

```bash
cloudflared tunnel login
```
会自动打开浏览器，选择你的域名授权。授权后会在 `~/.cloudflared/` 生成 `cert.pem`。

#### 步骤 5：创建 Tunnel

```bash
cloudflared tunnel create realtime-flow
```
会输出一个 Tunnel ID（UUID），记下来。同时在 `~/.cloudflared/` 生成 `<UUID>.json` 凭证文件。

#### 步骤 6：配置 Tunnel

创建配置文件 `~/.cloudflared/config.yml`：

```yaml
tunnel: <你的Tunnel-UUID>
credentials-file: ~/.cloudflared/<你的Tunnel-UUID>.json

ingress:
  # 将 stock.yourdomain.com 映射到本地 8899 端口
  - hostname: stock.yourdomain.com
    service: http://localhost:8899
  - service: http_status:404
```

#### 步骤 7：添加 DNS 记录

```bash
# 自动在 Cloudflare 添加 CNAME 记录
cloudflared tunnel route dns realtime-flow stock.yourdomain.com
```

#### 步骤 8：启动 Tunnel

```bash
# 前台测试
cloudflared tunnel run realtime-flow

# 后台运行（推荐）
cloudflared tunnel run realtime-flow & disown

# 或配置为 launchd 服务（开机自启）
cloudflared service install
```

#### 步骤 9：访问验证

```bash
# 健康检查
curl https://stock.yourdomain.com/health

# 浏览器访问
open https://stock.yourdomain.com
```

#### 常见问题

**Q: WebSocket 能正常工作吗？**
A: 可以。Cloudflare Tunnel 原生支持 WebSocket，无需额外配置。

**Q: 访问速度慢？**
A: Cloudflare 在国内没有节点，可能稍慢。可考虑：
- 用 Cloudflare 的"中国网络"功能（需企业版）
- 改用 frp + 阿里云ECS 方案

**Q: 需要备案吗？**
A: 域名解析到 Cloudflare（境外）不需要备案。但如果解析到阿里云国内ECS，需要ICP备案。

### 10.3 方案二：frp + 阿里云 ECS

**适用场景**：你有一台阿里云 ECS（带公网IP）

#### 服务端（阿里云 ECS）

```bash
# 下载 frp
wget https://github.com/fatedier/frp/releases/download/v0.61.0/frp_0.61.0_linux_amd64.tar.gz
tar -xzf frp_0.61.0_linux_amd64.tar.gz
cd frp_0.61.0_linux_amd64
```

编辑 `frps.ini`：
```ini
[common]
bind_port = 7000
vhost_http_port = 80
vhost_https_port = 443
dashboard_addr = 0.0.0.0
dashboard_port = 7500
dashboard_user = admin
dashboard_pwd = your_password
```

启动：
```bash
./frps -c frps.ini
```

#### 客户端（本地 Mac）

编辑 `frpc.ini`：
```ini
[common]
server_addr = 你的ECS公网IP
server_port = 7000

[realtime-flow]
type = http
local_ip = 127.0.0.1
local_port = 8899
custom_domains = stock.yourdomain.com
```

启动：
```bash
./frpc -c frpc.ini
```

#### 阿里云域名解析

在阿里云 DNS 控制台添加 A 记录：
- 主机记录：`stock`
- 记录类型：`A`
- 记录值：`你的ECS公网IP`

### 10.4 安全建议

外网暴露后务必加强安全：

1. **加访问认证**（推荐）：在 Cloudflare 开启 "Cloudflare Access"，配置邮箱白名单
2. **限流**：Cloudflare 免费版自带 DDoS 防护和限流
3. **关闭危险 API**：外网暴露时建议在 main.py 中注释掉 `/api/watchlist/add` 等写操作
4. **改默认端口**：虽然 Cloudflare Tunnel 不暴露真实端口，但养成好习惯
5. **定期查日志**：`grep "POST /api" /tmp/realtime-flow.log`

### 10.5 你需要提供的信息

如果你希望我帮你配置具体的内网穿透，请提供：

1. **你的域名**（例如：`example.com`）
2. **想用的子域名**（例如：`stock.example.com`）
3. **选择的方案**（Cloudflare Tunnel / frp / 其他）
4. **是否有阿里云 ECS**（如果有，用于 frp 方案）
5. **是否需要访问认证**（防止陌生人访问）

---

## 11. 二次开发

### 11.1 添加新的采集器

```python
# collectors/my_collector.py
from .base import BaseCollector

class MyCollector(BaseCollector):
    def __init__(self):
        super().__init__("自定义数据")

    def fetch(self):
        # 你的采集逻辑
        return {"key": "value"}
```

然后在 `engine.py` 的 `poll_once()` 中添加调用。

### 11.2 添加新的备用数据源

参考 `collectors/fallback.py` 的实现：
1. 继承 `BaseCollector`
2. 实现 `fetch_batch()` 方法
3. 在 `FallbackManager.fetch_watchlist_with_fallback` 中添加降级链

### 11.3 添加新的分析模型

```python
# analyzers/engine.py 的 FlowAnalyzer 类中添加
def analyze_my_model(self, data):
    """自定义分析"""
    return {"result": "analysis"}
```

### 11.4 添加新的 API 路由

```python
# main.py 中添加
@app.get("/api/my-custom")
async def my_custom():
    return {"data": engine.some_method()}
```

---

## 12. 常见问题

### 12.1 非交易时段为什么看不到数据？

东方财富资金流接口在非交易时段（15:00-次日 9:00）和周末会拒绝连接。v2.0 后自选股会自动降级到新浪/腾讯获取基本行情。系统在节假日不轮询（v2.0 新增 chinese_calendar 判断）。

### 12.2 数据多久更新一次？

默认每 **2 分钟** 轮询一次。自选股有 2 分钟缓存，避免频繁请求。

### 12.3 如何修改自选股名单？

**v2.0 推荐**：打开网页，在自选股面板点击"+ 添加"或"删除"按钮，无需改代码重启。

### 12.4 主源失败怎么办？

系统自动降级到新浪/腾讯备用源，无需人工干预。查看日志：
```bash
grep "降级" /tmp/realtime-flow.log
```

### 12.5 信号会重复写入吗？

不会。v2.0 增加了同日去重逻辑，同一天同类型同板块的信号只写入一次。

### 12.6 信号准确率怎么看？

访问 `http://localhost:8899/api/backtest/signals?days=30&forward_days=5` 查看回测报告。

### 12.7 数据库会不会无限增长？

系统默认保留 **180 天** 的数据，每天凌晨自动清理旧数据。signals 表使用 `signal_time` 字段清理（v2.0 修复了 v1.0 误用 `snapshot_time` 的 bug）。

### 12.8 服务会自动重启吗？

如果使用 `launchd-install` 安装了 launchd 服务（macOS），系统会在崩溃或重启后自动拉起。

### 12.9 能在 Windows 上用吗？

可以。Python 部分跨平台兼容。`start.sh` 需要改用 `.bat` 脚本或直接用 `python3 main.py` 启动。

### 12.10 外网访问如何配置？

参考[第 10 节：内网穿透与外网访问](#10-内网穿透与外网访问)。

---

## 附录

### A. 核心依赖版本兼容性

| 依赖 | 最低版本 | 兼容版本范围 |
|------|----------|-------------|
| Python | 3.9 | 3.9 - 3.14 |
| FastAPI | 0.100 | 0.100 - 0.136+ |
| AKShare | 1.10 | 1.10 - 1.18+ |
| chinese_calendar | 1.9 | 1.9+ |
| SQLite | 3.30 | 3.30 - 3.51+ |
| Chart.js | 4.0 | 4.0 - 4.4+ |

### B. 东方财富 API 字段映射

| akshare 函数 | 返回字段 | 对应东方财富 API |
|-------------|---------|-----------------|
| `stock_sector_fund_flow_rank` | f2(最新价), f3(涨跌幅), f62(主力净流入), f184(主力净占比) | `push2.eastmoney.com/api/qt/clist/get` |
| `stock_individual_fund_flow_rank` | 同上 | 同上 |
| `stock_individual_fund_flow` | f51(日期), f52(主力净流入), f57(收盘价), f58(涨跌幅) | `push2his.eastmoney.com/api/qt/stock/fflow/daykline/get` |
| `stock_market_fund_flow` | 主力/超大单/大单/中单/小单 净额与占比 | 同上 |
| `stock_hsgt_fund_min_em` | f51(时间), f54(沪股通), f58(深股通), f53(北向) | `push2.eastmoney.com/api/qt/kamtbs.rtmin/get` |

### C. 备用数据源接口

| 数据源 | 接口 | 字段 |
|--------|------|------|
| 新浪财经 | `https://hq.sinajs.cn/list=sh600519` | 0=名称,1=今开,2=昨收,3=当前价,30=日期 |
| 腾讯财经 | `https://qt.gtimg.cn/q=sh600519` | 1=名称,4=当前价,5=昨收,32=涨跌幅 |

### D. 环境变量参考

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| POLL_INTERVAL | 120 | 轮询间隔(秒) |
| DEBUG | false | 调试模式 |
| DB_PATH | `db/fund_flow.db` | 数据库路径（可设为绝对路径） |
| WEB_PORT | 8899 | Web 服务端口 |

---

*文档结束 · v2.0 · 2026-06-17 · 如有问题请查看日志或检查 config.py 配置*
