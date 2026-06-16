"""
FastAPI 主程序 - Web + WebSocket 服务
架构专家：模块化路由
用户体验专家：清晰的页面布局
运维专家：健康检查、可观测性
"""
import json
import logging
import asyncio
import time
import os
import secrets
import hashlib
import base64
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from config import CONFIG
from engine import engine
from db.models import db

# ─── 日志配置（运维专家） ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-18s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# ─── 静态文件 & 模板 ────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# ─── 访问认证配置（Cookie 认证方案） ──────────────────
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASS)

# Cookie 名称和有效期
AUTH_COOKIE_NAME = "rtf_session"
AUTH_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 天

# 已登录的 session token 集合（内存存储，重启后需重新登录）
# 生产环境可用 Redis 替代，单用户场景内存足够
_valid_sessions: set[str] = set()


def _generate_session_token() -> str:
    """生成随机 session token"""
    return secrets.token_urlsafe(32)


def _create_session() -> str:
    """创建新 session，返回 token"""
    token = _generate_session_token()
    _valid_sessions.add(token)
    return token


def _is_valid_session(token: Optional[str]) -> bool:
    """检查 session token 是否有效"""
    return token is not None and token in _valid_sessions


def _destroy_session(token: Optional[str]):
    """销毁 session"""
    if token:
        _valid_sessions.discard(token)


# 豁免认证的路径
PUBLIC_PATHS = {
    "/health",
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/static/css/style.css",  # 登录页需要样式
}

# 豁免认证的路径前缀
PUBLIC_PREFIXES = (
    "/static/",
)


class CookieAuthMiddleware(BaseHTTPMiddleware):
    """
    Cookie 认证中间件
    - 本地访问（127.0.0.1）豁免
    - /health、/login 等公开路径豁免
    - 未认证的页面请求重定向到 /login
    - 未认证的 API 请求返回 401 JSON
    """

    LOCAL_HOSTS = {"127.0.0.1", "::1"}

    async def dispatch(self, request: Request, call_next):
        if not AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path

        # 公开路径豁免
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # 本地访问豁免
        client_host = request.client.host if request.client else ""
        if client_host in self.LOCAL_HOSTS:
            return await call_next(request)

        # 检查 Cookie
        session_token = request.cookies.get(AUTH_COOKIE_NAME)
        if _is_valid_session(session_token):
            return await call_next(request)

        # 也兼容 Basic Auth（API 客户端用）
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, password = decoded.split(":", 1)
                if (secrets.compare_digest(username, AUTH_USER) and
                        secrets.compare_digest(password, AUTH_PASS)):
                    return await call_next(request)
            except Exception:
                pass

        # 未认证：页面请求重定向到登录页，API 请求返回 401
        if self._is_api_request(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权访问，请先登录"},
            )
        else:
            # 重定向到登录页，带上原始 URL
            login_url = f"/login?redirect={path}"
            return RedirectResponse(url=login_url, status_code=302)

    @staticmethod
    def _is_api_request(request: Request) -> bool:
        """判断是否是 API 请求"""
        path = request.url.path
        return path.startswith("/api/") or path == "/ws"


# ─── WebSocket 连接管理 ──────────────────────────────
connected_clients: set[WebSocket] = set()


async def broadcast(data: Dict[str, Any]):
    """广播到所有连接的客户端"""
    message = json.dumps(data, ensure_ascii=False, default=str)
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    connected_clients -= dead


# ─── 异步轮询任务 ──────────────────────────────────
async def poll_loop():
    """后台定时采集任务"""
    logger.info("⏱ 采集循环启动")
    # 先采集一次预热
    await asyncio.sleep(5)
    try:
        engine.poll_once()
    except Exception as e:
        logger.error(f"预热采集异常: {e}")

    while True:
        try:
            if not engine.is_market_hours():
                # 非交易时段，每小时检查一次
                await asyncio.sleep(3600)
                continue

            result = engine.poll_once()

            # 广播最新结果
            await broadcast({
                "type": "data_update",
                "data": engine.get_cache(),
                "timestamp": datetime.now().isoformat(),
            })

            # 等待下次轮询
            await asyncio.sleep(CONFIG.data.POLL_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"轮询循环异常: {e}")
            await asyncio.sleep(30)

    logger.info("⏱ 采集循环停止")


