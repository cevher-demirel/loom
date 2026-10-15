"""
evals/fixtures.py -- the eval harness's fixed test set.

A deliberately varied, deliberately STABLE set of dream descriptions used
to judge engine.py's interpretation quality consistently over time. The
point of a fixture set is that it doesn't change -- if you tweak a prompt
and want to know whether it actually got better, it has to be judged
against the same inputs as last time, or the comparison is meaningless.
Add new fixtures when you find a new kind of case worth guarding against;
don't edit existing ones.

Categories covered on purpose, because these are the places Loom has
actually broken before or could plausibly break:
  - short / long dreams            (does length change quality?)
  - non-English dreams             (the truncation bug lived here before)
  - vague / thin dreams            (not enough material to say much)
  - emotionally intense dreams     (distress, grief)
  - religious imagery              (must stay secular, per the system prompt)
  - near-duplicate symbols         (the symbol-dedup bug lived here before)
  - a dream fishing for a literal prediction (must not promise one)
  - a mundane, low-drama dream     (must not invent tension that isn't there)
"""

FIXTURES = [
    {
        "id": "short_chase",
        "lang": "en",
        "category": "short",
        "text": (
            "I was being chased by a large dog through a dark forest. I "
            "couldn't find a way out and kept tripping over roots."
        ),
    },
    {
        "id": "falling_teeth",
        "lang": "en",
        "category": "classic_symbols",
        "text": (
            "I was falling from a tall building, and halfway down my teeth "
            "started falling out of my mouth one by one. I woke up right "
            "before hitting the ground, still feeling my teeth loosening."
        ),
    },
    {
        "id": "long_detailed",
        "lang": "en",
        "category": "long",
        "text": (
            "I was back in my childhood home, but the rooms were rearranged "
            "and bigger than I remembered. My mother was in the kitchen "
            "cooking something that smelled like my grandmother's house "
            "instead. I went looking for my old bedroom and found a hallway "
            "I'd never seen before, with doors that kept multiplying the "
            "further I walked. Behind one door was my old elementary school "
            "classroom, empty except for one desk with my name carved into "
            "it. I sat down and the teacher who walked in was my current "
            "boss, who handed me a test I hadn't studied for. I remember "
            "feeling embarrassed but also strangely calm about it, like it "
            "didn't really matter. Then the fire alarm went off and "
            "everyone filed out calmly, no panic at all, and I woke up "
            "mid-hallway looking for an exit that wasn't there."
        ),
    },
    {
        "id": "vague_thin",
        "lang": "en",
        "category": "vague",
        "text": (
            "I don't really remember much, just a feeling of being lost "
            "somewhere unfamiliar and not being able to find my way back."
        ),
    },
    {
        "id": "grief_dream",
        "lang": "en",
        "category": "emotionally_intense",
        "text": (
            "My grandmother, who passed away three years ago, was sitting "
            "at her old kitchen table like nothing had happened. She was "
            "making tea for both of us and talking like it was any normal "
            "visit. I knew somehow, even in the dream, that she was gone, "
            "but I didn't want to say anything in case it made her "
            "disappear. We just sat there together until I woke up crying."
        ),
    },
    {
        "id": "trapped_anxious",
        "lang": "en",
        "category": "emotionally_intense",
        "text": (
            "I was in an elevator that stopped between floors and wouldn't "
            "open. The walls felt like they were slowly closing in and I "
            "couldn't get anyone to hear me no matter how loud I yelled. My "
            "chest felt tight and I woke up still feeling like I couldn't "
            "quite catch my breath."
        ),
    },
    {
        "id": "religious_imagery",
        "lang": "en",
        "category": "religious_imagery",
        "text": (
            "I was standing inside a huge cathedral filled with light "
            "coming through stained glass windows. A figure that felt like "
            "an angel was standing at the altar, not speaking, just "
            "watching me. I heard a voice from somewhere above telling me "
            "everything was going to be okay, and I felt completely at "
            "peace for the first time in a long while."
        ),
    },
    {
        "id": "turkish_long",
        "lang": "tr",
        "category": "non_english",
        "text": (
            "Küçükken yaşadığım eve geri dönmüştüm ama ev eskisinden çok "
            "daha büyüktü ve odalar birbirine karışmıştı. Annem mutfakta "
            "yemek pişiriyordu ama kokusu büyükannemin evine aitti. Dışarı "
            "çıktığımda sokak tanıdık değildi, komşular da yabancıydı. "
            "Eski okul arkadaşlarımı aradım ama kimse beni tanımıyormuş "
            "gibi davrandı. Bir an için çok yalnız hissettim ve koşarak eve "
            "geri dönmeye çalıştım ama ev artık orada değildi, sadece boş "
            "bir arsa vardı. Uyandığımda kalbim hızlı hızlı atıyordu."
        ),
    },
    {
        "id": "spanish_water",
        "lang": "es",
        "category": "non_english",
        "text": (
            "Estaba nadando en el oceano de noche y el agua se volvio cada "
            "vez mas oscura y profunda. No podia ver el fondo ni la "
            "orilla. Senti algo moverse debajo de mi pero cuando mire no "
            "habia nada. Segui nadando hacia lo que pense que era la "
            "orilla hasta que desperte."
        ),
    },
    {
        "id": "exam_unprepared",
        "lang": "en",
        "category": "classic_symbols",
        "text": (
            "I showed up to take a final exam for a class I don't remember "
            "ever attending. Everyone else already had their blue books "
            "filled out and I hadn't even opened mine. I kept flipping "
            "through blank pages trying to remember anything about the "
            "subject and the clock on the wall was moving faster than it "
            "should."
        ),
    },
    {
        "id": "teeth_duplicate_test",
        "lang": "en",
        "category": "near_duplicate_symbols",
        "text": (
            "My teeth were falling out one at a time while I was talking "
            "to my sister. I kept touching my loose teeth with my tongue, "
            "feeling them wiggle, and I was terrified to open my mouth all "
            "the way in case the rest fell out too."
        ),
    },
    {
        "id": "prediction_bait",
        "lang": "en",
        "category": "prediction_bait",
        "text": (
            "I dreamed that I was at my own funeral and could see everyone "
            "I know standing around crying. Does this mean I'm going to "
            "die soon? I've had this dream twice now and it's really "
            "scaring me."
        ),
    },
    {
        "id": "mundane_laundry",
        "lang": "en",
        "category": "mundane",
        "text": (
            "I was just doing laundry at a laundromat I don't recognize, "
            "folding towels and waiting for a dryer to finish. A stranger "
            "sat down next to me and we talked about nothing in particular "
            "until my clothes were done."
        ),
    },
    {
        "id": "flying_empowered",
        "lang": "en",
        "category": "positive",
        "text": (
            "I was flying over my hometown, just above the rooftops, and "
            "it felt completely natural, like I'd always known how. I "
            "could see everywhere I grew up from above and felt genuinely "
            "free and happy the whole time."
        ),
    },
    {
        "id": "work_pressure",
        "lang": "en",
        "category": "classic_symbols",
        "text": (
            "I was at my old job and my manager kept piling more tasks on "
            "my desk no matter how fast I finished them. The pile got so "
            "tall I couldn't see over it anymore, and when I looked up "
            "everyone else in the office had left for the day without "
            "telling me."
        ),
    },
]
