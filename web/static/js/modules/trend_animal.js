/**
 * 趋势动物模块
 * 数据来源：趋势动物 API（apiKey 仅在服务端，前端不接触）
 * 输出区分：接口直接返回的事实 / 基于趋势动物规则的分析判断
 */

let taState = {
    statusLoaded: false,
    fieldPrices: {},
    defaultFields: [],
    searchResults: [],
};

// ==================== 页面初始化 ====================
export async function initTrendAnimal() {
    const container = document.getElementById('trend-animal-page');
    if (!container) return;
    if (container.dataset.initialized === '1') {
        return;
    }

    // 先检查 API Key 配置状态
    try {
        const resp = await fetch('/api/trend/config');
        const result = await resp.json();
        const configured = result.success && result.data && result.data.configured;
        if (!configured) {
            renderApiConfigPrompt(container, '');
            return;
        }
        container.dataset.initialized = '1';
        container.dataset.maskedKey = result.data.masked_key || '';
        renderTrendAnimalLayout(container);
        loadTrendStatus();
        loadDailyReport(false);
        loadSelectionDates();
    } catch (e) {
        container.innerHTML = `<p class="text-danger">趋势动物配置检查失败: ${e.message}</p>`;
    }
}

/**
 * 渲染 API Key 配置引导页（未配置时显示）
 */
function renderApiConfigPrompt(container, maskedKey) {
    container.innerHTML = `
        <div class="page-header">
            <h2>🐯 趋势动物</h2>
            <p class="text-muted">趋势温度 / 右侧 / 节气 / 强度 — 趋势交易数据服务</p>
        </div>
        <div class="card" style="max-width: 560px; margin: 40px auto;">
            <div class="card-header"><h3>🔑 配置你的趋势动物 API Key</h3></div>
            <div class="card-body">
                <p class="text-muted" style="margin-bottom: 12px;">使用趋势动物功能前，请先配置你自己的 API Key。密钥仅保存在服务器配置文件（config/trend_animal_config.json），不会写入前端代码或公开仓库。</p>
                <div style="margin-bottom: 12px;">
                    <label style="font-weight:600;">API Key（sk- 开头）</label>
                    <input type="password" id="ta-apikey-input" class="form-control" placeholder="sk-xxxxxxxxxxxxxxxx" style="margin-top:6px;">
                </div>
                <div id="ta-apikey-msg" style="margin-bottom: 12px; font-size: 13px;"></div>
                <button class="btn btn-primary" id="ta-apikey-save" style="width:100%;">保存并验证</button>
                <div class="text-muted" style="font-size:12px;margin-top:16px;line-height:1.8;">
                    <b>如何获取 API Key：</b><br>
                    1. 打开「趋势动物 Pro」微信小程序<br>
                    2. 进入「我的」页面，找到「接入 AI Agent」<br>
                    3. 按页面提示获取你的专属 API Key（充值后可用付费接口）
                </div>
            </div>
        </div>
    `;
    document.getElementById('ta-apikey-save').addEventListener('click', () => saveApiKey(container));
    document.getElementById('ta-apikey-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') saveApiKey(container);
    });
}

async function saveApiKey(container) {
    const input = document.getElementById('ta-apikey-input');
    const msg = document.getElementById('ta-apikey-msg');
    const key = input.value.trim();
    if (!key) {
        msg.innerHTML = '<span class="text-danger">请输入 API Key</span>';
        return;
    }
    msg.innerHTML = '<span class="text-muted">保存并验证中...</span>';
    try {
        const resp = await fetch('/api/trend/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key })
        });
        const result = await resp.json();
        if (result.success) {
            msg.innerHTML = `<span style="color:#16a34a">✅ ${result.message}（${result.data.masked_key}）</span>`;
            input.value = '';
            // 初始化主界面
            container.dataset.initialized = '1';
            container.dataset.maskedKey = result.data.masked_key || '';
            setTimeout(() => {
                renderTrendAnimalLayout(container);
                loadTrendStatus();
                loadDailyReport(false);
                loadSelectionDates();
            }, 800);
        } else {
            msg.innerHTML = `<span class="text-danger">❌ ${result.message}</span>`;
        }
    } catch (e) {
        msg.innerHTML = `<span class="text-danger">保存失败: ${e.message}</span>`;
    }
}

