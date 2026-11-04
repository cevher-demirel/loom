import random
SYMS = [("a key","key"),("water","droplets"),("a door","door"),("flying","wind"),("a house","home"),("a staircase","stairs"),("the ocean","waves"),("a mirror","mirror"),("a snake","snake"),("a forest","trees"),("a train","train"),("teeth","smile"),("a bridge","bridge"),("fire","flame"),("a cat","cat")]
EMO = [("curious","Anticipation"),("afraid","Fear"),("joyful","Joy"),("sad","Sadness"),("angry","Anger"),("trusting","Trust"),("surprised","Surprise"),("disgusted","Disgust")]
PEOPLE = ["my mother","an old friend","a stranger","my sister","a teacher"]
PLACES = ["a hallway","my childhood home","a beach","a city at night","a school"]
THEMES = ["transition","loss","escape","searching","belonging"]
FAMS = ["Joy","Trust","Fear","Surprise","Sadness","Disgust","Anger","Anticipation"]
def dreams(n, seed=7, multi=True):
    r = random.Random(seed); out = []
    for i in range(1, n+1):
        syms = r.sample(SYMS, r.randint(1,3)); emo = r.sample(EMO, r.randint(1,2))
        plut = list({e[1] for e in emo}) + ([r.choice(FAMS)] if multi and r.random() < .4 else [])
        rep = [] if i % 3 == 0 else ["Fear","Worried"] if i % 3 == 1 else ["Joy","Hopeful","Sadness"]
        out.append({"id": i, "timestamp": "2026-%02d-%02dT0%d:00:00Z" % (1 + (i*7) % 10, 1 + (i*3) % 27, 1 + i % 8),
            "raw_text": "I was in %s and %s was there. %s kept turning up, and I felt %s the whole time. " % (r.choice(PLACES), r.choice(PEOPLE), syms[0][0].capitalize(), emo[0][0]) * (1 + i % 3),
            "interpretation": "A reading of this dream about %s.\n\nIt may point toward %s." % (syms[0][0], r.choice(THEMES)),
            "symbols": [s[0] for s in syms], "emotions": [e[0] for e in emo], "emotions_plutchik": plut,
            "people": [r.choice(PEOPLE)] if i % 2 else [], "settings": [r.choice(PLACES)], "themes": [r.choice(THEMES)],
            "symbol_icons": {s[0]: s[1] for s in syms}, "emotions_reported": rep, "conversation": [], "location": ""})
    return out
