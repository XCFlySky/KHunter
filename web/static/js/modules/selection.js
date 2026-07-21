/**
 * 选股相关功能模块
 */

// 缓存最近一次选股结果，用于手动保存
let lastSelectionResults = null;
let lastSelectionTime = null;
let lastSelectionDate = null;

/**
 * 执行选股 - 先显示策略选择对话框
 */
export async function runSelection() {
    try {
        // 加载策略列表
        const response = await fetch('/api/strategies');
        const result = await response.json();
        
        if (result.success) {
            showStrategySelectionModal(result.data);
        } else {
            alert('加载策略列表失败: ' + result.error);
        }
    } catch (error) {
        alert('加载策略列表失败: ' + error.message);
    }
}

/**
 * 显示策略选择对话框
 * @param {Array} strategies - 策略列表
 */
export function showStrategySelectionModal(strategies) {
    const modal = document.getElementById('strategy-selection-modal');
    // 使用更精确的选择器，确保获取模态框内的策略列表
    const list = document.querySelector('#strategy-selection-modal #strategy-list');
    
    // 生成策略列表 - 显示中文名称，默认未选中
    list.innerHTML = strategies.map(s => `
        <div class="strategy-item">
            <input type="checkbox" 
                   id="strategy-${s.name}" 
                   value="${s.name}">
            <label for="strategy-${s.name}">
                <strong>${s.icon} ${s.display_name}</strong>
                <p class="text-muted">${s.description}</p>
                <p class="text-muted">${Object.keys(s.params).length} 个参数</p>
            </label>
        </div>
    `).join('');
    
    // 初始化日期选择器为当日（使用更精确的选择器避免与span冲突）
    const selectionDateInput = document.querySelector('#strategy-selection-modal #selection-date');
    if (selectionDateInput) {
        const today = new Date().toISOString().split('T')[0];
        selectionDateInput.value = today;
    }
    
    modal.classList.add('active');
}

/**
 * 获取选中的策略和逻辑（OR/AND）
 * @returns {Object} 选中的策略和逻辑
 */
export function getSelectedStrategiesAndLogic() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]:checked');
    const strategies = Array.from(checkboxes).map(cb => cb.value);
    
    // 获取逻辑值（从隐藏的input中获取，默认为 'or'）
    const logicInput = document.querySelector('input[name="logic"]');
    const logic = logicInput ? logicInput.value : 'or';
    
    return { strategies, logic };
}

/**
 * 确认策略选择
 */
export async function confirmStrategySelection() {
    const { strategies, logic } = getSelectedStrategiesAndLogic();
    
    if (strategies.length === 0) {
        alert('请至少选择一个策略');
        return;
    }
    
    // 获取用户选择的日期（使用更精确的选择器避免与span冲突）
    const selectionDateInput = document.querySelector('#strategy-selection-modal #selection-date');
    let selectionDate = null;

    console.log('选股日期输入框值:', selectionDateInput ? selectionDateInput.value : '未找到元素');

    if (selectionDateInput && selectionDateInput.value) {
        selectionDate = selectionDateInput.value;
    }

    console.log('最终选股日期:', selectionDate);
    
    // 是否显示未选中股票及原因
    const diagCheckbox = document.querySelector('#strategy-selection-modal #include-diagnostics');
    const includeDiagnostics = diagCheckbox ? diagCheckbox.checked : false;
    
    // 校验是否为A股交易日：周末/节假日不开盘，不能选股
    const checkDate = selectionDate || new Date().toISOString().split('T')[0];
    try {
        const resp = await fetch(`/api/is-trading-day?date=${checkDate}`);
        const r = await resp.json();
        if (r.success && r.data && r.data.is_trading_day === false) {
            alert(`${checkDate} 是非交易日（周末或节假日），A股不开盘，不能选股`);
            return;
        }
    } catch (e) {
        console.warn('交易日校验失败，继续执行:', e.message);
    }
    
    closeStrategyModal();
    executeSelectionWithStrategies(strategies, logic, selectionDate, includeDiagnostics);
}

/**
 * 关闭策略选择对话框
 */
export function closeStrategyModal() {
    document.getElementById('strategy-selection-modal').classList.remove('active');
}

/**
 * 全选所有策略
 */
export function selectAllStrategies() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]');
    checkboxes.forEach(cb => cb.checked = true);
}

/**
 * 反选所有策略
 */
export function deselectAllStrategies() {
    const checkboxes = document.querySelectorAll('#strategy-list input[type="checkbox"]');
    checkboxes.forEach(cb => cb.checked = !cb.checked);
}

const PENDING_SELECTION_KEY = 'khunter_pending_selection_task';

/**
 * 记录/清除未完成的选股任务（用于页面刷新后恢复）
 */
function savePendingSelectionTask(taskId) {
    try { sessionStorage.setItem(PENDING_SELECTION_KEY, JSON.stringify({ task_id: taskId, started: Date.now() })); } catch (e) {}
}

function clearPendingSelectionTask() {
    try { sessionStorage.removeItem(PENDING_SELECTION_KEY); } catch (e) {}
}

/**
 * 应用选股结果：缓存、显示按钮并渲染到页面（执行完成/断线恢复共用）
 */
