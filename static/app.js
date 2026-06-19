/**
 * K38 Football dashboard scripts.
 */

const K38 = (() => {
    'use strict';

    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));

    const hasChinese = value => /[\u4e00-\u9fff]/.test(String(value || ''));

    const jsonFetch = async (url, options = {}) => {
        const timeout = options.timeout || 30000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    ...options.headers
                }
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || `请求失败 (${response.status})`);
            }

            return await response.json();
        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error('请求超时，请稍后重试');
            }
            throw error;
        } finally {
            clearTimeout(timeoutId);
        }
    };

    const setStatus = (isMock, text, tone) => {
        const dot = document.getElementById('statusDot');
        const label = document.getElementById('statusText');
        const statusTone = tone || (isMock ? 'mock' : 'online');
        if (dot) dot.className = `status-indicator ${statusTone}`;
        if (label) label.textContent = text || (isMock ? '模拟模式' : '在线');
    };

    const skeleton = (count = 4) => `
        <div class="skeleton-stack">
            ${Array.from({ length: count }, () => `
                <div class="skeleton-card">
                    <span></span><strong></strong><i></i>
                </div>
            `).join('')}
        </div>
    `;

    const empty = (text, icon = '') => `
        <div class="empty-state">
            ${icon ? `<span class="empty-icon">${esc(icon)}</span>` : ''}
            <span>${esc(text)}</span>
        </div>
    `;

    const pagination = (meta = {}, onClickName = 'loadPage') => {
        const pages = Number(meta.pages || 1);
        if (pages <= 1) return '';

        const page = Number(meta.page || 1);
        const hasPrev = Boolean(meta.has_prev || page > 1);
        const hasNext = Boolean(meta.has_next || page < pages);

        return `
            <div class="pagination">
                <button type="button" ${hasPrev ? '' : 'disabled'} onclick="${onClickName}(${page - 1})">上一页</button>
                <span>第 ${page} 页 / 共 ${pages} 页</span>
                <button type="button" ${hasNext ? '' : 'disabled'} onclick="${onClickName}(${page + 1})">下一页</button>
            </div>
        `;
    };

    const animateIn = (selector, root = document) => {
        requestAnimationFrame(() => {
            root.querySelectorAll(selector).forEach((element, index) => {
                element.style.setProperty('--i', index);
                element.classList.add('animate-in');
            });
        });
    };

    const animateNumber = (element, target, duration = 600) => {
        if (!element) return;
        const start = parseInt(element.textContent, 10) || 0;
        const end = Number(target) || 0;
        if (start === end) return;

        const startTime = performance.now();
        const tick = now => {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = progress * (2 - progress);
            element.textContent = Math.round(start + (end - start) * eased);
            if (progress < 1) requestAnimationFrame(tick);
        };

        requestAnimationFrame(tick);
    };

    const formatTime = value => {
        if (!value) return '待定';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '待定';
        return date.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    const dateKey = value => {
        if (!value) return 'unknown';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? 'unknown' : date.toISOString().slice(0, 10);
    };

    const dateLabel = key => key === 'unknown'
        ? '日期待定'
        : new Date(`${key}T00:00:00`).toLocaleDateString('zh-CN', {
            month: 'long',
            day: 'numeric',
            weekday: 'short'
        });

    const dateOrder = key => key === 'unknown'
        ? Number.MAX_SAFE_INTEGER
        : new Date(`${key}T00:00:00`).getTime();

    const teamName = (match, side, escaped = true) => {
        const flag = match[`${side}_flag`] || '';
        const cn = match[`${side}_team_cn`] || match[`${side}_team`];
        const en = match[`${side}_team_en`] || match[`${side}_team`];
        const name = cn || en || '待定';
        const value = `${flag ? `${flag} ` : ''}${name}`;
        return escaped ? esc(value) : value;
    };

    const shortTeamName = (match, side) => (
        match[`${side}_team_cn`] ||
        match[`${side}_team_en`] ||
        match[`${side}_team`] ||
        '待定'
    );

    const debounce = (func, wait) => {
        let timeout;
        return (...args) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => func(...args), wait);
        };
    };

    return {
        animateIn,
        animateNumber,
        dateKey,
        dateLabel,
        dateOrder,
        debounce,
        empty,
        esc,
        formatTime,
        hasChinese,
        jsonFetch,
        pagination,
        setStatus,
        shortTeamName,
        skeleton,
        teamName
    };
})();