function renderTrendAnimalLayout(container) {
    container.innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <h2>🐯 趋势动物</h2>
                <p class="text-muted">趋势温度 / 右侧 / 节气 / 强度 — 与 KHunter 选股结果联动确认</p>
            </div>
            <button class="btn btn-sm" id="ta-open-config" title="查看/更换 API Key">⚙️ API配置</button>
        </div>

        <!-- API 配置区（默认折叠） -->
        <div class="card" id="ta-config-card" style="display:none;margin-top:12px;">
            <div class="card-body" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <span class="text-muted">当前密钥: <b id="ta-masked-key"></b></span>
                <input type="password" id="ta-apikey-input2" class="form-control" placeholder="输入新 API Key 替换（sk- 开头）" style="max-width:280px;">
                <button class="btn btn-sm btn-primary" id="ta-apikey-save2">更换密钥</button>
                <span id="ta-apikey-msg2" style="font-size:13px;"></span>
            </div>
        </div>

        <!-- 状态栏 -->
        <div class="ta-status-bar" id="ta-status-bar">
            <span class="loading">加载数据状态中...</span>
        </div>

        <!-- 趋势日报（打开页面自动展示，服务端按日缓存） -->
        <div class="card" style="margin-top: 16px;">
            <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <h3>📰 趋势日报</h3>
                <div style="display:flex;gap:8px;align-items:center;">
                    <span id="ta-report-meta" class="text-muted" style="font-size:12px;"></span>
                    <button class="btn btn-sm" id="ta-refresh-report" title="重新调用付费接口构建（约1元）">🔄 重新生成</button>
                </div>
            </div>
            <div class="card-body">
                <div id="ta-daily-report"><p class="loading">正在加载趋势日报（首次构建约需几秒）...</p></div>
            </div>
        </div>

        <!-- 信号股趋势确认 -->
        <div class="card" style="margin-top: 16px;">
            <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <h3>📡 信号股趋势确认（选股结果 × 趋势动物）</h3>
                <div style="display:flex;gap:8px;align-items:center;">
                    <select id="ta-date-select" class="form-control" style="width:150px;"></select>
                    <button class="btn btn-primary" id="ta-load-signals">获取趋势确认</button>
                </div>
            </div>
            <div class="card-body">
                <div id="ta-cost-note" class="text-muted" style="font-size:12px;margin-bottom:8px;"></div>
                <div id="ta-signal-table"><p class="text-muted">选择选股日期后点击「获取趋势确认」（付费字段快照，仅请求必要字段）</p></div>
            </div>
        </div>

        <!-- 个股趋势查询 -->
        <div class="card" style="margin-top: 16px;">
            <div class="card-header"><h3>🔍 个股趋势查询</h3></div>
            <div class="card-body">
                <div style="display:flex;gap:8px;margin-bottom:12px;">
                    <input type="text" id="ta-search-input" class="form-control" placeholder="输入名称或代码，如 贵州茅台 / 600519" style="max-width:320px;">
                    <button class="btn btn-primary" id="ta-search-btn">搜索（0.01元/次）</button>
                </div>
                <div id="ta-search-results"></div>
                <div id="ta-stock-detail" style="margin-top:12px;"></div>
            </div>
        </div>

        <div class="ta-footer">
            <p>数据来源：趋势动物 API（trendtrader.cn）｜趋势温度/右侧/节气/强度等指标为接口直接返回的事实；「温转热/温转平/止盈复核」等标签为基于趋势动物规则的分析判断。</p>
            <p>⚠️ 趋势动物的指标和分析结果仅供参考，不构成投资建议，交易盈亏需用户自行承担。</p>
        </div>
    `;

    document.getElementById('ta-load-signals').addEventListener('click', loadSignalStocks);
    document.getElementById('ta-masked-key').textContent = document.getElementById('trend-animal-page').dataset.maskedKey || '';
    document.getElementById('ta-open-config').addEventListener('click', () => {
        const card = document.getElementById('ta-config-card');
        card.style.display = card.style.display === 'none' ? '' : 'none';
    });
    document.getElementById('ta-apikey-save2').addEventListener('click', async () => {
        const input = document.getElementById('ta-apikey-input2');
        const msg = document.getElementById('ta-apikey-msg2');
        const key = input.value.trim();
        if (!key) { msg.innerHTML = '<span class="text-danger">请输入新 API Key</span>'; return; }
        msg.innerHTML = '<span class="text-muted">验证中...</span>';
        try {
            const resp = await fetch('/api/trend/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key })
            });
            const result = await resp.json();
            if (result.success) {
                msg.innerHTML = `<span style="color:#16a34a">✅ 已更换并验证通过（${result.data.masked_key}）</span>`;
                document.getElementById('ta-masked-key').textContent = result.data.masked_key;
                document.getElementById('trend-animal-page').dataset.maskedKey = result.data.masked_key;
                input.value = '';
            } else {
                msg.innerHTML = `<span class="text-danger">❌ ${result.message}</span>`;
            }
        } catch (e) {
            msg.innerHTML = `<span class="text-danger">保存失败: ${e.message}</span>`;
        }
    });
    document.getElementById('ta-refresh-report').addEventListener('click', () => {
        if (confirm('重新生成会重新调用付费接口（约1元），当日已构建过建议使用缓存。确定重新生成？')) {
            loadDailyReport(true);
        }
    });
    document.getElementById('ta-search-btn').addEventListener('click', doSearch);
    document.getElementById('ta-search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch();
    });
}

// ==================== 状态栏 ====================
async function loadTrendStatus() {
    const bar = document.getElementById('ta-status-bar');
    try {
        const resp = await fetch('/api/trend/status');
        const result = await resp.json();
        if (!result.success) {
            bar.innerHTML = `<span class="text-danger">趋势动物: ${result.message}</span>`;
            return;
        }
        const d = result.data;
        taState.fieldPrices = d.field_prices || {};
        taState.defaultFields = d.default_fields || [];

        const ashare = (d.update_status || []).find(x => x.asset === 'A股') || {};
        const etf = (d.update_status || []).find(x => x.asset === 'ETF基金') || {};
        const bal = d.balance || {};
        bar.innerHTML = `
            <div class="ta-status-item"><span class="ta-label">A股数据日期</span><b>${ashare.asOfDate || '-'}</b></div>
            <div class="ta-status-item"><span class="ta-label">ETF数据日期</span><b>${etf.asOfDate || '-'}</b></div>
            <div class="ta-status-item"><span class="ta-label">账户余额</span><b>${bal.balance !== undefined ? '¥' + Number(bal.balance).toFixed(2) : '未返回'}</b></div>
            <div class="ta-status-item"><span class="ta-label">快照默认字段</span><b>${taState.defaultFields.length}个（精简控制成本）</b></div>
        `;
    } catch (e) {
        bar.innerHTML = `<span class="text-danger">状态加载失败: ${e.message}</span>`;
    }
}

// ==================== 趋势日报 ====================
async function loadDailyReport(refresh) {
    const box = document.getElementById('ta-daily-report');
    const meta = document.getElementById('ta-report-meta');
    box.innerHTML = '<p class="loading">正在加载趋势日报...</p>';
    try {
        const resp = await fetch(`/api/trend/daily-report${refresh ? '?refresh=1' : ''}`);
        const result = await resp.json();
        if (!result.success) {
            box.innerHTML = `<p class="text-danger">${result.message}</p>`;
            return;
        }
        renderDailyReport(result.data, box);
        const d = result.data;
        meta.textContent = `数据日期 ${d.as_of_date || '-'} ｜ 构建于 ${d.built_at || '-'} ｜ ${d.from_cache ? '缓存（免费）' : '新构建'} ｜ ${d.cost_note || ''}`;
    } catch (e) {
        box.innerHTML = `<p class="text-danger">加载失败: ${e.message}</p>`;
    }
}

function marketTempCard(item) {
    const curr = item.trendTemperatureCurr || '-';
    const prev = item.trendTemperaturePrev;
    const rightSide = item.isTrendRightSide === true ? '右侧' : '非右侧';
    const strength = item.trendStrengthGlobalCurr !== undefined && item.trendStrengthGlobalCurr !== null ? Number(item.trendStrengthGlobalCurr).toFixed(1) : '-';
    const r1d = item.return1d !== undefined && item.return1d !== null ? (item.return1d * 100).toFixed(2) + '%' : '-';
    const r1m = item.return1m !== undefined && item.return1m !== null ? (item.return1m * 100).toFixed(2) + '%' : '-';
    // 基于接口数据计算的修复描述（前温度→今温度）
    const shift = prev && prev !== curr ? `${prev} → ${curr}` : `维持${curr}`;
    return `
        <div class="ta-market-card">
            <div class="ta-market-name">${item.name || item.tickerName || ''}</div>
            <div class="ta-market-temp">${tempBadge(curr)}</div>
            <div class="ta-market-info">
                <div>状态: <b>${rightSide}</b></div>
                <div>温度: ${shift}</div>
                <div>强度: <b>${strength}</b></div>
                <div>1日: ${r1d} ｜ 1月: ${r1m}</div>
            </div>
        </div>`;
}

function hotStockRow(s, idx) {
    const rightSide = s.isTrendRightSide === true ? '✅' : '—';
    const strength = s.trendStrengthGlobalCurr !== undefined && s.trendStrengthGlobalCurr !== null ? Number(s.trendStrengthGlobalCurr).toFixed(1) : '-';
    const r1d = s.return1d !== undefined && s.return1d !== null ? (s.return1d * 100).toFixed(2) + '%' : '-';
    const r1m = s.return1m !== undefined && s.return1m !== null ? (s.return1m * 100).toFixed(2) + '%' : '-';
    const code = (s.tickerSymbol || '').split('.')[0];
    const nameLink = code ? `<a href="javascript:void(0)" onclick="viewStockDetail('${code}')" class="stock-link">${s.tickerName}</a>` : (s.tickerName || '-');
    return `<tr>
        <td>${idx + 1}</td>
        <td>${nameLink}</td>
        <td>${s.industryName || '-'}</td>
        <td>${tempBadge(s.trendTemperatureCurr)}</td>
        <td>${rightSide}</td>
        <td>${s.trendPhaseCurr || '-'}</td>
        <td><b>${strength}</b></td>
        <td>${r1d}</td>
        <td>${r1m}</td>
    </tr>`;
}

function stockChip(s, type) {
    const code = (s.tickerSymbol || '').split('.')[0];
    const strength = s.trendStrengthGlobalCurr !== undefined && s.trendStrengthGlobalCurr !== null ? Number(s.trendStrengthGlobalCurr).toFixed(0) : '';
    const flagText = (s.risk_flags || []).join('/');
    const onclick = code ? `onclick="viewStockDetail('${code}')"` : '';
    const extra = type === 'risk' && flagText ? `<span class="chip-strength">${flagText}</span>` : (strength ? `<span class="chip-strength">强度${strength}</span>` : '');
    return `<span class="ta-stock-chip ${type}" ${onclick}>${s.tickerName}${extra}</span>`;
}

function renderDailyReport(d, box) {
    const market = d.market || [];
    const hotStocks = d.hot_stocks || [];
    const hotEtfs = d.hot_etfs || [];
    const riskWatch = d.risk_watch || [];
    const industries = d.main_industries || [];

    let html = '<div class="ta-market-row">' + market.map(marketTempCard).join('') + '</div>';

    // 主线板块（基于接口数据计算）
    if (industries.length > 0) {
        html += `<div class="ta-section"><h4>🔥 今日主线板块 <small class="text-muted">温转热个股行业分布，基于接口数据计算</small></h4><div class="ta-chips">` +
            industries.map(i => `<span class="ta-chip-static">${i.industry} <b>×${i.count}</b></span>`).join('') + '</div></div>';
    }

    // 温转热个股：chips 速览 + 明细表
    html += `<div class="ta-section"><h4>🚀 今日温转热（A股，${hotStocks.length}只）<small class="text-muted">官方「温转热」组合成分 = 今日温度由温升热的品种</small></h4>`;
    if (hotStocks.length === 0) {
        html += '<p class="text-muted">今日无温转热个股（弱势市场，右侧机会少）</p>';
    } else {
        html += '<div class="ta-chips" style="margin-bottom:10px;">' + hotStocks.map(s => stockChip(s, 'hot')).join('') + '</div>';
        html += `<details><summary style="cursor:pointer;color:#6b7280;font-size:13px;">查看明细表</summary><table class="diag-table" style="margin-top:8px;"><thead><tr><th>#</th><th>名称</th><th>行业</th><th>温度</th><th>右侧</th><th>节气</th><th>强度</th><th>1日</th><th>1月</th></tr></thead><tbody>` +
            hotStocks.map(hotStockRow).join('') + '</tbody></table></details>';
    }
    html += '</div>';

    // 温转热ETF
    if (hotEtfs.length > 0) {
        html += `<div class="ta-section"><h4>📈 温转热（ETF基金，${hotEtfs.length}只）</h4><div class="ta-chips" style="margin-bottom:10px;">` +
            hotEtfs.map(s => stockChip(s, 'hot')).join('') + '</div>' +
            `<details><summary style="cursor:pointer;color:#6b7280;font-size:13px;">查看明细表</summary><table class="diag-table" style="margin-top:8px;"><thead><tr><th>#</th><th>名称</th><th>分类</th><th>温度</th><th>右侧</th><th>节气</th><th>强度</th><th>1日</th><th>1月</th></tr></thead><tbody>` +
            hotEtfs.map(hotStockRow).join('') + '</tbody></table></details></div>';
    }

    // 风险观察
    html += `<div class="ta-section"><h4>⚠️ 风险观察（止盈信号）</h4>`;
    if (riskWatch.length === 0) {
        html += '<p class="text-muted">今日温转热品种中无危险信号/沸/开香槟</p>';
    } else {
        html += '<div class="ta-chips">' + riskWatch.map(s => stockChip(s, 'risk')).join('') + '</div>';
    }
    html += '</div>';

    html += `<p class="text-muted" style="font-size:12px;margin-top:8px;">温度/右侧/节气/强度/涨幅/行业为接口直接返回的事实；主线板块分布为基于接口数据的聚合计算。「温转热」组合由趋势动物官方维护。</p>`;
    box.innerHTML = html;
}

