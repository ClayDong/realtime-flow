/**
 * realtime-flow v2 - 前端核心
 * 用户体验专家：实时更新、直观展示、自选股追踪、历史趋势
 */

// ─── 工具函数 ──────────────────────────────────────
const utils = {
  formatMoney(val) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    const v = Number(val);
    if (Math.abs(v) >= 10000) return (v / 10000).toFixed(2) + '亿';
    if (Math.abs(v) >= 1) return v.toFixed(2) + '亿';
    return (v * 10000).toFixed(0) + '万';
  },

  formatPct(val) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    const v = Number(val);
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  },

  formatPrice(val) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    return Number(val).toFixed(2);
  },

  colorClass(val) {
    if (val === null || val === undefined || isNaN(val)) return 'neutral';
    return Number(val) >= 0 ? 'positive' : 'negative';
  },

  strengthTag(ratio) {
    if (ratio === null || ratio === undefined || isNaN(ratio)) return '<span class="tag tag-neutral">-</span>';
    const r = Number(ratio);
    if (r > 5) return '<span class="tag tag-strong-in">强流入</span>';
    if (r > 2) return '<span class="tag tag-mild-in">温和流入</span>';
    if (r > -2) return '<span class="tag tag-neutral">中性</span>';
    if (r > -5) return '<span class="tag tag-mild-out">温和流出</span>';
    return '<span class="tag tag-strong-out">强流出</span>';
  },

  rankBadge(i) {
    const cls = i <= 3 ? `rank-${i}` : 'rank-other';
    return `<span class="rank-badge ${cls}">${i}</span>`;
  },

  ratioBar(val, maxAbs = 15) {
    const v = Number(val) || 0;
    const pct = Math.min(Math.abs(v) / maxAbs * 100, 100);
    const cls = v >= 0 ? 'bar-inflow' : 'bar-outflow';
    return `<div class="bar-container"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>`;
  },

  getVal(obj, ...keys) {
    for (const k of keys) {
      if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
    }
    return 0;
  },
};

// ─── WebSocket 管理器 ──────────────────────────────
class WSManager {
  constructor(url, onData) {
    this.url = url;
    this.onData = onData;
    this.ws = null;
    this.reconnectTimer = null;
    this.pingTimer = null;
    this.connect();
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    try {
      // 支持 Basic Auth：如果 URL 包含凭据（浏览器原生支持 user:pass@host）
      // WebSocket 不支持自定义 header，这里通过 query token 传递
      let wsUrl = this.url;
      // 如果页面是通过 Basic Auth 访问的，从 cookie 或 localStorage 取 token
      // 简化方案：依赖浏览器同源机制，WS 连接会继承页面的认证状态
      this.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.error('WS连接失败:', e);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log('WS 已连接');
      const dot = document.getElementById('status-dot');
      if (dot) { dot.classList.remove('offline', 'partial'); dot.classList.add('online'); }
      this.pingTimer = setInterval(() => {
        try { this.ws.send('ping'); } catch(e) {}
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'pong') return;
        if (msg.type === 'data_update' && msg.data) this.onData(msg.data);
      } catch (e) { console.error('WS消息错误:', e); }
    };

    this.ws.onclose = () => {
      console.log('WS 断开');
      clearInterval(this.pingTimer);
      const dot = document.getElementById('status-dot');
      if (dot) { dot.classList.remove('online'); dot.classList.add('offline'); }
      this.scheduleReconnect();
    };

    this.ws.onerror = () => { this.ws?.close(); };
  }

  scheduleReconnect() {
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), 5000);
  }

  close() {
    clearInterval(this.pingTimer);
    clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}

// ─── 趋势图表管理器 ───────────────────────────────
class TrendChartManager {
  constructor() {
    this.charts = {};
    this.loaded = false;
    this.loadChartJS();
  }

  loadChartJS() {
    if (window.Chart) { this.loaded = true; return; }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js';
    script.onload = () => {
      this.loaded = true;
      // 注册插件
      Chart.register({
        id: 'gradient',
        beforeDraw: (chart) => {
          const ctx = chart.ctx;
          chart.data.datasets.forEach((ds, i) => {
            if (ds.gradient) {
              const meta = chart.getDatasetMeta(i);
              if (meta.data?.[0]) {
                const top = meta.data[0].y;
                const bottom = meta.data[meta.data.length - 1].y;
                ds.backgroundColor = ctx.createLinearGradient(0, top, 0, bottom);
                ds.backgroundColor.addColorStop(0, ds.gradientFrom || 'rgba(64,196,255,0.3)');
                ds.backgroundColor.addColorStop(1, 'rgba(64,196,255,0.02)');
              }
            }
          });
        }
      });
      this.renderPending();
    };
    document.head.appendChild(script);
  }