function applySelectionResult(result) {
    console.log('选股成功，数据类型:', typeof result.data);
    console.log('选股结果键:', Object.keys(result.data || {}));
    // 缓存选股结果，供手动保存和导出使用
    lastSelectionResults = result.data;
    lastSelectionTime = result.time;
    lastSelectionDate = result.selection_date || result.time.split(' ')[0];
    
    // 显示选股日期
    const selectionDateEl = document.getElementById('selection-date-display');
    if (selectionDateEl) {
        selectionDateEl.textContent = `选股日期: ${lastSelectionDate}`;
    }
    
    // 显示导出和保存按钮
    const exportBtn = document.getElementById('export-selection-btn');
    if (exportBtn) {
        exportBtn.style.display = '';
        exportBtn.disabled = false;
    }
    const saveBtn = document.getElementById('save-selection-btn');
    if (saveBtn) {
        saveBtn.style.display = '';
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<span class="icon">💾</span> 保存结果';
        saveBtn.classList.remove('btn-success');
    }
    renderSelectionResults(result.data, result.time, result.filter_stats, result.strategy_display_names);
}

/**
 * 页面刷新/重新打开时，若有未完成的选股任务则恢复轮询，完成后自动显示结果
 */
export async function resumePendingSelection() {
    let pending = null;
    try { pending = JSON.parse(sessionStorage.getItem(PENDING_SELECTION_KEY) || 'null'); } catch (e) {}
    if (!pending || !pending.task_id) return;
    // 超过3小时的任务视为已过期
    if (Date.now() - (pending.started || 0) > 3 * 3600 * 1000) {
        clearPendingSelectionTask();
        return;
    }
    
    const resultsEl = document.getElementById('selection-results');
    if (!resultsEl) return;
    const indicator = document.getElementById('status-indicator');
    const btn = document.getElementById('run-selection-btn');
    
    console.log('恢复未完成的选股任务:', pending.task_id);
    resultsEl.innerHTML = '<p class="loading">选股任务正在后台执行，请稍候（网络波动不影响执行）...</p>';
    if (indicator) indicator.innerHTML = '<span class="dot yellow"></span> 运行中';
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="icon">⏳</span> 选股中...'; }
    
    const result = await pollSelectionResult(pending.task_id);
    clearPendingSelectionTask();
    
    if (result.success) {
        applySelectionResult(result);
    } else {
        resultsEl.innerHTML = `<p class="loading text-danger">选股失败: ${result.error || '未知错误'}</p>`;
    }
    if (indicator) indicator.innerHTML = '<span class="dot green"></span> 就绪';
    if (btn) { btn.disabled = false; btn.innerHTML = '<span class="icon">▶️</span> 执行选股'; }
}

/**
 * 轮询异步选股任务结果
 * @param {string} taskId - 任务ID
 * @returns {Object} 选股结果（与同步接口返回结构一致）
 */
async function pollSelectionResult(taskId) {
    const interval = 5000;          // 每5秒轮询一次
    const maxWait = 3 * 3600 * 1000; // 最长等待3小时
    const start = Date.now();
    let consecutiveErrors = 0;
    
    while (Date.now() - start < maxWait) {
        await new Promise(r => setTimeout(r, interval));
        try {
            const resp = await fetch(`/api/select/result/${taskId}`);
            const data = await resp.json();
            consecutiveErrors = 0;
            if (!data.success) {
                return { success: false, error: data.error || '任务查询失败' };
            }
            if (data.status === 'running') {
                continue;
            }
            if (data.status === 'done') {
                return data.result || { success: false, error: '结果为空' };
            }
            return { success: false, error: data.error || '选股执行失败' };
        } catch (e) {
            // 网络瞬时异常（如切换网络/锁屏）不直接失败，继续重试
            consecutiveErrors++;
            console.warn(`轮询选股结果失败(第${consecutiveErrors}次):`, e.message);
            if (consecutiveErrors >= 12) {
                return { success: false, error: '网络连接异常，请刷新页面后查看选股结果' };
            }
        }
    }
    return { success: false, error: '选股超时：任务耗时过长' };
}

/**
 * 执行选股（指定策略和逻辑）
 * @param {Array} strategies - 策略列表
 * @param {string} logic - 逻辑（OR/AND）
 * @param {string} selectionDate - 选股日期，格式为YYYY-MM-DD，null表示使用最新数据
 * @param {boolean} includeDiagnostics - 是否返回未选中股票及原因
 */
