/**
 * 模拟盘页面模块
 * 展示：收益指标卡 / 净值曲线（对比基准指数）/ 当前持仓 / 待执行订单 / 成交明细
 * 数据来自后端 /api/sim/*（trading/sim_account.py 的独立账户库）
 */

let simNavChart = null;

/** 百分比着色：A股习惯红涨绿跌 */
function pctText(v, digits = 2) {
    if (v === null || v === undefined) return '<span style="color:#9ca3af;">-</span>';
    const pct = (v * 100).toFixed(digits);
    const color = v > 0 ? '#dc2626' : (v < 0 ? '#16a34a' : '#6b7280');
    const sign = v > 0 ? '+' : '';
    return `<span style="color:${color}; font-weight:600;">${sign}${pct}%</span>`;
}

function moneyText(v) {
    if (v === null || v === undefined) return '-';
    return '¥' + Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** 页面入口（navigation.js 切换到此页时调用） */
export async function initSimAccountPage() {
    await Promise.all([loadSimOverview(), loadSimNav(), loadSimTrades()]);
}

async function fetchJson(url) {
    const resp = await fetch(url);
    const json = await resp.json();
    if (!json.success) throw new Error(json.message || json.error || '请求失败');
    return json.data;
}

// ==================== 总览（指标卡 + 持仓 + 待执行订单） ====================

async function loadSimOverview() {
    try {
        const data = await fetchJson('/api/sim/overview');
        renderMetricsCards(data.metrics, data.cash);
        renderPositions(data.positions, data.cash);
        renderPendingOrders(data.pending_orders);
    } catch (err) {
        console.error('加载模拟盘总览失败:', err);
        document.getElementById('sim-metrics-cards').innerHTML =
            `<div style="color:#dc2626; font-size:13px;">加载失败: ${esc(err.message)}</div>`;
    }
}

function renderMetricsCards(m, cash) {
    const container = document.getElementById('sim-metrics-cards');
    const empty = document.getElementById('sim-empty-state');

    if (!m || !m.trading_days) {
        empty.style.display = 'block';
        container.innerHTML = '';
        return;
    }
    empty.style.display = 'none';

    const cards = [
        { label: '总资产', value: moneyText(m.total_assets), sub: `初始 ${moneyText(m.initial_capital)}` },
        { label: '累计收益率', value: pctText(m.total_return), sub: `${m.start_date} ~ ${m.end_date}`, html: true },
        { label: '年化收益率', value: pctText(m.annual_return), sub: `${m.trading_days} 个交易日`, html: true },
        { label: '最大回撤', value: pctText(m.max_drawdown), sub: '净值高点回撤', html: true },
        { label: '夏普比率', value: m.sharpe !== undefined ? m.sharpe : '-', sub: '日频年化, rf=3%' },
        { label: '胜率', value: pctText(m.win_rate, 1), sub: `${m.sell_count} 笔已平仓`, html: true },
        { label: '盈亏比', value: m.profit_factor ?? '-', sub: `买入 ${m.buy_count} / 卖出 ${m.sell_count}` },
        { label: '可用现金', value: moneyText(cash), sub: '' },
    ];

    container.innerHTML = cards.map(c => `
        <div class="card" style="margin:0;">
            <div class="card-body" style="padding:14px 16px;">
                <div style="font-size:12px; color:#6b7280; margin-bottom:6px;">${c.label}</div>
                <div style="font-size:20px; font-weight:700; color:#111827;">${c.html ? c.value : esc(c.value)}</div>
                <div style="font-size:11px; color:#9ca3af; margin-top:4px;">${esc(c.sub)}</div>
            </div>
        </div>
    `).join('');
}

function renderPositions(positions, cash) {
    const section = document.getElementById('sim-position-section');
    const tbody = document.getElementById('sim-positions-body');
    section.style.display = 'grid';
    document.getElementById('sim-cash-label').textContent = `可用现金 ${moneyText(cash)}`;

    if (!positions || !positions.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#9ca3af;">暂无持仓</td></tr>';
        return;
    }
    tbody.innerHTML = positions.map(p => `
        <tr>
            <td>${esc(p.code)}</td>
            <td>${esc(p.name)}</td>
            <td>${p.quantity}</td>
            <td>${Number(p.buy_price).toFixed(2)}</td>
            <td>${Number(p.current_price).toFixed(2)}</td>
            <td>${pctText(p.return_rate)}</td>
            <td>${esc(p.buy_date)}</td>
        </tr>
    `).join('');
}

function renderPendingOrders(orders) {
    const tbody = document.getElementById('sim-pending-body');
    if (!orders || !orders.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#9ca3af;">暂无待执行订单</td></tr>';
        return;
    }
    tbody.innerHTML = orders.map(o => `
        <tr>
            <td>${esc(o.code)}</td>
            <td>${esc(o.name)}</td>
            <td>${o.side === 'buy'
                ? '<span style="color:#dc2626; font-weight:600;">买入</span>'
                : '<span style="color:#16a34a; font-weight:600;">卖出</span>'}</td>
            <td style="font-size:12px;">${esc(o.reason)}</td>
            <td style="font-size:12px;">${esc(o.strategy)}</td>
        </tr>
    `).join('');
}

// ==================== 净值曲线 ====================

async function loadSimNav() {
    try {
        const data = await fetchJson('/api/sim/nav');
        if (!data.nav || !data.nav.length) return;
        document.getElementById('sim-nav-card').style.display = 'block';
        renderNavChart(data.nav, data.benchmark);
    } catch (err) {
        console.error('加载净值曲线失败:', err);
    }
}

function renderNavChart(nav, benchmark) {
    const ctx = document.getElementById('sim-nav-chart');
    if (!ctx) return;
    if (simNavChart) {
        simNavChart.destroy();
        simNavChart = null;
    }

    const labels = nav.map(n => n.nav_date);
    const simReturns = nav.map(n => +(n.cum_return * 100).toFixed(2));

    const datasets = [{
        label: '模拟盘累计收益率 (%)',
        data: simReturns,
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59, 130, 246, 0.08)',
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointRadius: 2
    }];

    if (benchmark && benchmark.series) {
        datasets.push({
            label: `${benchmark.name}同期 (%)`,
            data: benchmark.series.map(v => v === null ? null : +(v * 100).toFixed(2)),
            borderColor: '#9ca3af',
            borderWidth: 1.5,
            borderDash: [6, 4],
            fill: false,
            tension: 0.3,
            pointRadius: 0,
            spanGaps: true
        });
    }

    simNavChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top' },
                tooltip: {
                    callbacks: {
                        label: item => `${item.dataset.label}: ${item.parsed.y === null ? '-' : (item.parsed.y > 0 ? '+' : '') + item.parsed.y + '%'}`
                    }
                }
            },
            scales: {
                y: { title: { display: true, text: '累计收益率 (%)' } },
                x: { ticks: { maxTicksLimit: 12 } }
            }
        }
    });
}