// ==================== 选股日期 ====================
async function loadSelectionDates() {
    const select = document.getElementById('ta-date-select');
    try {
        const resp = await fetch('/api/trend/selection-dates');
        const result = await resp.json();
        if (result.success && result.data.length > 0) {
            select.innerHTML = result.data.map(d =>
                `<option value="${d.selection_date}">${d.selection_date} (${d.cnt}只)</option>`
            ).join('');
        } else {
            select.innerHTML = '<option value="">无选股记录</option>';
        }
    } catch (e) {
        select.innerHTML = '<option value="">加载失败</option>';
    }
}

// ==================== 信号股趋势确认 ====================
async function loadSignalStocks() {
    const date = document.getElementById('ta-date-select').value;
    const table = document.getElementById('ta-signal-table');
    const costNote = document.getElementById('ta-cost-note');
    table.innerHTML = '<p class="loading">正在获取趋势快照（tmId映射 + 批量快照）...</p>';
    costNote.textContent = '';

    try {
        const resp = await fetch(`/api/trend/signal-stocks?date=${date || ''}`);
        const result = await resp.json();
        if (!result.success) {
            table.innerHTML = `<p class="text-danger">${result.message}</p>`;
            return;
        }
        const d = result.data;
        costNote.textContent = d.cost_note ? `费用说明：${d.cost_note}` : '';
        renderSignalTable(d.stocks, table);
    } catch (e) {
        table.innerHTML = `<p class="text-danger">请求失败: ${e.message}</p>`;
    }
}