# ─── 生命周期管理（架构/运维专家） ────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info("🚀 realtime-flow 启动")
    logger.info(f"   端口: {CONFIG.web.PORT}")
    logger.info(f"   轮询间隔: {CONFIG.data.POLL_INTERVAL_SECONDS}s")
    logger.info(f"   数据库: {CONFIG.storage.DB_PATH}")

    # 初始化自选股表（如果为空则用 config.py 默认值填充）
    db.init_watchlist_if_empty(CONFIG.portfolio.WATCHLIST)

    # 启动后台轮询
    task = asyncio.create_task(poll_loop())
    # 定期清理（每天凌晨）
    cleanup_task = asyncio.create_task(cleanup_loop())

    yield

    # 关闭
    task.cancel()
    cleanup_task.cancel()
    logger.info("🛑 realtime-flow 关闭")


async def cleanup_loop():
    """定期清理旧数据（运维专家）"""
    while True:
        await asyncio.sleep(86400)  # 每天
        try:
            db.cleanup_old_data()
        except Exception as e:
            logger.error(f"清理异常: {e}")


# ─── FastAPI 应用 ──────────────────────────────────
app = FastAPI(title="realtime-flow", version="2.0.0", lifespan=lifespan)

# 注册 Cookie 认证中间件（通过环境变量 AUTH_USER/AUTH_PASS 启用）
app.add_middleware(CookieAuthMiddleware)

if AUTH_ENABLED:
    logger.info(f"🔐 访问认证已启用（用户: {AUTH_USER}），本地访问豁免")
else:
    logger.info("🔓 访问认证未启用（本地开发模式）")

# 静态文件
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ─── 中间件：请求计时（运维专家） ───────────────────
class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        response.headers["X-Process-Time"] = f"{elapsed:.4f}"
        return response


app.add_middleware(TimingMiddleware)


# ══════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════

# ─── 认证路由 ───────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    # 如果已登录，直接跳转首页
    if AUTH_ENABLED:
        session_token = request.cookies.get(AUTH_COOKIE_NAME)
        if _is_valid_session(session_token):
            return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/api/auth/login")
async def login(request: Request):
    """登录 API - 验证用户名密码，设置 Cookie"""
    if not AUTH_ENABLED:
        return {"success": True, "msg": "认证未启用"}

    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    if (secrets.compare_digest(username, AUTH_USER) and
            secrets.compare_digest(password, AUTH_PASS)):
        token = _create_session()
        response = JSONResponse({"success": True, "msg": "登录成功"})
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=token,
            max_age=AUTH_COOKIE_MAX_AGE,
            httponly=True,
            secure=True,       # HTTPS only（Cloudflare 提供 HTTPS）
            samesite="lax",
            path="/",
        )
        logger.info(f"用户登录成功: {username}")
        return response
    else:
        logger.warning(f"登录失败: username={username}")
        return JSONResponse(
            status_code=401,
            content={"success": False, "detail": "用户名或密码错误"},
        )


@app.post("/api/auth/logout")
async def logout(request: Request):
    """登出 API - 清除 Cookie 和 session"""
    session_token = request.cookies.get(AUTH_COOKIE_NAME)
    _destroy_session(session_token)
    response = JSONResponse({"success": True, "msg": "已登出"})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return response


# ─── 页面路由 ───────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """主页 - 综合看板"""
    return templates.TemplateResponse(
        request, "index.html",
        {"page_refresh": CONFIG.web.PAGE_REFRESH_INTERVAL, "ws_push_interval": CONFIG.web.WS_PUSH_INTERVAL},
    )


@app.get("/sectors", response_class=HTMLResponse)
async def sectors_page(request: Request):
    """行业资金流页面"""
    return templates.TemplateResponse(
        request, "sectors.html",
        {"page_refresh": CONFIG.web.PAGE_REFRESH_INTERVAL},
    )


@app.get("/stocks", response_class=HTMLResponse)
async def stocks_page(request: Request):
    """个股资金流页面"""
    return templates.TemplateResponse(
        request, "stocks.html",
        {"page_refresh": CONFIG.web.PAGE_REFRESH_INTERVAL},
    )


# ══════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════

@app.get("/api/data")
async def get_data():
    """获取最新缓存数据"""
    return engine.get_cache()


@app.get("/api/history/sectors")
async def get_sector_history(sector_name: str = "汽车服务"):
    """获取某行业的历史资金流"""
    from collectors.sector_collector import SectorCollector
    sc = SectorCollector()
    return {"data": sc.fetch_sector_history(sector_name)}


