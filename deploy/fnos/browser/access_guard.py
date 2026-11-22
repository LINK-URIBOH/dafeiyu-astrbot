"""Read-only DOM observation, not a tool the model can call.

Only an observed, small Bilibili header promotion can be exempted. Forms,
blocking overlays, challenges and unknown page layouts remain fail-closed.
No nodes are removed, clicked or hidden in the live page.
"""

OBSERVE_ACCESS = r"""() => {
    if (!document.body) {
        if (location.href === 'about:blank') return JSON.stringify({text: '', challenge: false});
        throw new Error('Page body unavailable');
    }
    const visible = e => {
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.display !== 'none' &&
            s.visibility !== 'hidden' && s.opacity !== '0' &&
            e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
    };
    const hard = /验证码|安全验证|访问受限|风控验证|verify you are human|captcha/i;
    const vw = innerWidth, vh = innerHeight;
    const blockingOverlay = [...document.querySelectorAll(
        '[role="dialog"], [aria-modal="true"], [class*="mask"], [class*="overlay"], [class*="modal"]'
    )].some(e => {
        if (!visible(e)) return false;
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        return s.pointerEvents !== 'none' &&
            (e.getAttribute('aria-modal') === 'true' ||
             (['fixed', 'absolute'].includes(s.position) &&
              Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) *
              Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0)) >= vw * vh * 0.45));
    });
    const exempt = new Set();
    const unobscured = e => {
        const r = e.getBoundingClientRect();
        const x = (Math.max(0, r.left) + Math.min(vw, r.right)) / 2;
        const y = (Math.max(0, r.top) + Math.min(vh, r.bottom)) / 2;
        return visible(e) && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw &&
            e.contains(document.elementFromPoint(x, y));
    };
    const publicVideoAccessible = [...document.querySelectorAll('a[href*="/video/"]')].some(unobscured);
    // An ordinary header login link is not an access requirement.
    if (!blockingOverlay) {
        for (const e of document.querySelectorAll('header a, header button, nav a, nav button')) {
            const r = e.getBoundingClientRect();
            if (unobscured(e) && r.top >= 0 && r.bottom < vh * 0.35 &&
                !e.closest('form, [role="dialog"], [aria-modal="true"]') &&
                !hard.test(e.innerText || '')) exempt.add(e);
        }
    }
    if (['www.bilibili.com', 'bilibili.com'].includes(location.hostname) && !blockingOverlay && publicVideoAccessible) {
        for (const e of document.querySelectorAll('.header-avatar-unlogin-wrap .login-panel-popover')) {
            const r = e.getBoundingClientRect();
            if (visible(e) && r.top >= 0 && r.top < vh * 0.35 && r.left >= vw * 0.5 &&
                r.width <= Math.min(500, vw * 0.5) && r.height <= 400 &&
                r.width * r.height < vw * vh * 0.18 &&
                !e.closest('form, [role="dialog"], [aria-modal="true"]') &&
                !e.querySelector('input, form, iframe, canvas, img, [role="dialog"], [aria-modal="true"]') &&
                !hard.test(e.innerText || '')) exempt.add(e);
        }
    }
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const parts = [];
    while (walker.nextNode()) {
        const n = walker.currentNode, p = n.parentElement;
        if (!p || !n.textContent.trim() || p.closest('script, style, noscript') || !visible(p)) continue;
        let ignored = false;
        for (const e of exempt) if (e.contains(p)) { ignored = true; break; }
        if (!ignored) parts.push(n.textContent.trim());
    }
    // Image/iframe-based challenges may have no extractable text.
    const challenge = [...document.querySelectorAll(
        'iframe[src*="captcha"], iframe[src*="geetest"], [class*="captcha"], [id*="captcha"], ' +
        '.geetest_panel, .geetest_box, [class*="geetest_holder"], input[type="password"], ' +
        'input[autocomplete="one-time-code"], [class*="login"] canvas, ' +
        '[class*="login"] img[alt*="二维码"], iframe[src*="passport.bilibili.com"]'
    )].some(visible);
    return JSON.stringify({text: parts.join('\n'), challenge});
}"""