  renderPending() {
    // 如果有等待渲染的图表
    if (this._pending) {
      this.renderSectorTrend(this._pending);
      this._pending = null;
    }
  }

  renderSectorTrend(data) {
    if (!this.loaded) { this._pending = data; return; }
    const canvas = document.getElementById('sector-trend-chart');
    if (!canvas) return;
    if (this.charts.sectorTrend) this.charts.sectorTrend.destroy();

    const ctx = canvas.getContext('2d');
    this.charts.sectorTrend = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.map(d => d.name),
        datasets: [{
          label: '主力净流入（亿）',
          data: data.map(d => d.main_inflow),
          backgroundColor: data.map(d => Number(d.main_inflow) >= 0
            ? 'rgba(0,200,83,0.7)' : 'rgba(255,23,68,0.7)'),
          borderColor: data.map(d => Number(d.main_inflow) >= 0
            ? 'rgba(0,200,83,1)' : 'rgba(255,23,68,1)'),
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => utils.formatMoney(ctx.raw),
            }
          }
        },
        scales: {
          y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#556677', callback: (v) => utils.formatMoney(v) }
          },
          x: {
            grid: { display: false },
            ticks: { color: '#556677', maxRotation: 45, font: { size: 11 } }
          }
        }
      }
    });
  }
}

// ─── 主应用 ─────────────────────────────────────────
class App {
  constructor() {
    this.data = null;
    this.updateTimestamp = null;
    this.charts = new TrendChartManager();
    this.init();
  }