const K38Dashboard = (() => {
    'use strict';

    const state = {
        league: 'all',
        status: 'all',
        season: '2026',
        page: 1,
        loadingSeq: 0
    };

    let els = null;

    const dash = value => value === null || value === undefined || value === '' ? '-' : K38.esc(value);

    const queryElements = () => ({
        app: document.getElementById('k38App'),
        leagueFilters: document.getElementById('leagueFilters'),
        statusFilters: document.getElementById('statusFilters'),
        statusRow: document.getElementById('statusFilterRow'),
        rows: document.getElementById('matchRows'),
        pagination: document.getElementById('pagination'),
        summary: document.getElementById('resultSummary'),
        hotMatches: document.getElementById('hotMatches'),
        hotCount: document.getElementById('hotMatchCount'),
        predictions: document.getElementById('sidePredictions'),
        predictionCount: document.getElementById('predictionCount'),
        metricTotal: document.getElementById('metricTotal'),
        metricLive: document.getElementById('metricLive'),
        metricUpcoming: document.getElementById('metricUpcoming'),
        metricFinished: document.getElementById('metricFinished')
    });

    const hasDashboard = elements => (
        elements.app &&
        elements.leagueFilters &&
        elements.statusFilters &&
        elements.rows &&
        elements.pagination
    );

    const setActive = (container, attr, value) => {
        if (!container) return;
        container.querySelectorAll('.segment').forEach(button => {
            button.classList.toggle('active', button.dataset[attr] === value);
        });
    };

    const apiUrl = () => {
        const params = new URLSearchParams({
            league: state.league,
            status: state.status,
            season: state.season,
            page: state.page
        });
        return `/api/matches?${params.toString()}`;
    };

    const showSkeleton = () => {
        if (els.rows) {
            els.rows.innerHTML = Array.from({ length: 8 }, () => `
                <tr>
                    <td colspan="8" class="table-state">
                        <div class="skeleton-stack">
                            <div class="skeleton-card"><span></span><strong></strong><i></i></div>
                        </div>
                    </td>
                </tr>
            `).join('');
        }
        if (els.summary) els.summary.textContent = '加载中';
        if (els.pagination) els.pagination.innerHTML = '';
    };

    const loadMatches = async () => {
        const seq = ++state.loadingSeq;
        showSkeleton();

        try {
            const data = await K38.jsonFetch(apiUrl());
            if (seq !== state.loadingSeq) return;

            const matches = Array.isArray(data.matches) ? data.matches : [];
            renderMetrics(data.counts || {});
            renderHotMatches(matches);
            renderPredictions(matches);
            renderRows(matches);
            renderPagination(data.pagination || {});
            renderSummary(data);
            K38.setStatus(data.is_mock, data.updated_at ? `更新于 ${data.updated_at}` : '在线', data.is_mock ? 'mock' : 'online');
        } catch (error) {
            if (seq !== state.loadingSeq) return;
            if (els.rows) {
                els.rows.innerHTML = `<tr><td colspan="8" class="table-state">${K38.esc(error.message || '加载失败')}</td></tr>`;
            }
            if (els.summary) els.summary.textContent = '加载失败';
            if (els.pagination) els.pagination.innerHTML = '';
            K38.setStatus(true, '接口异常', 'mock');
        }
    };

    const renderMetrics = counts => {
        K38.animateNumber(els.metricTotal, counts.total || 0);
        K38.animateNumber(els.metricLive, counts.live || 0);
        K38.animateNumber(els.metricUpcoming, counts.upcoming || 0);
        K38.animateNumber(els.metricFinished, counts.finished || 0);
    };

    const renderHotMatches = matches => {
        if (!els.hotMatches || !els.hotCount) return;
        const hot = [...matches]
            .sort((a, b) => Number(a.status_sort || 9) - Number(b.status_sort || 9))
            .slice(0, 4);

        els.hotCount.textContent = `${hot.length} 场`;
        els.hotMatches.innerHTML = hot.length ? hot.map(match => `
            <a class="hot-match" href="${matchUrl(match)}">
                <strong>${teamLine(match, 'home')} vs ${teamLine(match, 'away')}</strong>
                <span>${dash(match.league_name)} · ${scoreText(match)} · ${statusText(match)}</span>
            </a>
        `).join('') : '<div class="table-state">暂无热门比赛</div>';
    };

    const renderPredictions = matches => {
        if (!els.predictions || !els.predictionCount) return;
        const predictions = matches.filter(match => match.prediction).slice(0, 5);

        els.predictionCount.textContent = `${predictions.length} 条`;
        els.predictions.innerHTML = predictions.length ? predictions.map(match => {
            const prediction = match.prediction || {};
            const target = prediction.predicted_winner ||
                prediction.predicted_result ||
                prediction.recommendation ||
                prediction.predicted_score ||
                '查看预测';
            const confidence = percentText(prediction.confidence);

            return `
                <a class="prediction-item" href="${matchUrl(match)}">
                    <strong>${teamLine(match, 'home')} vs ${teamLine(match, 'away')}</strong>
                    <span>${K38.esc(target)}${confidence ? ` · ${confidence}` : ''}</span>
                </a>
            `;
        }).join('') : '<div class="table-state">暂无今日预测</div>';
    };

    const renderRows = matches => {
        if (!els.rows) return;
        if (!matches.length) {
            els.rows.innerHTML = '<tr><td colspan="8" class="table-state">当前筛选暂无比赛</td></tr>';
            return;
        }

        els.rows.innerHTML = matches.map(match => `
            <tr>
                <td>${statusPill(match)}</td>
                <td>${teamCell(match, 'home')}</td>
                <td class="score-cell">${scoreText(match)}</td>
                <td>${teamCell(match, 'away')}</td>
                <td class="odds-cell">${oddsText(match, 'initial')}</td>
                <td class="odds-cell">${oddsText(match, 'live')}</td>
                <td class="possession-cell">${possessionText(match)}</td>
                <td>${predictionLink(match)}</td>
            </tr>
        `).join('');
    };

    const renderPagination = meta => {
        if (els.pagination) els.pagination.innerHTML = K38.pagination(meta, 'loadIndexPage');
    };

    const renderSummary = data => {
        if (!els.summary) return;
        const page = data.pagination || {};
        const total = Number(data.total || page.total || 0);
        els.summary.textContent = total
            ? `共 ${total} 场 · 第 ${page.page || state.page}/${page.pages || 1} 页`
            : '暂无结果';
    };

    const statusPill = match => `<span class="status-pill ${statusType(match)}">${dash(match.emoj)} ${statusText(match)}</span>`;

    const statusType = match => {
        const sort = Number(match.status_sort);
        if (sort === 1 || sort === 2) return 'live';
        if (sort === 3) return 'upcoming';
        if (sort === 4) return 'finished';
        return '';
    };

    const statusText = match => {
        const sort = Number(match.status_sort);
        if (sort === 1 || sort === 2) return K38.esc(match.elapsed ? `${match.elapsed}'` : (match.status || 'LIVE'));
        if (sort === 3) return K38.esc(match.match_date ? K38.formatTime(match.match_date) : (match.status || '未开始'));
        if (sort === 4) return K38.esc(match.status || 'FT');
        return K38.esc(match.status || '待定');
    };

    const teamCell = (match, side) => {
        const cn = match[`${side}_team_cn`] || match[`${side}_team`] || match[`${side}_team_en`] || '待定';
        const en = match[`${side}_team_en`] || match[`${side}_team`] || '';
        const flag = match[`${side}_flag`] || '';

        return `
            <div class="team-cell">
                <strong>${K38.esc(`${flag ? `${flag} ` : ''}${cn}`)}</strong>
                <span>${K38.esc(en && en !== cn ? en : '')}</span>
            </div>
        `;
    };

    const teamLine = (match, side) => K38.esc(
        match[`${side}_team_cn`] ||
        match[`${side}_team_en`] ||
        match[`${side}_team`] ||
        '待定'
    );

    const scoreText = match => {
        if (match.score_display) return K38.esc(match.score_display);
        const home = match.home_goals;
        const away = match.away_goals;
        return home === null || home === undefined || away === null || away === undefined
            ? '-:-'
            : `${K38.esc(home)}:${K38.esc(away)}`;
    };

    const oddsText = (match, kind) => {
        const flatKeys = kind === 'initial'
            ? ['initial_odds', 'opening_odds', 'pre_odds', 'odds_initial']
            : ['live_odds', 'current_odds', 'realtime_odds', 'odds_live'];

        for (const key of flatKeys) {
            if (match[key]) return normalizeOdds(match[key]);
        }

        const odds = match.odds || {};
        const group = odds[kind] || odds[kind === 'initial' ? 'opening' : 'live'] || {};
        return normalizeOdds(group);
    };

    const normalizeOdds = value => {
        if (!value) return '-';
        if (Array.isArray(value)) return value.map(dash).join(' / ');
        if (typeof value === 'object') {
            const ordered = [value.home, value.draw, value.away].filter(item => item !== undefined && item !== null && item !== '');
            if (ordered.length) return ordered.map(dash).join(' / ');
            return Object.values(value).filter(Boolean).map(dash).join(' / ') || '-';
        }
        return dash(value);
    };

    const possessionText = match => {
        const stats = match.stats || {};
        const pairs = [
            [match.home_possession, match.away_possession],
            [stats.home_possession, stats.away_possession],
            [stats['Ball Possession_home'], stats['Ball Possession_away']],
            [stats[`Ball Possession_${match.home_team_id}`], stats[`Ball Possession_${match.away_team_id}`]],
            [stats[`ball_possession_${match.home_team_id}`], stats[`ball_possession_${match.away_team_id}`]]
        ];

        const pair = pairs.find(([home, away]) => hasValue(home) || hasValue(away));
        return pair ? `${dash(pair[0])} / ${dash(pair[1])}` : '-';
    };

    const hasValue = value => value !== null && value !== undefined && value !== '';

    const percentText = value => {
        const number = Number(value);
        if (!Number.isFinite(number)) return '';
        return `${Math.round(number <= 1 ? number * 100 : number)}%`;
    };

    const predictionLink = match => {
        const prediction = match.prediction || match.corner_prediction;
        const label = prediction ? '查看预测' : '预测';
        return `<a class="predict-link" href="${matchUrl(match)}">${label}</a>`;
    };

    const matchUrl = match => `/match/${encodeURIComponent(match.fixture_id || '')}`;

    const bindEvents = () => {
        els.leagueFilters.addEventListener('click', event => {
            const button = event.target.closest('[data-league]');
            if (!button) return;
            state.league = button.dataset.league || 'all';
            state.status = 'all';
            state.page = 1;
            setActive(els.leagueFilters, 'league', state.league);
            setActive(els.statusFilters, 'status', state.status);
            if (els.statusRow) els.statusRow.classList.toggle('is-hidden', state.league === 'all');
            loadMatches();
        });

        els.statusFilters.addEventListener('click', event => {
            const button = event.target.closest('[data-status]');
            if (!button) return;
            state.status = button.dataset.status || 'all';
            state.page = 1;
            setActive(els.statusFilters, 'status', state.status);
            loadMatches();
        });
    };

    const init = () => {
        els = queryElements();
        if (!hasDashboard(els) || document.documentElement.dataset.k38DashboardInit === 'true') return;

        document.documentElement.dataset.k38DashboardInit = 'true';
        state.season = String((window.K38_BOOTSTRAP && window.K38_BOOTSTRAP.season) || state.season);
        bindEvents();
        loadMatches();
    };

    const goToPage = page => {
        state.page = Math.max(1, Number(page || 1));
        loadMatches();
    };

    return { init, goToPage };
})();

window.K38 = K38;
window.K38Dashboard = K38Dashboard;
window.loadIndexPage = page => K38Dashboard.goToPage(page);

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', K38Dashboard.init);
} else {
    K38Dashboard.init();
}

window.addEventListener('error', event => {
    console.error('全局错误:', event.error || event.message);
});

window.addEventListener('unhandledrejection', event => {
    console.error('未处理的 Promise 拒绝:', event.reason);
});
