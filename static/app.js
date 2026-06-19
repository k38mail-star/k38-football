const K38 = (() => {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));

    const jsonFetch = async url => {
        const resp = await fetch(url);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
        return data;
    };

    const setStatus = (isMock, text, tone) => {
        const dot = document.getElementById('statusDot');
        const label = document.getElementById('statusText');
        if (dot) dot.className = 'status-indicator ' + (tone || (isMock ? 'mock' : 'online'));
        if (label) label.textContent = text || (isMock ? '实时' : '在线');
    };

    const skeleton = (count = 4, type = 'card') => `
        <div class="skeleton-stack">
            ${Array.from({ length: count }, () => `
                <div class="skeleton-card ${type}">
                    <span></span><strong></strong><i></i>
                </div>
            `).join('')}
        </div>
    `;

    const empty = (text, icon = '📭') => `<div class="empty-state"><span class="empty-icon">${icon}</span><span>${esc(text)}</span></div>`;

    const animateIn = (selector, root = document) => {
        requestAnimationFrame(() => {
            root.querySelectorAll(selector).forEach((el, i) => {
                el.style.setProperty('--i', i);
                el.classList.add('animate-in');
            });
        });
    };

    const pagination = (meta = {}, onClickName = 'loadPage') => {
        if (!meta.pages || meta.pages <= 1) return '';
        const page = Number(meta.page || 1);
        const pages = Number(meta.pages || 1);
        return `
            <div class="pagination">
                <button type="button" ${meta.has_prev ? '' : 'disabled'} onclick="${onClickName}(${page - 1})">上一页</button>
                <span>${page} / ${pages}</span>
                <button type="button" ${meta.has_next ? '' : 'disabled'} onclick="${onClickName}(${page + 1})">下一页</button>
            </div>
        `;
    };

    const hasChinese = value => /[\u4e00-\u9fff]/.test(String(value || ''));

    const formatTime = value => {
        if (!value) return '待定';
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? '待定' : d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    };

    const dateKey = value => {
        if (!value) return 'unknown';
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? 'unknown' : d.toISOString().slice(0, 10);
    };

    const dateLabel = key => {
        if (key === 'unknown') return '待定';
        const today = new Date().toISOString().slice(0, 10);
        if (key === today) return '📅 今天';
        const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1);
        if (key === yesterday.toISOString().slice(0, 10)) return '📅 昨天';
        const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
        if (key === tomorrow.toISOString().slice(0, 10)) return '📅 明天';
        return new Date(key + 'T00:00:00').toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' });
    };

    const dateOrder = key => key === 'unknown' ? 9999999999999 : new Date(key + 'T00:00:00').getTime();

    const teamName = (match, side, escaped = true) => {
        const flag = match[`${side}_flag`] || '';
        const name = match[`${side}_team_en`] || match[`${side}_team`] || '';
        const value = `${flag ? flag + ' ' : ''}${name}`;
        return escaped ? esc(value) : value;
    };

    const shortTeamName = (match, side) => match[`${side}_team_en`] || match[`${side}_team`] || '';

    return {
        animateIn, dateKey, dateLabel, dateOrder, empty, esc, formatTime,
        hasChinese, jsonFetch, pagination, setStatus, shortTeamName, skeleton, teamName
    };
})();