const TEMP_CLASS = { '沸': 'ta-temp-7', '热': 'ta-temp-6', '温': 'ta-temp-5', '平': 'ta-temp-4', '凉': 'ta-temp-3', '寒': 'ta-temp-2', '冻': 'ta-temp-1' };

function tempBadge(t) {
    if (!t) return '<span class="text-muted">-</span>';
    return `<span class="ta-temp ${TEMP_CLASS[t] || ''}">${t}</span>`;
}

function tagBadge(tag) {
    const cls = { buy: 'ta-tag-buy', sell: 'ta-tag-sell', risk: 'ta-tag-risk', strong: 'ta-tag-strong' }[tag.type] || '';
    return `<span class="ta-tag ${cls}">${tag.text}</span>`;
}

function renderSignalTable(stocks, container) {
    if (!stocks || stocks.length === 0) {
        container.innerHTML = '<p class="text-muted">该日期无选股记录</p>';
        return;
    }
    const rows = stocks.map(s => {
        const snap = s.snapshot || {};
        const rightSide = snap.isTrendRightSide === true ? '<span style="color:#16a34a">右侧</span>' : (snap.isTrendRightSide === false ? '<span class="text-muted">左侧</span>' : '-');
        const strength = snap.trendStrengthGlobalCurr !== undefined && snap.trendStrengthGlobalCurr !== null ? Number(snap.trendStrengthGlobalCurr).toFixed(1) : '-';
        const r1d = snap.return1d !== undefined && snap.return1d !== null ? (snap.return1d * 100).toFixed(2) + '%' : '-';
        const tags = (s.discipline_tags || []).map(tagBadge).join('') || '<span class="text-muted">-</span>';
        const rowCls = (s.discipline_tags || []).some(t => t.type === 'buy') ? 'ta-row-buy' :
                       (s.discipline_tags || []).some(t => t.type === 'sell') ? 'ta-row-sell' : '';
        return `<tr class="${rowCls}">
            <td><a href="javascript:void(0)" onclick="viewStockDetail('${s.code}')" class="stock-link">${s.code}</a></td>
            <td>${s.name}</td>
            <td style="font-size:12px;">${(s.strategies || []).join('<br>')}</td>
            <td>${tempBadge(snap.trendTemperaturePrev)} → ${tempBadge(snap.trendTemperatureCurr)}</td>
            <td>${rightSide}</td>
            <td>${snap.trendPhaseCurr || '-'}</td>
            <td>${strength}</td>
            <td>${r1d}</td>
            <td>${tags}</td>
        </tr>`;
    }).join('');

    container.innerHTML = `
        <table class="diag-table ta-signal-table">
            <thead><tr>
                <th>代码</th><th>名称</th><th>来源策略</th>
                <th>温度(前→今)</th><th>右侧</th><th>节气</th>
                <th>强度</th><th>日涨幅</th><th>纪律标签(分析判断)</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>
        <p class="text-muted" style="font-size:12px;margin-top:8px;">共 ${stocks.length} 只。温度/右侧/节气/强度/涨幅为接口直接返回的事实；纪律标签为基于趋势动物规则（温转热/温转平/止盈信号/强度≥90）的分析判断。</p>
    `;
}

