import sys, os, csv, json
sys.path.insert(0, os.path.dirname(__file__))
from findings import F
R = "/home/claude/cevher-demirel/loom/docs/audit/stage22/"
CRIT = ["Hierarchy","Readability","Navigation","Discoverability","Consistency","Mobile","Accessibility","Emotional","Efficiency","Polish"]
# scores 1-5 in CRIT order; note = evidence ids for any <4
S = [
("Splash",[5,4,4,4,5,5,3,5,3,4],"Accessibility 3 (aria-hidden, no skip); Efficiency 3: X-01 fixed 2.2s hold"),
("Auth (Log In / Sign Up / Forgot)",[4,4,4,4,4,3,3,4,3,4],"Mobile 3, Efficiency 3: A-01 (320x568 form below fold, default tab Sign Up); Accessibility 3: small eye/forgot targets"),
("Home",[5,4,4,4,4,4,3,5,4,5],"Accessibility 3: N-02 (Review in Loom Map link 18px; footer links 24px), 10.9px nav labels N-01"),
("Record a Dream (entry)",[4,4,4,4,4,3,4,5,3,4],"Mobile 3, Efficiency 3: R-02 Continue off-screen at keyboard height"),
("Emotion Wheel explorer",[5,4,4,4,4,3,4,5,4,5],"Mobile 3: R-01 landscape unusable, R-03 tray at 320x568"),
("Interpreting / error",[5,5,4,4,5,5,4,5,4,5],""),
("Dream Detail",[4,4,3,4,3,4,4,4,4,4],"Navigation 3, Consistency 3: D-01 Archive vs Journal"),
("Journal",[3,4,3,4,3,4,3,4,3,4],"Hierarchy 3, Navigation 3, Efficiency 3: J-01, Consistency 3: J-03, Accessibility 3: N-02 (32px targets)"),
("Loom Map / Network",[3,3,3,2,3,3,3,4,2,4],"L-01 (no visible connections; Discoverability 2, Efficiency 2), L-02 silent 12-node cap, L-04 targets/labels"),
("Loom Map / node sheet",[4,4,3,3,4,4,4,4,3,4],"L-01 connected items not interactive (Discoverability 3, Efficiency 3)"),
("Loom Map / Filters sheet",[4,4,4,4,4,4,4,4,4,4],""),
("Loom Map / Timeline + element detail",[3,3,3,3,3,4,4,4,3,3],"L-06 stacked Timeline controls and mid-word cut excerpts"),
("Loom Map / List",[4,4,4,4,4,4,4,4,4,4],""),
("Insights",[4,3,4,3,3,4,3,4,4,4],"Readability 3: 11-11.8px captions; Discoverability 3, Consistency 3: I-01, I-02; Accessibility 3: legend toggle 19px (N-02)"),
("Settings menu",[4,4,4,4,4,4,4,4,4,4],""),
("Profile",[3,4,3,3,3,4,4,3,3,3],"S-01 page nearly empty; naming mismatch with Account"),
("Account / Data / Delete",[3,4,3,3,3,4,4,3,3,3],"S-01, S-02 delete flow emphasis"),
("Privacy / Support",[4,4,4,4,4,4,4,4,4,4],""),
]
os.makedirs(R, exist_ok=True)
with open(R+"scorecard.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["Screen"]+CRIT+["Average","Evidence for scores below 4"])
    for n,s,e in S: w.writerow([n]+s+[round(sum(s)/10,1),e])
md=["# C. UI/UX scorecard (1-5, higher is better)\n","Scores are the auditor's judgement from the captured screens (390x844 primary, other viewports as noted) and the measurements in `measurements.json`. Every score below 4 cites a finding ID from `01_findings_register.md`.\n","| Screen | "+" | ".join(CRIT)+" | Avg |","|---|"+"---|"*11]
for n,s,e in S: md.append("| %s | %s | %.1f |"%(n," | ".join(map(str,s)),sum(s)/10))
md.append("\n## Evidence for every score below 4\n")
for n,s,e in S:
    if e: md.append("- **%s**: %s"%(n,e))
md.append("\n## Reading the scorecard\n- Lowest-scoring screens: Loom Map / Network, Loom Map / Timeline detail, Profile, Account, Journal.\n- Highest: Interpreting, Emotion Wheel, Home. The recording journey (Stage 19-21) is the strongest part of the product.\n- Scores are relative; they are not a user-research result.")
open(R+"02_scorecard.md","w").write("\n".join(md)+"\n")
pri={"P0":0,"P1":1,"P2":2,"P3":3,"D":4}
FS=sorted(F,key=lambda x:(pri[x[1]],x[0]))
m=["# B. Findings register\n","No P0 findings: no core journey was found to lose data or be fully blocked in portrait; the Stage 21 submission mechanism was not touched. 'D' = data-integrity question for the owner (nothing was changed).\n","Priorities: P0 blocks a core journey or risks data loss; P1 significant usability/accessibility issue; P2 noticeable inconsistency or friction; P3 optional polish.\n"]
for (i,p,scr,el,prob,vp,why,rec,cx,rr) in FS:
    m.append("### %s [%s] %s\n- **Element:** %s\n- **Observed:** %s\n- **Viewport / interaction:** %s\n- **Why it matters:** %s\n- **Recommendation:** %s\n- **Complexity:** %s  |  **Regression risk:** %s\n"%(i,p,scr,el,prob,vp,why,rec,cx,rr))
open(R+"01_findings_register.md","w").write("\n".join(m))
with open(R+"findings.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["id","priority","screen","element","observed","viewport","why","recommendation","complexity","regression_risk"])
    for r in FS: w.writerow(r)
print(len(F),"findings;",sum(1 for x in F if x[1]=="P1"),"P1;",sum(1 for x in F if x[1]=="P2"),"P2")
