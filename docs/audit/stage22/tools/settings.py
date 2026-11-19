import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import capture as C
from capture import make, S, settle, seed, VPS, sync_playwright, INDEX
def gear(pg): pg.evaluate("document.querySelector('.header-gear-btn, .side-nav-btn--gear').click()"); settle(pg, 900)
def row(pg, label):
    pg.evaluate("(l)=>{const b=[...document.querySelectorAll('#panel-profile button, #panel-profile a')].find(x=>x.textContent.trim().startsWith(l));b.click()}", label); settle(pg, 900)
with sync_playwright() as p:
    b = p.chromium.launch()
    for (w, h) in VPS:
        for label, name in (("Profile", "profile_form"), ("Account", "account_data"), ("Privacy", "privacy_notice"), ("Support", "support")):
            ctx, pg, st = make(b, w, h, dreams=seed.dreams(5))
            try:
                gear(pg); row(pg, label); S(pg, "09_settings", name, w, h)
                if label == "Account":
                    S(pg, "09_settings", name + "_full", w, h, True)
                    pg.evaluate("document.getElementById('delete-account-btn').click()"); settle(pg, 700); S(pg, "09_settings", "delete_confirm", w, h)
            except Exception as e: C.LOG.append("FAILED %s %dx%d %s" % (name, w, h, str(e).splitlines()[0][:100]))
            ctx.close()
        c2 = b.new_context(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True); p2 = c2.new_page()
        p2.route("**://loom-phas.onrender.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body="{}"))
        try:
            p2.goto(INDEX); p2.wait_for_timeout(3500)
            p2.evaluate("(()=>{const b=[...document.querySelectorAll('#auth-shell button')].find(x=>x.textContent.trim()==='Log In');b.click()})()"); p2.wait_for_timeout(700); S(p2, "10_auth", "login", w, h)
            p2.evaluate("(()=>{const b=document.querySelector('.auth-forgot-link');b.click()})()"); p2.wait_for_timeout(700); S(p2, "10_auth", "forgot", w, h)
            p2.evaluate("(()=>{const b=[...document.querySelectorAll('#auth-shell button')].find(x=>x.textContent.trim()==='Sign Up');b.click()})()"); p2.wait_for_timeout(500)
            p2.fill("#auth-panel-signup input >> nth=0", "ab"); p2.evaluate("(()=>{const b=[...document.querySelectorAll('#auth-panel-signup button')].find(x=>/create account/i.test(x.textContent));b&&b.click()})()"); p2.wait_for_timeout(700); S(p2, "10_auth", "signup_validation", w, h)
        except Exception as e: C.LOG.append("FAILED auth %dx%d %s" % (w, h, str(e).splitlines()[0][:100]))
        c2.close()
    b.close()
print([l for l in C.LOG if l.startswith("FAILED")], len(C.LOG))