  init() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/ws`;

    this.fetchInitialData().then(() => {
      this.ws = new WSManager(wsUrl, (data) => {
        this.data = data;
        this.updateTimestamp = new Date();
        this.renderAll();
      });
    });
  }

  async fetchInitialData() {
    try {
      const resp = await fetch('/api/data');
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.updated_at) {
          this.data = data;
          this.updateTimestamp = new Date();
          this.renderAll();
        }
      }
    } catch (e) { console.error('初始数据加载失败:', e); }
  }

  async fetchWatchlist() {
    try {
      const resp = await fetch('/api/watchlist');
      if (resp.ok) {
        const data = await resp.json();
        this.renderWatchlist(data.data || []);
      }
    } catch (e) { console.error('自选股加载失败:', e); }
  }

  // ══════════════════════════════════════════════════
  // 渲染入口
  // ══════════════════════════════════════════════════
  renderAll() {
    if (!this.data) return;
    this.renderStatusBar();
    this.renderMarketOverview();
    this.renderSectorAnalysis();
    this.renderStockAnalysis();
    this.renderConceptAnalysis();
    this.renderSignals();
    this.renderTimestamp();
    this.renderSectorTrendChart();
    this.fetchWatchlist();  // 异步加载自选股
  }

  renderStatusBar() {
    const el = document.getElementById('status-text');
    if (!el) return;
    if (!this.data?.updated_at) {
      el.textContent = '等待数据...';
      return;
    }
    const updateTime = new Date(this.data.updated_at);
    const now = new Date();
    const ageSec = Math.floor((now - updateTime) / 1000);
    const timeStr = updateTime.toLocaleTimeString('zh-CN', { hour12: false });

    // 数据时效性提示
    let ageText, ageColor;
    if (ageSec < 180) { ageText = `${ageSec}秒前`; ageColor = 'var(--accent-green)'; }
    else if (ageSec < 600) { ageText = `${Math.floor(ageSec/60)}分钟前`; ageColor = 'var(--accent-gold)'; }
    else if (ageSec < 3600) { ageText = `${Math.floor(ageSec/60)}分钟前`; ageColor = 'var(--accent-red)'; }
    else { ageText = '数据过期'; ageColor = 'var(--accent-red)'; }

    el.innerHTML = `更新: ${timeStr} <span style="color:${ageColor};margin-left:6px;">(${ageText})</span>`;
  }

  renderMarketOverview() {
    const container = document.getElementById('market-overview');
    if (!container) return;

    const mkt = this.data.market?.market;
    const north = this.data.market?.north_bound;
    const analysis = this.data.market_analysis;

    if (!mkt) {
      container.innerHTML = `<div class="empty-state"><div class="icon">📊</div><p>非交易时段，暂无数据</p></div>`;
      return;
    }

    container.innerHTML = `
      <div class="grid-4">
        <div class="card">
          <div class="card-header"><span class="card-title">上证指数</span></div>
          <div class="card-value ${utils.colorClass(mkt.sh_change)}">${utils.formatPrice(mkt.sh_close)}</div>
          <div class="card-sub ${utils.colorClass(mkt.sh_change)}">${utils.formatPct(mkt.sh_change)}</div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">深证成指</span></div>
          <div class="card-value ${utils.colorClass(mkt.sz_change)}">${utils.formatPrice(mkt.sz_close)}</div>
          <div class="card-sub ${utils.colorClass(mkt.sz_change)}">${utils.formatPct(mkt.sz_change)}</div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">主力净流入</span></div>
          <div class="card-value ${utils.colorClass(mkt.main_net_inflow)}">${utils.formatMoney(mkt.main_net_inflow)}</div>
          <div class="card-sub ${utils.colorClass(mkt.main_net_ratio)}">净占比 ${utils.formatPct(mkt.main_net_ratio)}</div>
        </div>
        <div class="card">
          <div class="card-header"><span class="card-title">北向资金</span></div>
          <div class="card-value ${north && utils.colorClass(north.total)}">${north ? utils.formatMoney(north.total) : '-'}</div>
          <div class="card-sub">${north ? (north.total >= 0 ? '净流入' : '净流出') : '暂无'}</div>
        </div>
      </div>
      <div class="grid-3" style="margin-top:12px;">
        <div class="card">
          <div class="card-title">超大单净流入</div>
          <div class="card-value ${utils.colorClass(mkt.super_large_inflow)}" style="font-size:18px;">${utils.formatMoney(mkt.super_large_inflow)}</div>
          <div class="card-sub">机构资金动向</div>
        </div>
        <div class="card">
          <div class="card-title">小单净流入（散户）</div>
          <div class="card-value ${utils.colorClass(mkt.small_inflow)}" style="font-size:18px;">${utils.formatMoney(mkt.small_inflow)}</div>
          <div class="card-sub">散户资金动向</div>
        </div>
        <div class="card">
          <div class="card-title">市场博弈</div>
          <div class="card-value" style="font-size:16px;font-weight:500;color:var(--text-primary);">${analysis?.main_vs_retail || '等待数据...'}</div>
        </div>
      </div>
    `;
  }

  renderSectorAnalysis() {
    const container = document.getElementById('sector-analysis');
    if (!container) return;
    const analysis = this.data.sector_analysis;
    if (!analysis || !analysis.inflow_top?.length) {
      container.innerHTML = `<div class="empty-state"><div class="icon">🏭</div><p>行业数据加载中...</p></div>`;
      return;
    }

    const rotScore = analysis.rotation_score || 0;
    const rotDesc = rotScore > 3 ? '资金高度集中，行业轮动明显' :
                    rotScore > 1.5 ? '行业轮动温和' : '资金分散，无明显轮动';

    let html = `
      <div class="card" style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;">
          <span class="card-title">🏭 行业轮动强度</span>
          <span style="font-weight:700;font-size:18px;color:var(--accent-gold);">${rotScore}</span>
        </div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">${rotDesc}</div>
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-title" style="color:var(--accent-green);margin-bottom:12px;">⬆ 资金流入 TOP ${analysis.inflow_top.length}</div>
          <div class="table-wrapper">
            <table>
              <thead><tr><th>#</th><th>行业</th><th>主力净流入</th><th>净占比</th><th>涨跌幅</th><th>强度</th></tr></thead>
              <tbody>
                ${analysis.inflow_top.map((s, i) => `
                  <tr>
                    <td>${utils.rankBadge(i + 1)}</td>
                    <td><strong>${s.name}</strong></td>
                    <td class="${utils.colorClass(s.main_inflow)}">${utils.formatMoney(s.main_inflow)}</td>
                    <td class="${utils.colorClass(s.main_ratio)}">${utils.formatPct(s.main_ratio)}</td>
                    <td class="${utils.colorClass(s.price_change)}">${utils.formatPct(s.price_change)}</td>
                    <td>${utils.strengthTag(s.main_ratio)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <div class="card-title" style="color:var(--accent-red);margin-bottom:12px;">⬇ 资金流出 TOP ${analysis.outflow_top.length}</div>
          <div class="table-wrapper">
            <table>
              <thead><tr><th>#</th><th>行业</th><th>主力净流入</th><th>净占比</th><th>涨跌幅</th><th>强度</th></tr></thead>
              <tbody>
                ${analysis.outflow_top.map((s, i) => `
                  <tr>
                    <td>${utils.rankBadge(i + 1)}</td>
                    <td><strong>${s.name}</strong></td>
                    <td class="${utils.colorClass(s.main_inflow)}">${utils.formatMoney(s.main_inflow)}</td>
                    <td class="${utils.colorClass(s.main_ratio)}">${utils.formatPct(s.main_ratio)}</td>
                    <td class="${utils.colorClass(s.price_change)}">${utils.formatPct(s.price_change)}</td>
                    <td>${utils.strengthTag(s.main_ratio)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    if (analysis.institutional_focus?.length) {
      html += `
        <div class="card" style="margin-top:12px;">
          <div class="card-title purple" style="margin-bottom:12px;">🏦 机构关注（超大单集中）</div>
          <div class="table-wrapper">
            <table><thead><tr><th>#</th><th>行业</th><th>超大单净流入</th><th>主力净流入</th></tr></thead>
              <tbody>
                ${analysis.institutional_focus.slice(0, 8).map((s, i) => `
                  <tr>
                    <td>${utils.rankBadge(i + 1)}</td>
                    <td><strong>${s.name}</strong></td>
                    <td class="${utils.colorClass(s.super_large_inflow)}">${utils.formatMoney(s.super_large_inflow)}</td>
                    <td class="${utils.colorClass(s.main_inflow)}">${utils.formatMoney(s.main_inflow)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>`;
    }

    if (analysis.divergence?.length) {
      html += `
        <div class="card" style="margin-top:12px;border-color:rgba(255,215,0,0.3);">
          <div class="card-title gold" style="margin-bottom:12px;">⚠️ 背离预警</div>
          ${analysis.divergence.map(d => `
            <div class="signal-item">
              <div class="signal-icon signal-warning">⚠</div>
              <div class="signal-text">
                <div class="name">${d.name}</div>
                <div class="desc">${d.type}</div>
                <div style="font-size:12px;margin-top:2px;">
                  主力净流入: <span class="${utils.colorClass(d.main_inflow)}">${utils.formatMoney(d.main_inflow)}</span>
                  ，涨跌幅: <span class="${utils.colorClass(d.price_change)}">${utils.formatPct(d.price_change)}</span>
                </div>
              </div>
            </div>
          `).join('')}
        </div>`;
    }

    container.innerHTML = html;
  }

  renderSectorTrendChart() {
    const analysis = this.data.sector_analysis;
    if (!analysis?.inflow_top?.length) return;
    const chartData = analysis.inflow_top.slice(0, 12);
    this.charts.renderSectorTrend(chartData);
  }

  renderStockAnalysis() {
    const container = document.getElementById('stock-analysis');
    if (!container) return;
    const analysis = this.data.stock_analysis;
    if (!analysis || !analysis.ranked_stocks?.length) {
      container.innerHTML = `<div class="empty-state"><div class="icon">📈</div><p>个股数据加载中...</p></div>`;
      return;
    }

    const stocks = analysis.ranked_stocks;

    let html = `
      <div class="card" style="margin-bottom:12px;">
        <div class="card-title" style="margin-bottom:12px;">📈 个股综合评分 TOP ${stocks.length}</div>
        <div class="table-wrapper">
          <table>
            <thead><tr>
              <th>#</th><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th>
              <th>主力净流入</th><th>主力占比</th><th>综合评分</th><th>强度</th>
            </tr></thead>
            <tbody>
              ${stocks.map((s, i) => `
                <tr>
                  <td>${utils.rankBadge(i + 1)}</td>
                  <td style="color:var(--text-muted);">${s.code}</td>
                  <td><strong>${s.name}</strong></td>
                  <td>${utils.formatPrice(s.price)}</td>
                  <td class="${utils.colorClass(s.price_change)}">${utils.formatPct(s.price_change)}</td>
                  <td class="${utils.colorClass(s.main_inflow)}">${utils.formatMoney(s.main_inflow)}</td>
                  <td class="${utils.colorClass(s.main_ratio)}">${utils.formatPct(s.main_ratio)}${utils.ratioBar(s.main_ratio)}</td>
                  <td style="font-weight:700;color:var(--accent-blue);">${s.score}</td>
                  <td>${utils.strengthTag(s.main_ratio)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    if (analysis.strong_inflow?.length) {
      html += `
        <div class="card" style="margin-top:12px;border-color:rgba(0,200,83,0.2);">
          <div class="card-title" style="color:var(--accent-green);margin-bottom:12px;">🔥 强资金流入个股</div>
          <div class="table-wrapper"><table><thead><tr><th>#</th><th>名称</th><th>主力占比</th><th>主力净流入</th><th>涨跌幅</th></tr></thead>
            <tbody>${analysis.strong_inflow.slice(0, 10).map((s, i) => `
              <tr>
                <td>${utils.rankBadge(i + 1)}</td>
                <td><strong>${s.name}</strong></td>
                <td class="positive">${utils.formatPct(s.main_ratio)}</td>
                <td class="positive">${utils.formatMoney(s.main_inflow)}</td>
                <td class="${utils.colorClass(s.price_change)}">${utils.formatPct(s.price_change)}</td>
              </tr>`).join('')}
            </tbody></table>
          </div>
        </div>`;
    }

    container.innerHTML = html;
  }

  renderConceptAnalysis() {
    const container = document.getElementById('concept-analysis');
    if (!container) return;
    const analysis = this.data.concept_analysis;
    if (!analysis?.hot_concepts?.length) {
      if (container) container.innerHTML = `<div class="empty-state"><div class="icon">🏷️</div><p>概念数据加载中...</p></div>`;
      return;
    }

    container.innerHTML = `
      <div class="card">
        <div class="card-title gold" style="margin-bottom:12px;">🏷️ 热门概念 TOP ${analysis.hot_concepts.length}</div>
        <div class="table-wrapper"><table>
          <thead><tr><th>#</th><th>概念</th><th>主力净流入</th><th>净占比</th><th>涨跌幅</th></tr></thead>
          <tbody>${analysis.hot_concepts.map((c, i) => `
            <tr>
              <td>${utils.rankBadge(i + 1)}</td>
              <td><strong>${c.name}</strong></td>
              <td class="${utils.colorClass(c.main_inflow)}">${utils.formatMoney(c.main_inflow)}</td>
              <td class="${utils.colorClass(c.main_ratio)}">${utils.formatPct(c.main_ratio)}</td>
              <td class="${utils.colorClass(c.price_change)}">${utils.formatPct(c.price_change)}</td>
            </tr>`).join('')}
          </tbody></table>
        </div>
      </div>`;
  }

  renderSignals() {
    const container = document.getElementById('signals-panel');
    if (!container) return;
    const analysis = this.data.sector_analysis;
    if (!analysis) { container.innerHTML = `<div class="empty-state"><div class="icon">🔔</div><p>暂无信号</p></div>`; return; }

    const items = [];

    if (analysis.divergence?.length) {
      analysis.divergence.forEach(d => {
        items.push({ icon: '⚠', iconClass: 'signal-warning', name: `${d.name}`, desc: d.type, value: `主力${utils.formatMoney(d.main_inflow)}`, valClass: utils.colorClass(d.main_inflow) });
      });
    }

    if (analysis.rotation_score > 3) {
      items.push({ icon: '🔄', iconClass: 'signal-info', name: `行业轮动强度 ${analysis.rotation_score}`, desc: '资金高度集中，注意轮动节奏', value: '', valClass: '' });
    }

    const mkt = this.data.market_analysis;
    if (mkt?.signals?.length) {
      mkt.signals.forEach(s => {
        items.push({ icon: '🌐', iconClass: 'signal-info', name: '市场信号', desc: s, value: '', valClass: '' });
      });
    }

    if (!items.length) { container.innerHTML = `<div class="empty-state"><div class="icon">🔔</div><p>暂无异常信号</p></div>`; return; }

    container.innerHTML = items.map(item => `
      <div class="signal-item">
        <div class="signal-icon ${item.iconClass}">${item.icon}</div>
        <div class="signal-text">
          <div class="name">${item.name}</div>
          <div class="desc">${item.desc}</div>
          ${item.value ? `<div class="value ${item.valClass}">${item.value}</div>` : ''}
        </div>
      </div>`).join('');
  }

  renderWatchlist(stocks) {
    const container = document.getElementById('watchlist-panel');
    if (!container) return;
    if (!stocks?.length) {
      container.innerHTML = `
        <div class="card-title gold" style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
          <span>⭐ 自选股资金流</span>
          <button onclick="window.app.showAddWatchlistDialog()" style="background:var(--accent-blue);color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;">+ 添加</button>
        </div>
        <div class="empty-state"><div class="icon">⭐</div><p>暂无自选股，点击添加</p></div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="card-title gold" style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
        <span>⭐ 自选股资金流</span>
        <button onclick="window.app.showAddWatchlistDialog()" style="background:var(--accent-blue);color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;">+ 添加</button>
      </div>
      <div class="table-wrapper"><table>
        <thead><tr>
          <th>名称</th><th>日期</th><th>收盘价</th><th>涨跌幅</th>
          <th>主力净流入</th><th>主力占比</th><th>强度</th><th></th>
        </tr></thead>
        <tbody>${stocks.map(s => {
          const inflow = s['主力净流入-净额'] || 0;
          const ratio = s['主力净流入-净占比'] || 0;
          const pct = s['涨跌幅'] || 0;
          const close = s['收盘价'] || 0;
          const sourceTag = s.source && s.source !== 'eastmoney'
            ? `<span style="font-size:9px;color:var(--text-muted);margin-left:4px;">[${s.source}]</span>` : '';
          return `<tr>
            <td><strong>${s.display_name || s.code}</strong>${sourceTag}</td>
            <td style="color:var(--text-muted);font-size:11px;">${s['日期'] || '-'}</td>
            <td>${utils.formatPrice(close)}</td>
            <td class="${utils.colorClass(pct)}">${utils.formatPct(pct)}</td>
            <td class="${utils.colorClass(inflow)}">${utils.formatMoney(inflow)}</td>
            <td class="${utils.colorClass(ratio)}">${utils.formatPct(ratio)}${utils.ratioBar(ratio)}</td>
            <td>${utils.strengthTag(ratio)}</td>
            <td><button onclick="window.app.removeWatchlist('${s.code}')" style="background:rgba(255,23,68,0.2);color:var(--accent-red);border:none;padding:2px 6px;border-radius:3px;cursor:pointer;font-size:11px;">删除</button></td>
          </tr>`;
        }).join('')}
        </tbody>
      </table></div>`;
  }

  // 自选股管理：添加
  async showAddWatchlistDialog() {
    const code = prompt('输入股票代码（6位数字）:');
    if (!code) return;
    const market = prompt('输入市场（sh=上交所, sz=深交所, bj=北交所）:', 'sh');
    if (!market) return;
    const name = prompt('输入显示名称（可留空）:', '') || '';
    try {
      const resp = await fetch('/api/watchlist/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code, market, name}),
      });
      const result = await resp.json();
      if (result.success) {
        alert(result.msg);
        this._watchlist_cache = null;  // 清缓存（通过 engine）
        this.fetchWatchlist();
      } else {
        alert('添加失败: ' + result.msg);
      }
    } catch (e) {
      alert('请求失败: ' + e.message);
    }
  }

  // 自选股管理：删除
  async removeWatchlist(code) {
    if (!confirm(`确认删除 ${code}？`)) return;
    try {
      const resp = await fetch('/api/watchlist/remove', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code}),
      });
      const result = await resp.json();
      if (result.success) {
        alert(result.msg);
        this.fetchWatchlist();
      } else {
        alert('删除失败');
      }
    } catch (e) {
      alert('请求失败: ' + e.message);
    }
  }

  renderTimestamp() {
    const el = document.getElementById('update-time');
    if (el) el.textContent = this.updateTimestamp
      ? this.updateTimestamp.toLocaleTimeString('zh-CN', { hour12: false }) : '-';
  }
}

document.addEventListener('DOMContentLoaded', () => { window.app = new App(); });