@app.get("/api/history/stock")
async def get_stock_history(code: str = "600519", market: str = "sh"):
    """获取某只个股的历史资金流"""
    from collectors.stock_collector import StockCollector
    sc = StockCollector()
    return {"data": sc.fetch_stock_detail(code, market)}


@app.get("/api/stats")
async def get_stats():
    """系统运行状态"""
    return engine.get_stats()


@app.get("/api/db/recent")
async def get_db_recent():
    """最近快照数据"""
    return {
        "sectors": db.get_latest_sector_snapshot("今日"),
        "stocks": db.get_latest_stock_snapshot("今日", 50),
        "signals": db.get_recent_signals(20),
        "market": db.get_market_flow_recent(5),
    }




@app.get("/api/watchlist")
async def get_watchlist():
    """自选股资金流（用 to_thread 避免阻塞事件循环）"""
    data = await asyncio.to_thread(engine.fetch_watchlist_flow)
    return {"data": data, "count": len(data)}


@app.get("/api/watchlist/config")
async def get_watchlist_config():
    """获取自选股配置列表"""
    return {"data": engine.get_watchlist_config()}


@app.post("/api/watchlist/add")
async def add_watchlist_stock(request: Request):
    """添加自选股"""
    body = await request.json()
    code = str(body.get("code", "")).strip()
    market = str(body.get("market", "sh")).strip()
    name = str(body.get("name", "")).strip()
    result = engine.add_watchlist_stock(code, market, name)
    return result


@app.post("/api/watchlist/remove")
async def remove_watchlist_stock(request: Request):
    """删除自选股"""
    body = await request.json()
    code = str(body.get("code", "")).strip()
    result = engine.remove_watchlist_stock(code)
    return result


@app.get("/api/portfolio")
async def get_portfolio():
    """持仓概览"""
    return engine.get_portfolio_summary()


@app.get("/api/backtest/signals")
async def backtest_signals(days: int = 30, forward_days: int = 5):
    """信号回测验证（用 to_thread 避免阻塞）"""
    from analyzers.backtest import backtester
    result = await asyncio.to_thread(
        backtester.backtest_signals, days, forward_days
    )
    return result
@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "total_polls": engine.stats["total_polls"],
        "latest_update": engine.latest_data.get("updated_at"),
        "trade_time": engine.is_trade_time(),
        "market_hours": engine.is_market_hours(),
    }


# ══════════════════════════════════════════════════════
# WebSocket
# ══════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """实时推送 WebSocket（支持 Cookie 认证 + Basic Auth 兼容）"""
    # 认证检查（如果启用了认证）
    if AUTH_ENABLED:
        client_host = ws.client.host if ws.client else ""
        if client_host not in CookieAuthMiddleware.LOCAL_HOSTS:
            authenticated = False

            # 方式1：检查 Cookie（浏览器 WebSocket 会自动带 Cookie）
            session_token = ws.cookies.get(AUTH_COOKIE_NAME)
            if _is_valid_session(session_token):
                authenticated = True

            # 方式2：检查 Basic Auth header（API 客户端用）
            if not authenticated:
                auth_header = ws.headers.get("authorization", "")
                if auth_header.startswith("basic "):
                    try:
                        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                        username, password = decoded.split(":", 1)
                        if (secrets.compare_digest(username, AUTH_USER) and
                                secrets.compare_digest(password, AUTH_PASS)):
                            authenticated = True
                    except Exception:
                        pass

            if not authenticated:
                await ws.close(code=4401, reason="认证失败，请先登录")
                return

    await ws.accept()
    connected_clients.add(ws)
    logger.info(f"WebSocket 客户端连接 (当前: {len(connected_clients)})")

    try:
        # 立即推送一次当前数据
        cache = engine.get_cache()
        if cache.get("updated_at"):
            await ws.send_text(json.dumps({
                "type": "data_update",
                "data": cache,
                "timestamp": datetime.now().isoformat(),
            }, ensure_ascii=False, default=str))

        # 持续接收心跳
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket 异常: {e}")
    finally:
        connected_clients.discard(ws)
        logger.info(f"WebSocket 客户端断开 (当前: {len(connected_clients)})")


# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=CONFIG.web.HOST,
        port=CONFIG.web.PORT,
        reload=CONFIG.web.DEBUG,
        log_level="info",
    )