export async function executeSelectionWithStrategies(strategies, logic = 'or', selectionDate = null, includeDiagnostics = false) {
    // 缓存选股日期，供手动保存使用
    lastSelectionDate = selectionDate;
    
    const btn = document.getElementById('run-selection-btn');
    const indicator = document.getElementById('status-indicator');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 选股中...';
    indicator.innerHTML = '<span class="dot yellow"></span> 运行中';
    
    // 切换到选股结果页
    import('./navigation.js').then(module => module.switchPage('selection'));
    document.getElementById('selection-results').innerHTML = '<p class="loading">正在执行选股策略，请稍候...</p>';
    
    console.log('选股请求开始', { strategies, logic, selectionDate });
    
    try {
        // 设置较长的超时时间（3小时）
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10800000);
        
        const requestBody = { strategies: strategies, logic: logic, end_date: selectionDate, include_diagnostics: includeDiagnostics, async: true };
        console.log('发送请求体:', JSON.stringify(requestBody));
        
        const response = await fetch('/api/select', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody),
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        console.log('响应状态码:', response.status);
        
        // 检查响应是否为JSON
        const contentType = response.headers.get('content-type');
        console.log('响应Content-Type:', contentType);
        
        let result;
        let responseText = null;
        try {
            // 先读取文本，避免重复读取响应体
            responseText = await response.text();
            console.log('原始响应长度:', responseText.length);
            
            // 尝试解析JSON
            if (!responseText) {
                throw new Error('响应体为空');
            }
            result = JSON.parse(responseText);
            console.log('响应数据:', result);
        } catch (parseError) {
            console.error('JSON解析失败:', parseError);
            if (responseText) {
                console.error('原始响应:', responseText.substring(0, 500));
            }
            throw new Error('服务器返回的数据格式错误: ' + parseError.message);
        }
        
        // 异步模式：服务器立即返回 task_id，改为轮询获取最终结果（避免长连接被移动网络掐断）
        if (result.success && result.async && result.task_id) {
            console.log('选股任务已在后台运行, task_id:', result.task_id);
            document.getElementById('selection-results').innerHTML = 
                '<p class="loading">选股任务正在后台执行，请稍候（网络波动不影响执行）...</p>';
            savePendingSelectionTask(result.task_id);
            result = await pollSelectionResult(result.task_id);
            clearPendingSelectionTask();
            console.log('异步选股最终结果:', result);
        }
        
        if (result.success) {
            applySelectionResult(result);
        } else {
            console.error('选股失败:', result.error);
            document.getElementById('selection-results').innerHTML = 
                `<p class="loading text-danger">选股失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('选股异常:', error);
        console.error('错误堆栈:', error.stack);
        
        if (error.name === 'AbortError') {
            document.getElementById('selection-results').innerHTML = 
                `<p class="loading text-danger">选股超时：请求耗时过长，请稍后重试或减少选股策略数量</p>`;
        } else {
            document.getElementById('selection-results').innerHTML = 
                `<p class="loading text-danger">选股失败: ${error.message}</p>`;
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="icon">▶️</span> 执行选股';
        indicator.innerHTML = '<span class="dot green"></span> 就绪';
    }
}

/**
 * 分析策略交集
 * @param {Object} results - 选股结果
 * @returns {Object} 交集分析结果
 */
export function analyzeStrategyIntersection(results) {
    const stockStrategies = {};
    for (const [strategyName, signals] of Object.entries(results)) {
        for (const signal of signals) {
            const code = signal.code;
            if (!stockStrategies[code]) {
                stockStrategies[code] = {code: code, name: signal.name, strategies: [], count: 0, signals: {}};
            }
            stockStrategies[code].strategies.push(strategyName);
            stockStrategies[code].signals[strategyName] = signal.signals;
            stockStrategies[code].count++;
        }
    }
    const byCount = {};
    for (const [code, data] of Object.entries(stockStrategies)) {
        const count = data.count;
        if (!byCount[count]) {
            byCount[count] = [];
        }
        byCount[count].push(data);
    }
    const totalStrategies = Object.keys(results).length;
    const stocksByStrategy = {};
    for (const [name, signals] of Object.entries(results)) {
        stocksByStrategy[name] = signals.length;
    }
    const multiStrategyCount = Object.values(byCount).filter((_, count) => count > 1).reduce((sum, stocks) => sum + stocks.length, 0);
    const intersectionRate = Object.keys(stockStrategies).length > 0 ? (multiStrategyCount / Object.keys(stockStrategies).length).toFixed(2) : 0;
    return {total: Object.keys(stockStrategies).length, byCount: byCount, intersectionStats: {totalStrategies: totalStrategies, stocksByStrategy: stocksByStrategy, intersectionRate: parseFloat(intersectionRate)}};
}

/**
 * 渲染交集分析
 * @param {Object} analysis - 交集分析数据
 * @returns {string} HTML字符串
 */
export function renderIntersectionAnalysis(analysis) {
    // 验证分析数据是否有效
    if (!analysis || typeof analysis !== 'object') {
        console.warn('无效的交集分析数据:', analysis);
        return '';
    }
    
    // 获取 by_count 数据（后端返回的是 by_count，不是 byCount）
    const byCount = analysis.by_count || analysis.byCount || {};
    
    // 验证 by_count 是否为对象
    if (typeof byCount !== 'object' || byCount === null) {
        console.warn('by_count 不是有效的对象:', byCount);
        return '';
    }
    
    // 获取交集统计信息
    const intersectionStats = analysis.intersection_stats || analysis.intersectionStats || {};
    const intersectionRate = intersectionStats.intersection_rate || intersectionStats.intersectionRate || 0;
    
    // 构建HTML
    let html = '<div class="intersection-analysis"><h4>📊 策略交集分析</h4><p>总选股数：<strong>' + (analysis.total || 0) + '</strong>只</p><div class="intersection-stats">';
    
    // 获取并排序交集数量
    const sortedCounts = Object.keys(byCount).map(Number).sort((a, b) => b - a);
    
    // 如果没有交集数据，显示提示
    if (sortedCounts.length === 0) {
        html += '<div class="intersection-item"><span>暂无交集数据</span></div>';
    } else {
        // 遍历每个交集数量
        for (const count of sortedCounts) {
            const stocks = byCount[count];
            if (!Array.isArray(stocks)) {
                console.warn('stocks 不是数组:', stocks);
                continue;
            }
            
            const label = count === 1 ? '仅被1个策略选中' : '被' + count + '个策略同时选中';
            const badge = count > 1 ? '⭐' : '';
            html += '<div class="intersection-item"><span>' + label + '：<strong>' + stocks.length + '</strong>只 ' + badge + '</span></div>';
        }
    }
    
    html += '</div><p class="text-muted" style="margin: 8px 0 0 0; font-size: 13px;">交集率：' + (intersectionRate * 100).toFixed(1) + '%</p></div>';
    return html;
}

/**
 * 手动保存选股结果到数据库
 * 将缓存的选股数据发送到后端保存接口
 */
export async function saveSelectionResults() {
    // 检查是否有可保存的数据
    if (!lastSelectionResults || !lastSelectionTime) {
        alert('没有可保存的选股结果，请先执行选股');
        return;
    }

    const btn = document.getElementById('save-selection-btn');
    if (!btn) return;

    // 按钮状态：保存中
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 保存中...';

    try {
        // 后端已经返回中文名称作为键，直接使用结果
        // 为每个信号添加策略名称（如果还没有）
        const resultsToSave = JSON.parse(JSON.stringify(lastSelectionResults));
        
        for (const [strategyName, signals] of Object.entries(resultsToSave)) {
            // 跳过特殊字段
            if (strategyName.startsWith('_')) {
                continue;
            }
            
            // 为每个信号添加策略名称
            if (Array.isArray(signals)) {
                signals.forEach(signal => {
                    if (!signal.strategies) {
                        signal.strategies = [strategyName];
                    }
                });
            }
        }
        
        // 发送保存请求
        const response = await fetch('/api/save_selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: resultsToSave,
                time: lastSelectionTime,
                end_date: lastSelectionDate
            })
        });

        const result = await response.json();

        if (result.success) {
            // 保存成功，显示统计信息
            const msg = `保存成功：新增${result.saved || 0}条，更新${result.updated || 0}条，跳过${result.skipped || 0}条`;
            btn.innerHTML = '<span class="icon">✅</span> 已保存';
            btn.classList.add('btn-success');
            // 3秒后恢复按钮状态
            setTimeout(() => {
                btn.innerHTML = '<span class="icon">💾</span> 保存结果';
                btn.classList.remove('btn-success');
                btn.disabled = false;
            }, 3000);
            console.log(msg);
        } else {
            // 保存失败
            alert('保存失败: ' + (result.error || '未知错误'));
            btn.innerHTML = '<span class="icon">💾</span> 保存结果';
            btn.disabled = false;
        }
    } catch (error) {
        console.error('保存选股结果异常:', error);
        alert('保存失败: ' + error.message);
        btn.innerHTML = '<span class="icon">💾</span> 保存结果';
        btn.disabled = false;
    }
}

/**
 * 导出选股结果为Excel
 */
export async function exportSelectionResults() {
    // 检查是否有可导出的数据
    if (!lastSelectionResults || !lastSelectionTime) {
        alert('没有可导出的选股结果，请先执行选股');
        return;
    }
    
    const btn = document.getElementById('export-selection-btn');
    if (!btn) return;
    
    // 按钮状态：导出中
    btn.disabled = true;
    btn.innerHTML = '<span class="icon">⏳</span> 导出中...';
    
    try {
        // 调用后端API导出Excel
        const response = await fetch('/api/khunter/export_selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: lastSelectionResults,
                selection_date: lastSelectionDate,
                selection_time: lastSelectionTime
            })
        });
        
        if (response.ok) {
            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = '选股结果.xlsx';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="([^"]+)"/);
                if (match && match[1]) {
                    filename = decodeURIComponent(match[1]);
                }
            }
            
            // 下载文件
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } else {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.message || '导出失败');
        }
        
        // 恢复按钮状态
        btn.innerHTML = '<span class="icon">📥</span> 导出结果';
        btn.disabled = false;
        
    } catch (error) {
        console.error('导出选股结果异常:', error);
        alert('导出失败: ' + error.message);
        btn.innerHTML = '<span class="icon">📥</span> 导出结果';
        btn.disabled = false;
    }
}

// 暴露全局函数
window.exportSelectionResults = exportSelectionResults;

/**
 * 渲染选股结果
 * @param {Object} results - 选股结果
 * @param {string} time - 选股时间
 * @param {Object} filterStats - 过滤统计信息
 * @param {Object} strategyDisplayNames - 策略名称映射
 */
export function renderSelectionResults(results, time, filterStats, strategyDisplayNames = {}) {
    // 保存策略名称映射到全局变量，供保存时使用
    window.strategyDisplayNames = strategyDisplayNames || {};
    
    // 设置选股时间
    document.getElementById('selection-time').textContent = `选股时间: ${time}`;
    const container = document.getElementById('selection-results');
    
    // 检查results是否有效
    if (!results || typeof results !== 'object') {
        console.error('选股结果数据格式错误:', results);
        container.innerHTML = '<p class="loading text-danger">选股结果数据格式错误</p>';
        return;
    }
    
    let html = '';
    let totalCount = 0;
    let intersectionAnalysis = null;
    let intersectionStocks = null;
    
    // 提取特殊字段（后端返回的是 _intersection_analysis，不是 _intersectionAnalysis）
    if (results._intersection_analysis) {
        intersectionAnalysis = results._intersection_analysis;
        delete results._intersection_analysis;
    }
    if (results._intersection) {
        intersectionStocks = results._intersection;
        delete results._intersection;
    }
    
    // 提取未选中股票诊断信息（不参布后续渲染和保存）
    let diagnostics = null;
    if (results._diagnostics) {
        diagnostics = results._diagnostics;
        delete results._diagnostics;
    }
    
    // 提取按日期分组结果（日期范围选股模式）
    let byDate = null;
    if (results._by_date) {
        byDate = results._by_date;
        delete results._by_date;
    }
    
    // 重置诊断块状态（避免上一次选股的残留）
    diagState = {};
    
    // 处理交集结果（AND逻辑）
    if (intersectionStocks && Array.isArray(intersectionStocks)) {
        totalCount = intersectionStocks.length;
        html += '<p style="margin-bottom: 16px;"><strong>交集结果：共选出 ' + totalCount + ' 只股票</strong></p>';
        
        if (totalCount === 0) {
            html += '<p class="text-muted">两个策略没有同时选中的股票</p>';
        } else {
            html += intersectionStocks.map(signal => {
                // 验证信号结构
                if (!signal || typeof signal !== 'object') {
                    console.warn('无效的信号结构:', signal);
                    return '';
                }
                
                const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                const strategiesStr = signal.strategies && Array.isArray(signal.strategies) ? signal.strategies.join(' + ') : '';
                const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                
                const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + keyDate + reasons + '</div></div></div>';
            }).join('');
        }
    } else {
        // 处理OR逻辑结果 - 优先显示交集股票
        
        // 显示交集分析（如果有）
        if (intersectionAnalysis && typeof intersectionAnalysis === 'object') {
            const analysisHtml = renderIntersectionAnalysis(intersectionAnalysis);
            if (analysisHtml) {
                html += analysisHtml;
            }
        }
        
        // 构建交集股票集合（用于优先显示）
        const intersectionSet = new Set();
        const byCountMap = (intersectionAnalysis && intersectionAnalysis.by_count) || {};
        
        // 收集所有出现在多个策略中的股票代码
        // by_count 的格式: { '1': [{code, name, ...}, ...], '2': [{code, name, ...}, ...] }
        for (const count in byCountMap) {
            if (parseInt(count) > 1) {  // 只收集被多个策略选中的股票
                const stocks = byCountMap[count];
                if (Array.isArray(stocks)) {
                    stocks.forEach(stock => {
                        if (stock && stock.code) {
                            intersectionSet.add(stock.code);
                        }
                    });
                }
            }
        }
        
        // 处理每个策略的结果
        const strategyEntries = Object.entries(results || {});
        
        if (strategyEntries.length === 0) {
            html += '<p class="text-muted">暂无选股结果</p>';
        } else {
            // 第一步：优先显示交集股票（出现在多个策略中的股票）
            if (intersectionSet.size > 0) {
                // 按交集数量降序排列
                const sortedCounts = Object.keys(byCountMap)
                    .map(Number)
                    .sort((a, b) => b - a);  // 降序排列
                
                // 按交集数量显示股票
                for (const count of sortedCounts) {
                    if (count > 1) {
                        const stocks = byCountMap[count];
                        if (!Array.isArray(stocks) || stocks.length === 0) {
                            continue;
                        }
                        
                        // 收集这个交集数量的所有股票及其策略信息
                        const countStocksMap = {};
                        for (const stock of stocks) {
                            if (stock && stock.code) {
                                countStocksMap[stock.code] = stock;
                            }
                        }
                        
                        // 生成标题：显示被多少个策略同时选中
                        const countTitle = count === 2 ? '被2个策略同时选中' : ('被' + count + '个策略同时选中');
                        html += '<div class="selection-strategy"><h4>⭐ ' + countTitle + ' (' + Object.keys(countStocksMap).length + '只)</h4>';
                        
                        // 显示这个交集数量的所有股票
                        html += Object.values(countStocksMap).map(signal => {
                            if (!signal || typeof signal !== 'object') {
                                console.warn('无效的信号结构:', signal);
                                return '';
                            }
                            
                            const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                            // 使用中文名称显示策略
                            const strategiesStr = signal.strategy_display_names && Array.isArray(signal.strategy_display_names) ? signal.strategy_display_names.join(' + ') : '';
                            const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                            
                            const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + keyDate + reasons + '</div></div></div>';
                        }).join('');
                        
                        html += '</div>';
                        totalCount += Object.keys(countStocksMap).length;
                    }
                }
            }
            
            // 第二步：显示单个策略的股票（被1个策略选中的股票）
            if (byCountMap[1] && Array.isArray(byCountMap[1]) && byCountMap[1].length > 0) {
                const singleStrategyStocks = byCountMap[1];
                
                // 按策略分组股票
                const stocksByStrategy = {};
                for (const stock of singleStrategyStocks) {
                    if (stock && stock.code) {
                        // 获取策略名称
                        const strategyName = stock.strategy_display_names && Array.isArray(stock.strategy_display_names) ? 
                                           stock.strategy_display_names[0] : 
                                           (stock.strategies && Array.isArray(stock.strategies) ? stock.strategies[0] : '未知策略');
                        
                        if (!stocksByStrategy[strategyName]) {
                            stocksByStrategy[strategyName] = [];
                        }
                        stocksByStrategy[strategyName].push(stock);
                    }
                }
                
                // 按策略分组显示
                for (const [strategyName, stocks] of Object.entries(stocksByStrategy)) {
                    if (stocks.length > 0) {
                        totalCount += stocks.length;
                        html += '<div class="selection-strategy"><h4>' + strategyName + ' (' + stocks.length + '只)</h4>';
                        
                        // 显示这个策略的所有股票
                        html += stocks.map(signal => {
                            if (!signal || typeof signal !== 'object') {
                                console.warn('无效的信号结构:', signal);
                                return '';
                            }
                            
                            const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                            // 使用中文名称显示策略
                            const strategiesStr = signal.strategy_display_names && Array.isArray(signal.strategy_display_names) ? signal.strategy_display_names.join(' + ') : '';
                            const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                            
                            const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategiesStr + '</span>' + keyDate + reasons + '</div></div></div>';
                        }).join('');
                        
                        html += '</div>';
                    }
                }
            } else if (strategyEntries.length > 0) {
                // 兜底逻辑：当没有交集分析数据时，直接遍历策略结果显示股票
                for (const [strategyName, signals] of strategyEntries) {
                    if (Array.isArray(signals) && signals.length > 0) {
                        // 尝试获取策略的中文名称
                        let strategyDisplayName = strategyName;
                        // 简单的策略名称映射，实际项目中可能需要从配置或API获取
                        const strategyNameMap = {
                            'TrendAccelerationInflectionStrategy': '趋势加速拐点',
                            'TrendReversalStrategy': '趋势共振反转策略',
                            'ResistanceBreakoutStrategy': '阻力位突破策略',
                            'WBottomStrategy': 'W底策略',
                            'MultiGoldenCrossStrategy': '多金叉共振策略',
                            'MorningStarStrategy': '启明星策略',
                            'MultiPartyCannonStrategy': '多方炮策略',
                            'MultiDeathCrossStrategy': '多死叉共振策略',
                            'MHeadStrategy': 'M头策略',
                            'StrongWashWeakToStrongStrategy': '强势洗盘弱转强策略',
                            'LimitUpPullbackStrategy': '涨停回马枪策略',
                            'LimitUpSidewaysStrategy': '涨停横盘策略',
                            'TrendStartStrategy': '趋势起点策略'
                        };
                        if (strategyNameMap[strategyName]) {
                            strategyDisplayName = strategyNameMap[strategyName];
                        }
                        
                        html += '<div class="selection-strategy"><h4>' + strategyDisplayName + ' (' + signals.length + '只)</h4>';
                        
                        html += signals.map(signal => {
                            if (!signal || typeof signal !== 'object') {
                                console.warn('无效的信号结构:', signal);
                                return '';
                            }
                            
                            const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
                            const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + r + '</span>').join('') : '';
                            
                            const keyDate = s.key_date ? '<span class="tag">' + s.key_date_type + ': ' + s.key_date + '</span>' : '';
                            return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + signal.code + '\')" class="stock-link">' + signal.code + ' ' + signal.name + '</a></span><div class="signal-tags"><span class="tag">' + strategyDisplayName + '</span>' + keyDate + reasons + '</div></div></div>';
                        }).join('');
                        
                        html += '</div>';
                        totalCount += signals.length;
                    }
                }
            }
            
            // 添加总数统计
            if (totalCount > 0) {
                html = '<p style="margin-bottom: 16px;"><strong>共选出 ' + totalCount + ' 只股票</strong></p>' + html;
            }
        }
    }
    
    // 如果没有生成任何HTML，根据过滤统计信息决定是否显示提示
    if (!html) {
        // 检查是否有过滤统计信息且显示有股票
        const hasFilterStats = filterStats && filterStats.enabled && 
                              (filterStats.total_before > 0 || filterStats.total_after > 0 || filterStats.filtered_out > 0);
        
        if (!hasFilterStats) {
            html = '<p class="text-muted">暂无选股结果</p>';
        }
    }
    
    // 追加未选中股票诊断区域
    if (diagnostics) {
        html += renderSelectionDiagnostics(diagnostics);
    }
    
    // 追加按日期分组展示区域（日期范围选股模式）
    if (byDate) {
        html += renderByDateSections(byDate);
    }
    
    container.innerHTML = html;
    
    // 渲染诊断区域的表格内容（需在 innerHTML 之后执行）
    initDiagnosticsTables();
    
    // 显示过滤统计信息
    if (filterStats && filterStats.enabled) {
        const filterHtml = `
            <div class="filter-stats-section">
                <h3>过滤统计</h3>
                <p>过滤前: ${filterStats.total_before} 只</p>
                <p>过滤后: ${filterStats.total_after} 只</p>
                <p>被过滤: ${filterStats.filtered_out} 只</p>
                <h4>过滤条件统计</h4>
                <ul>
                    ${Object.entries(filterStats.filters_applied || {}).map(([filter, count]) => {
                        if (count > 0) {
                            return `<li>${filter}: ${count} 只</li>`;
                        }
                        return '';
                    }).join('')}
                </ul>
                ${filterStats.filtered_stocks && filterStats.filtered_stocks.length > 0 ? `
                    <h4>被过滤的股票</h4>
                    <div class="filtered-stocks-list">
                        ${filterStats.filtered_stocks.map(stock => {
                            return `
                                <div class="filtered-stock-item">
                                    <span class="stock-code">${stock.code} ${stock.name}</span>
                                    <span class="stock-reason">${stock.reason}</span>
                                </div>
                            `;
                        }).join('')}
                    </div>
                ` : ''}
            </div>
        `;
        
        // 添加到容器的末尾
        container.insertAdjacentHTML('beforeend', filterHtml);
    }
}


// ==================== 未选中股票诊断区域 ====================

// 诊断块状态（模块级缓存），key 为块ID（支持按日期前缀区分多个块）
let diagState = {};  // key -> { reason, search, page, data }
const DIAG_PAGE_SIZE = 50;

/**
 * HTML转义，防止名称中的特殊字符破坏页面
 */
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * 渲染未选中股票诊断区域（每个策略一个折叠块）
 * @param {Object} diagnostics - 诊断数据 {策略中文名: {total_analyzed, selected, rejected_count, reason_stats, rejected}}
 * @param {string} keyPrefix - 块ID前缀（按日期展示时用于区分不同日期的块）
 */
export function renderSelectionDiagnostics(diagnostics, keyPrefix = '') {
    const keys = Object.keys(diagnostics);
    if (keys.length === 0) return '';

    // 无前缀（单日模式）时显示标题；按日期嵌套时省略标题
    let html = keyPrefix === '' ? '<div class="diag-section"><h3 style="margin: 24px 0 12px;">🔍 未选中股票诊断</h3>' : '';

    keys.forEach((strategyName, i) => {
        const diag = diagnostics[strategyName];
        const key = keyPrefix + 'diag_' + i;
        diagState[key] = { reason: null, search: '', page: 1, data: diag };

        // 原因统计 chips（按数量降序）
        const reasonStats = diag.reason_stats || {};
        const sortedReasons = Object.entries(reasonStats).sort((a, b) => b[1] - a[1]);
        const chipsHtml = sortedReasons.map(([reason, count]) => {
            return '<span class="diag-reason-chip" data-key="' + key + '" data-reason="' + escapeHtml(reason) + '" onclick="toggleDiagReasonFilter(this)">'
                + escapeHtml(reason) + ' <b>(' + count + ')</b></span>';
        }).join('');

        html += `
            <details class="diag-block" id="${key}-block">
                <summary>
                    <strong>${escapeHtml(strategyName)}</strong>
                    — 共分析 ${diag.total_analyzed} 只，选中 <span style="color:#16a34a">${diag.selected}</span> 只，
                    未选中 <span style="color:#dc2626">${diag.rejected_count}</span> 只（点击展开）
                </summary>`;
        html += `
                <div class="diag-content">
                    <div class="diag-chips">
                        <span style="font-size:13px;color:#6b7280;">原因统计（点击筛选）:</span>
                        ${chipsHtml}
                    </div>
                    <div class="diag-toolbar">
                        <input type="text" class="diag-search" id="${key}-search" placeholder="搜索代码/名称..."
                               oninput="onDiagSearch('${key}', this.value)">
                        <span class="diag-count" id="${key}-count"></span>
                    </div>
                    <table class="diag-table">
                        <thead>
                            <tr><th style="width:100px;">代码</th><th style="width:140px;">名称</th><th>未满足原因</th></tr>
                        </thead>
                        <tbody id="${key}-tbody"></tbody>
                    </table>
                    <div class="diag-pagination" id="${key}-pagination"></div>
                </div>
            </details>`;
    });

    if (keyPrefix === '') html += '</div>';
    return html;
}

/**
 * 在 innerHTML 渲染后初始化所有诊断表格
 */
export function initDiagnosticsTables() {
    Object.keys(diagState).forEach(key => {
        renderDiagTable(key);
    });
}

/**
 * 获取诊断数据（按 key 找到对应块的数据）
 */
function getDiagByKey(key) {
    const state = diagState[key];
    return state ? state.data : null;
}

/**
 * 将原因文本归一化为类别（与后端 reason_stats 的归类逻辑一致）
 */
function normalizeDiagReason(reason) {
    return (reason || '').split('（')[0].split('，')[0].replace(/(?<![A-Za-z0-9])\d+\.?\d*/g, 'N');
}

/**
 * 获取过滤后的未选中股票列表
 */
function getFilteredRejected(key) {
    const diag = getDiagByKey(key);
    if (!diag || !Array.isArray(diag.rejected)) return [];
    const state = diagState[key];
    let list = diag.rejected;

    if (state.reason) {
        // 原因统计分类是归一化后的类别，按类别匹配
        list = list.filter(item => normalizeDiagReason(item.reason) === state.reason);
    }
    if (state.search) {
        const q = state.search.toLowerCase();
        list = list.filter(item =>
            (item.code || '').toLowerCase().includes(q) ||
            (item.name || '').toLowerCase().includes(q)
        );
    }
    return list;
}

/**
 * 渲染某个策略的诊断表格（当前页）
 */
function renderDiagTable(key) {
    const tbody = document.getElementById(key + '-tbody');
    const countEl = document.getElementById(key + '-count');
    const paginationEl = document.getElementById(key + '-pagination');
    if (!tbody) return;

    const state = diagState[key];
    const list = getFilteredRejected(key);
    const totalPages = Math.max(1, Math.ceil(list.length / DIAG_PAGE_SIZE));
    if (state.page > totalPages) state.page = totalPages;

    const start = (state.page - 1) * DIAG_PAGE_SIZE;
    const pageItems = list.slice(start, start + DIAG_PAGE_SIZE);

    tbody.innerHTML = pageItems.map(item => `
        <tr>
            <td>${escapeHtml(item.code)}</td>
            <td><a href="javascript:void(0)" onclick="viewStockDetail('${escapeHtml(item.code)}')" class="stock-link">${escapeHtml(item.name)}</a></td>
            <td class="diag-reason-cell">${escapeHtml(item.reason)}</td>
        </tr>
    `).join('') || '<tr><td colspan="3" style="text-align:center;color:#9ca3af;">无匹配数据</td></tr>';

    if (countEl) {
        countEl.textContent = '共 ' + list.length + ' 只';
    }

    // 分页控件
    if (paginationEl) {
        if (totalPages <= 1) {
            paginationEl.innerHTML = '';
        } else {
            paginationEl.innerHTML = `
                <button class="diag-page-btn" ${state.page <= 1 ? 'disabled' : ''} onclick="gotoDiagPage('${key}', ${state.page - 1})">上一页</button>
                <span style="margin: 0 10px;">${state.page} / ${totalPages}</span>
                <button class="diag-page-btn" ${state.page >= totalPages ? 'disabled' : ''} onclick="gotoDiagPage('${key}', ${state.page + 1})">下一页</button>`;
        }
    }
}

/**
 * 翻页
 */
export function gotoDiagPage(key, page) {
    if (!diagState[key]) return;
    diagState[key].page = page;
    renderDiagTable(key);
}

/**
 * 搜索
 */
export function onDiagSearch(key, value) {
    if (!diagState[key]) return;
    diagState[key].search = (value || '').trim();
    diagState[key].page = 1;
    renderDiagTable(key);
}

/**
 * 点击原因 chip 切换筛选
 */
export function toggleDiagReasonFilter(chipEl) {
    const key = chipEl.getAttribute('data-key');
    const reason = chipEl.getAttribute('data-reason');
    if (!diagState[key]) return;

    const block = document.getElementById(key + '-block');
    if (diagState[key].reason === reason) {
        // 再次点击取消筛选
        diagState[key].reason = null;
        if (block) {
            block.querySelectorAll('.diag-reason-chip').forEach(c => c.classList.remove('active'));
        }
    } else {
        diagState[key].reason = reason;
        if (block) {
            block.querySelectorAll('.diag-reason-chip').forEach(c => {
                c.classList.toggle('active', c.getAttribute('data-reason') === reason);
            });
        }
    }
    diagState[key].page = 1;
    renderDiagTable(key);
}


// ==================== 按日期分组展示（日期范围选股） ====================

/**
 * 渲染按日期分组的选股结果
 * @param {Object} byDate - { 'YYYY-MM-DD': { '策略中文名': [signals], '_diagnostics': {...} } }
 */
export function renderByDateSections(byDate) {
    const dates = Object.keys(byDate).sort().reverse();  // 最新日期在前
    if (dates.length === 0) return '';

    let html = '<div class="diag-section"><h3 style="margin: 24px 0 12px;">📅 按日期展示（共 ' + dates.length + ' 个交易日）</h3>';

    dates.forEach(date => {
        const dayData = byDate[date] || {};
        let total = 0;
        let inner = '';
        let dayDiag = null;

        for (const [strategyName, signals] of Object.entries(dayData)) {
            if (strategyName === '_diagnostics') {
                dayDiag = signals;
                continue;
            }
            if (Array.isArray(signals)) {
                total += signals.length;
                inner += renderDayStrategyBlock(strategyName, signals);
            }
        }

        if (!inner) {
            inner = '<p class="text-muted" style="margin: 8px 0;">当日无选中股票</p>';
        }

        // 当日诊断（未选中股票及原因）
        if (dayDiag) {
            const keyPrefix = 'd' + date.replace(/-/g, '') + '_';
            inner += renderSelectionDiagnostics(dayDiag, keyPrefix);
        }

        html += '<details class="diag-block">'
            + '<summary><strong>' + escapeHtml(date) + '</strong> — 选中 <span style="color:#16a34a">' + total + '</span> 只（点击展开）</summary>'
            + '<div class="diag-content">' + inner + '</div>'
            + '</details>';
    });

    html += '</div>';
    return html;
}

/**
 * 渲染某日某策略的选股结果卡片
 */
function renderDayStrategyBlock(strategyName, signals) {
    if (!Array.isArray(signals) || signals.length === 0) return '';

    let html = '<div class="selection-strategy" style="margin-top: 8px;"><h4>' + escapeHtml(strategyName) + ' (' + signals.length + '只)</h4>';

    html += signals.map(signal => {
        if (!signal || typeof signal !== 'object') return '';
        const s = signal.signals && Array.isArray(signal.signals) && signal.signals[0] ? signal.signals[0] : {};
        const reasons = s.reasons && Array.isArray(s.reasons) ? s.reasons.map(r => '<span class="tag">' + escapeHtml(r) + '</span>').join('') : '';
        const keyDate = s.key_date ? '<span class="tag">' + escapeHtml(s.key_date_type || '') + ': ' + escapeHtml(s.key_date) + '</span>' : '';
        return '<div class="signal-card"><div class="signal-header"><span class="signal-title"><a href="javascript:void(0)" onclick="viewStockDetail(\'' + escapeHtml(signal.code) + '\')" class="stock-link">' + escapeHtml(signal.code) + ' ' + escapeHtml(signal.name) + '</a></span><div class="signal-tags">' + keyDate + reasons + '</div></div></div>';
    }).join('');

    html += '</div>';
    return html;
}

// 页面加载后自动恢复未完成的选股任务（如果有），完成后自动显示结果，无需手动刷新
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => resumePendingSelection());
} else {
    resumePendingSelection();
}