// ==================== 成交明细 ====================

async function loadSimTrades() {
    try {
        const trades = await fetchJson('/api/sim/trades?limit=100');
        if (!trades || !trades.length) return;
        document.getElementById('sim-trades-card').style.display = 'block';
        const tbody = document.getElementById('sim-trades-body');
        tbody.innerHTML = trades.map(t => `
            <tr>
                <td>${esc(t.trade_date)}</td>
                <td>${t.side === 'buy'
                    ? '<span style="color:#dc2626; font-weight:600;">买入</span>'
                    : '<span style="color:#16a34a; font-weight:600;">卖出</span>'}</td>
                <td>${esc(t.code)}</td>
                <td>${esc(t.name)}</td>
                <td>${Number(t.price).toFixed(2)}</td>
                <td>${t.quantity}</td>
                <td>${moneyText(t.amount)}</td>
                <td>${moneyText(t.fee)}</td>
                <td>${t.profit === null || t.profit === undefined
                    ? '<span style="color:#9ca3af;">-</span>'
                    : `<span style="color:${t.profit >= 0 ? '#dc2626' : '#16a34a'}; font-weight:600;">${t.profit >= 0 ? '+' : ''}${Number(t.profit).toFixed(2)}</span>`}</td>
                <td style="font-size:12px;">${esc(t.reason)}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('加载成交明细失败:', err);
    }
}