// ==================== 个股查询 ====================
async function doSearch() {
    const kw = document.getElementById('ta-search-input').value.trim();
    const box = document.getElementById('ta-search-results');
    if (!kw) { box.innerHTML = '<p class="text-muted">请输入关键词</p>'; return; }
    box.innerHTML = '<p class="loading">搜索中...</p>';
    try {
        const resp = await fetch(`/api/trend/search?keyword=${encodeURIComponent(kw)}`);
        const result = await resp.json();
        if (!result.success) { box.innerHTML = `<p class="text-danger">${result.message}</p>`; return; }
        taState.searchResults = result.data || [];
        if (taState.searchResults.length === 0) { box.innerHTML = '<p class="text-muted">未找到匹配品种</p>'; return; }
        box.innerHTML = '<div class="ta-search-chips">' + taState.searchResults.map((item, i) =>
            `<span class="ta-chip" onclick="window._taSelectStock(${i})">${item.tickerName} <small>${item.tickerSymbol || ''} [${item.asset}]</small></span>`
        ).join('') + '</div>';
    } catch (e) {
        box.innerHTML = `<p class="text-danger">搜索失败: ${e.message}</p>`;
    }
}

window._taSelectStock = async function (idx) {
    const item = taState.searchResults[idx];
    if (!item) return;
    const detail = document.getElementById('ta-stock-detail');
    detail.innerHTML = '<p class="loading">获取趋势快照...</p>';
    try {
        const resp = await fetch(`/api/trend/snapshot?tmIds=${item.tmId}`);
        const result = await resp.json();
        if (!result.success || !result.data || result.data.length === 0) {
            detail.innerHTML = `<p class="text-danger">${result.message || '快照无数据'}</p>`;
            return;
        }
        const snap = result.data[0];
        const r1d = snap.return1d !== undefined && snap.return1d !== null ? (snap.return1d * 100).toFixed(2) + '%' : '-';
        detail.innerHTML = `
            <div class="ta-detail-card">
                <div class="ta-detail-header">
                    <h4>${item.tickerName} <small>${item.tickerSymbol || ''} [${item.asset}]</small></h4>
                    <button class="btn btn-sm btn-primary" onclick="window._taLoadPlot(${item.tmId}, '${item.tickerName}')">生成趋势图（0.1元/次）</button>
                </div>
                <div class="ta-detail-grid">
                    <div>温度: ${tempBadge(snap.trendTemperaturePrev)} → ${tempBadge(snap.trendTemperatureCurr)}</div>
                    <div>右侧: ${snap.isTrendRightSide === true ? '✅ 是' : (snap.isTrendRightSide === false ? '❌ 否' : '-')}</div>
                    <div>节气: ${snap.trendPhaseCurr || '-'}</div>
                    <div>全局强度: ${snap.trendStrengthGlobalCurr !== undefined ? Number(snap.trendStrengthGlobalCurr).toFixed(1) : '-'}</div>
                    <div>日涨幅: ${r1d}</div>
                    <div>风险标志: ${[snap.stopwinFlagByDangerSignal && '危险', snap.stopwinFlagByBoilingTemperature && '沸', snap.stopwinFlagByPopChampagne && '开香槟'].filter(Boolean).join('/') || '无'}</div>
                </div>
                <div id="ta-plot-box" style="margin-top:12px;"></div>
            </div>
        `;
    } catch (e) {
        detail.innerHTML = `<p class="text-danger">快照失败: ${e.message}</p>`;
    }
};

window._taLoadPlot = async function (tmId, name) {
    const box = document.getElementById('ta-plot-box');
    box.innerHTML = '<p class="loading">生成趋势图中（约0.1元/次）...</p>';
    try {
        const resp = await fetch(`/api/trend/plot?tmId=${tmId}&seq=1`);
        const result = await resp.json();
        if (!result.success || !result.data) {
            box.innerHTML = `<p class="text-danger">${result.message || '生成失败'}</p>`;
            return;
        }
        box.innerHTML = `<div class="ta-plot"><p class="text-muted" style="font-size:12px;">${name} 趋势曲线（数据来源：趋势动物）</p><img src="data:image/png;base64,${result.data}" style="max-width:100%;border-radius:8px;"></div>`;
    } catch (e) {
        box.innerHTML = `<p class="text-danger">生成失败: ${e.message}</p>`;
    }
};
