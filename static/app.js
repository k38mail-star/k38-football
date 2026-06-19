/**
 * K38 Football — Ultimate Frontend Framework v3.0
 * Modern, Fast, Elegant
 */

const K38 = (() => {
    'use strict';

    // ═══ Utilities ═══
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));

    const hasChinese = value => /[一-鿿]/.test(String(value || ''));

    // ═══ API Layer ═══
    const jsonFetch = async (url, options = {}) => {
        const timeout = options.timeout || 30000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        try {
            const resp = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    ...options.headers
                }
            });

            clearTimeout(timeoutId);

            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                throw new Error(data.error || `请求失败 (${resp.status})`);
            }

            return await resp.json();
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('请求超时，请稍后重试');
            }
            throw error;
        }
    };

    // ═══ Status Management ═══
    const setStatus = (isMock, text, tone) => {
        const dot = document.getElementById('statusDot');
        const label = document.getElementById('statusText');
        if (dot) dot.className = 'status-indicator ' + (tone || (isMock ? 'mock' : 'online'));
        if (label) label.textContent = text || (isMock ? '模拟模式' : '在线');
    };

    // ═══ UI Components ═══
    const skeleton = (count = 4) => `
        <div class="skeleton-stack">
            ${Array.from({ length: count }, () => `
                <div class="skeleton-card">
                    <span></span><strong></strong><i></i>
                </div>
            `).join('')}
        </div>
    `;

    const empty = (text, icon = '⚽') => `
        <div class="empty-state">
            <span class="empty-icon">${icon}</span>
            <span>${esc(text)}</span>
        </div>
    `;

    const pagination = (meta = {}, onClickName = 'loadPage') => {
        if (!meta.pages || meta.pages <= 1) return '';
        const page = Number(meta.page || 1);
        const pages = Number(meta.pages || 1);
        return `
            <div class="pagination">
                <button type="button" ${meta.has_prev ? '' : 'disabled'} onclick="${onClickName}(${page - 1})">
                    ← 上一页
                </button>
                <span>第 ${page} 页 / 共 ${pages} 页</span>
                <button type="button" ${meta.has_next ? '' : 'disabled'} onclick="${onClickName}(${page + 1})">
                    下一页 →
                </button>
            </div>
        `;
    };

    // ═══ Animations ═══
    const animateIn = (selector, root = document) => {
        requestAnimationFrame(() => {
            const elements = root.querySelectorAll(selector);
            elements.forEach((el, i) => {
                el.style.setProperty('--i', i);
                el.classList.add('animate-in');
            });
        });
    };

    const animateNumber = (element, target, duration = 800) => {
        const start = parseInt(element.textContent) || 0;
        if (start === target) return;

        const startTime = performance.now();
        const animate = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const easeOutQuad = progress * (2 - progress);
            const current = Math.round(start + (target - start) * easeOutQuad);

            element.textContent = current;

            if (progress < 1) {
                requestAnimationFrame(animate);
            }
        };

        requestAnimationFrame(animate);
    };

    // ═══ Date & Time ═══
    const formatTime = value => {
        if (!value) return '待定';
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? '待定' : d.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    const dateKey = value => {
        if (!value) return 'unknown';
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? 'unknown' : d.toISOString().slice(0, 10);
    };

    const dateLabel = key => {
        if (key === 'unknown') return '日期待定';
        const today = new Date().toISOString().slice(0, 10);
        if (key === today) return '📅 今天';

        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        if (key === yesterday.toISOString().slice(0, 10)) return '📅 昨天';

        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        if (key === tomorrow.toISOString().slice(0, 10)) return '📅 明天';

        return new Date(key + 'T00:00:00').toLocaleDateString('zh-CN', {
            month: 'long',
            day: 'numeric',
            weekday: 'short'
        });
    };

    const dateOrder = key => {
        return key === 'unknown' ? 9999999999999 : new Date(key + 'T00:00:00').getTime();
    };

    // ═══ Team Utilities ═══
    const teamName = (match, side, escaped = true) => {
        const flag = match[`${side}_flag`] || '';
        const name = match[`${side}_team_en`] || match[`${side}_team`] || '';
        const value = `${flag ? flag + ' ' : ''}${name}`;
        return escaped ? esc(value) : value;
    };

    const shortTeamName = (match, side) => {
        return match[`${side}_team_en`] || match[`${side}_team`] || '';
    };

    // ═══ Debounce ═══
    const debounce = (func, wait) => {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    };

    // ═══ Public API ═══
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

// ═══ Global Error Handler ═══
window.addEventListener('error', (event) => {
    console.error('全局错误:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('未处理的 Promise 拒绝:', event.reason);
});

// ═══ Performance Monitoring ═══
if ('performance' in window) {
    window.addEventListener('load', () => {
        const perfData = performance.getEntriesByType('navigation')[0];
        console.log('页面加载时间:', Math.round(perfData.loadEventEnd - perfData.fetchStart), 'ms');
    });
}
