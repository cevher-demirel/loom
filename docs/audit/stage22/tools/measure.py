import sys, os, json
sys.path.insert(0, "/home/claude/cevher-demirel/loom"); sys.path.insert(0, os.path.dirname(__file__))
from tests.browser.harness import make, pick_child
from playwright.sync_api import sync_playwright
import seed
JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05 && r.bottom > 0 && r.right > 0 && r.left < innerWidth; };
  const name = e => (e.getAttribute('aria-label') || e.getAttribute('title') || e.textContent || e.getAttribute('placeholder') || '').trim().replace(/\s+/g,' ').slice(0,40);
  const desc = e => (e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + String(e.getAttribute('class')||'').split(' ').filter(Boolean).slice(0,2).join('.'));
  const lum = c => { const a = c.map(v => { v/=255; return v<=.03928? v/12.92 : Math.pow((v+.055)/1.055,2.4)}); return .2126*a[0]+.7152*a[1]+.0722*a[2]; };
  const parse = s => { const m = s.match(/rgba?\(([^)]+)\)/); if(!m) return null; const p = m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; };
  const bgOf = e => { let c = {r:10,g:10,b:26}; const chain=[]; for (let x=e; x; x=x.parentElement) chain.push(x); for (const x of chain.reverse()) { const p = parse(getComputedStyle(x).backgroundColor); if (p && p.a>0) c = {r:c.r*(1-p.a)+p.r*p.a, g:c.g*(1-p.a)+p.g*p.a, b:c.b*(1-p.a)+p.b*p.a}; } return c; };
  const out = {small:[], unnamed:[], tiny:[], lowc:[], overflow: document.documentElement.scrollWidth > innerWidth + 1};
  const inter = [...document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, [role=tab], [role=button]')].filter(vis);
  inter.forEach(e => { const r = e.getBoundingClientRect(); if (Math.min(r.width, r.height) < 44) out.small.push([desc(e), name(e), Math.round(r.width), Math.round(r.height)]); if (!name(e) && !e.querySelector('[aria-label]') && !(e.labels && e.labels.length)) out.unnamed.push(desc(e)); });
  const seen = new Set();
  document.querySelectorAll('body *').forEach(e => { if (!vis(e)) return; const t = [...e.childNodes].filter(n=>n.nodeType===3 && n.textContent.trim()).map(n=>n.textContent.trim()).join(' '); if (!t) return;
    const s = getComputedStyle(e), fs = parseFloat(s.fontSize); if (fs < 12) out.tiny.push([desc(e), t.slice(0,30), fs]);
    const fg = parse(s.color); if (!fg) return; const bg = bgOf(e); const a = fg.a; const f = {r:bg.r*(1-a)+fg.r*a, g:bg.g*(1-a)+fg.g*a, b:bg.b*(1-a)+fg.b*a};
    const L1 = lum([f.r,f.g,f.b]), L2 = lum([bg.r,bg.g,bg.b]); const ratio = (Math.max(L1,L2)+.05)/(Math.min(L1,L2)+.05); const large = fs >= 24 || (fs >= 18.66 && +s.fontWeight >= 700);
    const k = desc(e)+t.slice(0,12); if (ratio < (large?3:4.5) && !seen.has(k)) { seen.add(k); out.lowc.push([desc(e), t.slice(0,30), +ratio.toFixed(2), fs]); } });
  return out;
}
"""
def tab(pg, t):
    pg.evaluate("(t)=>{const b=document.querySelector('.bottom-tab-btn[data-tab=\"'+t+'\"]')||document.querySelector('.side-nav-btn[data-tab=\"'+t+'\"]');b.click()}", t); pg.wait_for_timeout(1000)
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for (w, h) in ((320,568),(390,844),(1280,800)):
        ctx, pg, st = make(b, w, h, dreams=seed.dreams(30))
        def grab(n): res["%s@%dx%d" % (n, w, h)] = pg.evaluate(JS)
        grab("home")
        pg.evaluate("document.getElementById('home-record-btn').click()"); pg.wait_for_timeout(700); grab("record")
        pg.fill("#dream-input", "text"); pg.click("#interpret-btn"); pg.wait_for_selector(".feel-wheel"); pg.wait_for_timeout(700); grab("wheel")
        pick_child(pg, "fear", 0, 0); pg.wait_for_timeout(300); grab("wheel_selected")
        for t, n in (("archive","journal"),("symbols","loom_map"),("patterns","insights")):
            tab(pg, t); grab(n)
        pg.evaluate("document.querySelector('.header-gear-btn, .side-nav-btn--gear').click()"); pg.wait_for_timeout(900); grab("profile")
        ctx.close()
    b.close()
json.dump(res, open("/home/claude/cevher-demirel/loom/docs/audit/stage22/measurements.json", "w"), indent=1)
for k, v in res.items():
    print(k, "overflow" if v["overflow"] else "", "small:", len(v["small"]), "unnamed:", len(v["unnamed"]), "tiny:", len(v["tiny"]), "lowc:", len(v["lowc"]))
