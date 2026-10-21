"""
Loominous -- desktop interface.

A soft, dreamy cloud-sky background sits behind the whole app. The
conversation itself lives in a "frosted glass" panel floating over that
sky, with WhatsApp-style rounded message bubbles -- yours in soft sage
green on the right, Loominous's in warm cream on the left, each timestamped.

Two tabs:
  - "Log a Dream": describe a dream, get it extracted + interpreted, then
    keep the conversation going -- replies continue the same dream thread.
  - "Patterns": ask Loominous to reflect across your whole archive so far.

Run this file directly: python gui.py
Requires background.png to be in the same folder.
"""

import customtkinter as ctk
from PIL import Image, ImageDraw
from tkinter import filedialog
import threading
import shutil
import os
import math
from datetime import datetime

import database
import engine

database.init_db()

ctk.set_appearance_mode("dark")

# ---------- Palette ----------
TEXT_COLOR = "#ece8f5"
MUTED = "#b9aed1"
ACCENT = "#9b8ce0"
ACCENT_HOVER = "#8577c9"

PANEL_COLOR = "#211c38"        # the frosted panel the chat sits in
INPUT_BG = "#2a2444"

USER_BUBBLE = "#4a7a63"        # soft sage green, WhatsApp-inspired
USER_TEXT = "#eef7ef"
ASSISTANT_BUBBLE = "#f1e9de"   # warm cream
ASSISTANT_TEXT = "#2a2440"
TIMESTAMP_COLOR_USER = "#cfe8d9"
TIMESTAMP_COLOR_ASSISTANT = "#8d8398"

CHIP_TEXT = "#d8cff2"

WINDOW_W, WINDOW_H = 640, 820

# ---------- Window ----------
app = ctk.CTk()
app.title("Loominous")
app.geometry(f"{WINDOW_W}x{WINDOW_H}")
app.resizable(False, False)

bg_pil = Image.open("background.png").resize((WINDOW_W, WINDOW_H))
bg_image = ctk.CTkImage(light_image=bg_pil, dark_image=bg_pil, size=(WINDOW_W, WINDOW_H))
bg_label = ctk.CTkLabel(app, image=bg_image, text="")
bg_label.place(x=0, y=0, relwidth=1, relheight=1)

# ---------- Header (floats directly over the sky, no panel behind it) ----------
ctk.CTkLabel(
    app, text="Loominous", font=("Segoe UI", 24, "bold"), text_color=TEXT_COLOR,
    fg_color="transparent"
).place(x=28, y=20)
ctk.CTkLabel(
    app, text="Where your dreams start to speak to each other.",
    font=("Segoe UI", 12), text_color=MUTED, fg_color="transparent"
).place(x=28, y=54)

# ---------- Tabview, floating over the sky with transparent chrome ----------
tabview = ctk.CTkTabview(
    app, width=WINDOW_W - 32, height=WINDOW_H - 100,
    fg_color="transparent",
    segmented_button_fg_color=INPUT_BG,
    segmented_button_selected_color=ACCENT,
    segmented_button_selected_hover_color=ACCENT_HOVER,
    segmented_button_unselected_color=INPUT_BG,
    text_color=TEXT_COLOR,
)
tabview.place(x=16, y=82)
tab_log = tabview.add("Log a Dream")
tab_mydreams = tabview.add("My Dreams")
tab_patterns = tabview.add("Patterns")
tab_profile = tabview.add("Profile")
tab_log.configure(fg_color="transparent")
tab_mydreams.configure(fg_color="transparent")
tab_patterns.configure(fg_color="transparent")
tab_profile.configure(fg_color="transparent")

# ---------- Profile, loaded once at startup ----------
profile = database.get_profile()

# ===================== TAB 1: LOG A DREAM =====================

panel_log = ctk.CTkFrame(tab_log, fg_color=PANEL_COLOR, corner_radius=18)
panel_log.pack(fill="both", expand=True, padx=2, pady=(8, 2))

current_dream = None  # {"id": ..., "messages": [...]} once a dream is active

input_label = ctk.CTkLabel(
    panel_log, text="What did you dream?", font=("Segoe UI", 13), text_color=MUTED
)
input_label.pack(anchor="w", padx=18, pady=(16, 6))

dream_input = ctk.CTkTextbox(
    panel_log, height=90, font=("Segoe UI", 13), fg_color=INPUT_BG,
    text_color=TEXT_COLOR, corner_radius=12, border_width=0
)
dream_input.pack(fill="x", padx=16, pady=(0, 8))

status_label = ctk.CTkLabel(panel_log, text="", font=("Segoe UI", 11, "italic"), text_color=ACCENT)
status_label.pack(anchor="w", padx=18)

chat_scroll = ctk.CTkScrollableFrame(panel_log, fg_color="transparent")
chat_scroll.pack(fill="both", expand=True, padx=10, pady=(6, 8))


def scroll_chat_to_bottom():
    app.update_idletasks()
    chat_scroll._parent_canvas.yview_moveto(1.0)


def add_bubble(scroll_frame, sender, text):
    """
    Add a message bubble to any chat scroll area (used by both tabs).
    sender: 'user', 'assistant', or 'chip' (a small insight-tag line).
    """
    row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
    row.pack(fill="x", pady=4, padx=4)

    if sender == "chip":
        ctk.CTkLabel(
            row, text=text, font=("Segoe UI", 11, "italic"), text_color=CHIP_TEXT,
            wraplength=420, justify="left"
        ).pack(anchor="w", padx=10)
        app.update_idletasks()
        scroll_frame._parent_canvas.yview_moveto(1.0)
        return

    is_user = sender == "user"
    bubble_color = USER_BUBBLE if is_user else ASSISTANT_BUBBLE
    text_color = USER_TEXT if is_user else ASSISTANT_TEXT
    ts_color = TIMESTAMP_COLOR_USER if is_user else TIMESTAMP_COLOR_ASSISTANT

    bubble = ctk.CTkFrame(row, fg_color=bubble_color, corner_radius=16)
    bubble.pack(side="right" if is_user else "left",
                padx=(70, 4) if is_user else (4, 70))

    ctk.CTkLabel(
        bubble, text=text, font=("Segoe UI", 13), text_color=text_color,
        wraplength=300, justify="left"
    ).pack(anchor="w", padx=14, pady=(10, 2))

    ctk.CTkLabel(
        bubble, text=datetime.now().strftime("%H:%M"), font=("Segoe UI", 9),
        text_color=ts_color
    ).pack(anchor="e" if is_user else "w", padx=14, pady=(0, 8))

    app.update_idletasks()
    scroll_frame._parent_canvas.yview_moveto(1.0)


def set_log_busy(is_busy, message=""):
    interpret_button.configure(state="disabled" if is_busy else "normal")
    status_label.configure(text=message)


def reset_dream_session():
    global current_dream
    current_dream = None
    dream_input.delete("1.0", "end")
    for widget in chat_scroll.winfo_children():
        widget.destroy()
    input_label.configure(text="What did you dream?")
    interpret_button.configure(text="Interpret This Dream")


def on_interpret():
    global current_dream
    user_text = dream_input.get("1.0", "end").strip()
    if not user_text:
        return
    dream_input.delete("1.0", "end")

    if current_dream is None:
        add_bubble(chat_scroll, "user", user_text)
        set_log_busy(True, "Reading your dream...")

        def worker():
            extracted = engine.extract_dream_data(user_text)
            app.after(0, lambda: set_log_busy(True, "Finding connections..."))

            embedding = engine.embed_text(user_text)
            all_dreams = database.get_all_dreams()
            similar = engine.find_similar_dreams(embedding, all_dreams, top_n=3)

            app.after(0, lambda: set_log_busy(True, "Interpreting..."))
            interpretation = engine.interpret_dream(user_text, extracted, similar, profile)

            dream_id = database.insert_dream(user_text, extracted, interpretation, embedding)

            context_message = (
                f"Dream described: {user_text}\n\n"
                f"Symbols: {', '.join(extracted.get('symbols', []))}\n"
                f"Emotions: {', '.join(extracted.get('emotions', []))}\n"
                f"Themes: {', '.join(extracted.get('themes', []))}"
            )
            messages = [
                {"role": "user", "content": context_message},
                {"role": "assistant", "content": interpretation},
            ]
            database.update_dream_conversation(dream_id, messages)

            chip_parts = []
            if extracted.get("symbols"):
                chip_parts.append("Symbols: " + ", ".join(extracted["symbols"]))
            if extracted.get("emotions"):
                chip_parts.append("Emotions: " + ", ".join(extracted["emotions"]))
            if extracted.get("themes"):
                chip_parts.append("Themes: " + ", ".join(extracted["themes"]))
            chip_text = "  ·  ".join(chip_parts)

            def finish():
                global current_dream
                current_dream = {"id": dream_id, "messages": messages}
                if chip_text:
                    add_bubble(chat_scroll, "chip", chip_text)
                add_bubble(chat_scroll, "assistant", interpretation)
                set_log_busy(False)
                input_label.configure(text="Reply, or share more about the dream")
                interpret_button.configure(text="Continue")
                populate_my_dreams()

            app.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    else:
        add_bubble(chat_scroll, "user", user_text)
        set_log_busy(True, "Thinking...")

        def worker():
            current_dream["messages"].append({"role": "user", "content": user_text})
            reply = engine.continue_conversation(current_dream["messages"])
            current_dream["messages"].append({"role": "assistant", "content": reply})
            database.update_dream_conversation(current_dream["id"], current_dream["messages"])

            def finish():
                add_bubble(chat_scroll, "assistant", reply)
                set_log_busy(False)

            app.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


button_row = ctk.CTkFrame(panel_log, fg_color="transparent")
button_row.pack(fill="x", padx=16, pady=(0, 16))

new_dream_button = ctk.CTkButton(
    button_row, text="New Dream", command=reset_dream_session,
    height=40, corner_radius=12, fg_color="transparent", border_width=1,
    border_color=MUTED, hover_color=INPUT_BG, text_color=MUTED,
    font=("Segoe UI", 13)
)
new_dream_button.pack(side="left")

interpret_button = ctk.CTkButton(
    button_row, text="Interpret This Dream", command=on_interpret,
    height=40, corner_radius=12, fg_color=ACCENT, hover_color=ACCENT_HOVER,
    text_color="#1a1530", font=("Segoe UI", 13, "bold")
)
interpret_button.pack(side="right")

dream_input.bind("<Shift-Return>", lambda event: on_interpret())

# ===================== TAB 2: MY DREAMS =====================
# Browse every dream you've logged, individually. Click one to reopen
# its full interpretation and conversation thread in a detail window.

panel_mydreams = ctk.CTkFrame(tab_mydreams, fg_color=PANEL_COLOR, corner_radius=18)
panel_mydreams.pack(fill="both", expand=True, padx=2, pady=(8, 2))

mydreams_header_row = ctk.CTkFrame(panel_mydreams, fg_color="transparent")
mydreams_header_row.pack(fill="x", padx=18, pady=(16, 6))

ctk.CTkLabel(
    mydreams_header_row, text="Your dream archive",
    font=("Segoe UI", 13), text_color=MUTED
).pack(side="left")

ctk.CTkButton(
    mydreams_header_row, text="Refresh", command=lambda: populate_my_dreams(),
    height=28, width=80, corner_radius=10, fg_color="transparent",
    border_width=1, border_color=MUTED, hover_color=INPUT_BG,
    text_color=MUTED, font=("Segoe UI", 11)
).pack(side="right")

mydreams_scroll = ctk.CTkScrollableFrame(panel_mydreams, fg_color="transparent")
mydreams_scroll.pack(fill="both", expand=True, padx=10, pady=(6, 16))


def open_dream_detail(dream):
    """Open a read-only window showing one dream's full story: the
    original description, its extracted data, and the entire conversation
    thread that followed it."""
    detail = ctk.CTkToplevel(app)
    detail.title(f"Dream -- {dream['timestamp'][:10]}")
    detail.geometry("480x640")
    detail.configure(fg_color=PANEL_COLOR)

    date_str = dream["timestamp"][:10]
    ctk.CTkLabel(
        detail, text=date_str, font=("Segoe UI", 16, "bold"), text_color=TEXT_COLOR
    ).pack(anchor="w", padx=20, pady=(18, 4))

    chip_parts = []
    if dream.get("symbols"):
        chip_parts.append("Symbols: " + ", ".join(dream["symbols"]))
    if dream.get("emotions"):
        chip_parts.append("Emotions: " + ", ".join(dream["emotions"]))
    if dream.get("themes"):
        chip_parts.append("Themes: " + ", ".join(dream["themes"]))
    if chip_parts:
        ctk.CTkLabel(
            detail, text="  ·  ".join(chip_parts), font=("Segoe UI", 11, "italic"),
            text_color=CHIP_TEXT, wraplength=430, justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 10))

    detail_scroll = ctk.CTkScrollableFrame(detail, fg_color="transparent")
    detail_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 16))

    conversation = dream.get("conversation") or []
    if conversation:
        # First entry is the seed context (not shown as a bubble, it's
        # just the dream text + extracted data we already showed above);
        # every entry after that is real back-and-forth.
        for i, msg in enumerate(conversation):
            if i == 0:
                continue  # skip the seed context message
            sender = "user" if msg["role"] == "user" else "assistant"
            add_bubble(detail_scroll, sender, msg["content"])
    else:
        add_bubble(detail_scroll, "assistant", dream.get("interpretation", ""))


def populate_my_dreams():
    """Rebuild the dream list -- called on startup, after logging a new
    dream, and whenever the Refresh button is pressed."""
    for widget in mydreams_scroll.winfo_children():
        widget.destroy()

    all_dreams = list(reversed(database.get_all_dreams()))  # newest first

    if not all_dreams:
        ctk.CTkLabel(
            mydreams_scroll, text="No dreams logged yet. Your first one will appear here.",
            font=("Segoe UI", 12), text_color=MUTED
        ).pack(anchor="w", padx=10, pady=10)
        return

    for dream in all_dreams:
        card = ctk.CTkFrame(mydreams_scroll, fg_color=INPUT_BG, corner_radius=14)
        card.pack(fill="x", padx=4, pady=5)

        date_str = dream["timestamp"][:10]
        snippet = dream["raw_text"][:80] + ("..." if len(dream["raw_text"]) > 80 else "")

        text_col = ctk.CTkFrame(card, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        ctk.CTkLabel(
            text_col, text=date_str, font=("Segoe UI", 11, "bold"), text_color=ACCENT
        ).pack(anchor="w")
        ctk.CTkLabel(
            text_col, text=snippet, font=("Segoe UI", 12), text_color=TEXT_COLOR,
            wraplength=360, justify="left"
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            card, text="Open", width=64, height=32, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#1a1530",
            font=("Segoe UI", 12),
            command=lambda d=dream: open_dream_detail(d)
        ).pack(side="right", padx=14)


populate_my_dreams()

# ===================== TAB 2: PATTERNS =====================

panel_patterns = ctk.CTkFrame(tab_patterns, fg_color=PANEL_COLOR, corner_radius=18)
panel_patterns.pack(fill="both", expand=True, padx=2, pady=(8, 2))

ctk.CTkLabel(
    panel_patterns, text="Patterns across your dream archive",
    font=("Segoe UI", 13), text_color=MUTED
).pack(anchor="w", padx=18, pady=(16, 6))

patterns_status = ctk.CTkLabel(
    panel_patterns, text="", font=("Segoe UI", 11, "italic"), text_color=ACCENT
)
patterns_status.pack(anchor="w", padx=18)

patterns_scroll = ctk.CTkScrollableFrame(panel_patterns, fg_color="transparent")
patterns_scroll.pack(fill="both", expand=True, padx=10, pady=(6, 8))

patterns_input = ctk.CTkTextbox(
    panel_patterns, height=60, font=("Segoe UI", 13), fg_color=INPUT_BG,
    text_color=TEXT_COLOR, corner_radius=12, border_width=0
)
patterns_input.pack(fill="x", padx=16, pady=(0, 8))

# Tracks the ongoing conversation about the pattern analysis, once started.
patterns_conversation = None  # list of {"role": ..., "content": ...}


def set_patterns_busy(is_busy, message=""):
    analyze_button.configure(state="disabled" if is_busy else "normal")
    patterns_status.configure(text=message)


def reset_patterns_session():
    global patterns_conversation
    patterns_conversation = None
    patterns_input.delete("1.0", "end")
    for widget in patterns_scroll.winfo_children():
        widget.destroy()
    analyze_button.configure(text="Analyze My Dream Archive")


def on_analyze():
    global patterns_conversation

    if patterns_conversation is None:
        # ---------- First run: analyze the whole archive ----------
        set_patterns_busy(True, "Looking across your dreams...")

        def worker():
            all_dreams = database.get_all_dreams()
            count = len(all_dreams)
            analysis = engine.analyze_patterns(all_dreams, profile)

            archive_summary = "\n".join(
                f"{d['timestamp'][:10]} -- symbols: {', '.join(d['symbols'])}; "
                f"emotions: {', '.join(d['emotions'])}; themes: {', '.join(d['themes'])}"
                for d in all_dreams
            )
            seed_message = (
                f"Here is this person's full dream archive so far "
                f"({count} dreams):\n{archive_summary}"
            )
            messages = [
                {"role": "user", "content": seed_message},
                {"role": "assistant", "content": analysis},
            ]

            def finish():
                global patterns_conversation
                patterns_conversation = messages
                add_bubble(patterns_scroll, "chip", f"Based on {count} logged dream{'s' if count != 1 else ''}")
                add_bubble(patterns_scroll, "assistant", analysis)
                set_patterns_busy(False)
                analyze_button.configure(text="Ask")

            app.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    else:
        # ---------- Follow-up question about the analysis ----------
        question = patterns_input.get("1.0", "end").strip()
        if not question:
            return
        patterns_input.delete("1.0", "end")
        add_bubble(patterns_scroll, "user", question)
        set_patterns_busy(True, "Thinking...")

        def worker():
            patterns_conversation.append({"role": "user", "content": question})
            reply = engine.continue_conversation(patterns_conversation)
            patterns_conversation.append({"role": "assistant", "content": reply})

            def finish():
                add_bubble(patterns_scroll, "assistant", reply)
                set_patterns_busy(False)

            app.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


patterns_button_row = ctk.CTkFrame(panel_patterns, fg_color="transparent")
patterns_button_row.pack(fill="x", padx=16, pady=(0, 16))

new_analysis_button = ctk.CTkButton(
    patterns_button_row, text="New Analysis", command=reset_patterns_session,
    height=40, corner_radius=12, fg_color="transparent", border_width=1,
    border_color=MUTED, hover_color=INPUT_BG, text_color=MUTED,
    font=("Segoe UI", 13)
)
new_analysis_button.pack(side="left")

analyze_button = ctk.CTkButton(
    patterns_button_row, text="Analyze My Dream Archive", command=on_analyze,
    height=40, corner_radius=12, fg_color=ACCENT, hover_color=ACCENT_HOVER,
    text_color="#1a1530", font=("Segoe UI", 13, "bold")
)
analyze_button.pack(side="right")

# ===================== TAB 4: PROFILE =====================

panel_profile = ctk.CTkFrame(tab_profile, fg_color=PANEL_COLOR, corner_radius=18)
panel_profile.pack(fill="both", expand=True, padx=2, pady=(8, 2))

profile_scroll = ctk.CTkScrollableFrame(panel_profile, fg_color="transparent")
profile_scroll.pack(fill="both", expand=True, padx=10, pady=(16, 10))

AVATAR_SIZE = 140


def make_circular_image(path, size=AVATAR_SIZE):
    """Load an image file and return a circular-cropped CTkImage."""
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def generate_placeholder_avatar(size=AVATAR_SIZE):
    """A simple generic avatar (silhouette on a soft circle) used until
    the person uploads their own photo."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=(58, 50, 92, 255))

    head_r = size * 0.16
    cx, cy = size / 2, size * 0.38
    draw.ellipse((cx - head_r, cy - head_r, cx + head_r, cy + head_r), fill=(220, 215, 235, 255))

    body_w = size * 0.52
    draw.ellipse((size / 2 - body_w / 2, size * 0.56, size / 2 + body_w / 2, size * 1.15),
                 fill=(220, 215, 235, 255))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


avatar_frame = ctk.CTkFrame(profile_scroll, fg_color="transparent")
avatar_frame.pack(pady=(10, 6))

if profile.get("picture_path") and os.path.exists(profile["picture_path"]):
    avatar_image = make_circular_image(profile["picture_path"])
else:
    avatar_image = generate_placeholder_avatar()

avatar_label = ctk.CTkLabel(avatar_frame, image=avatar_image, text="")
avatar_label.pack()


def on_change_photo():
    chosen = filedialog.askopenfilename(
        title="Choose a profile picture",
        filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif")]
    )
    if not chosen:
        return
    dest_path = "profile_picture.png"
    # Convert and save a copy into the project folder so the app doesn't
    # depend on the original file staying in its original location.
    Image.open(chosen).convert("RGBA").save(dest_path)

    new_image = make_circular_image(dest_path)
    avatar_label.configure(image=new_image)
    avatar_label.image = new_image  # keep a reference so it isn't garbage-collected
    profile["picture_path"] = dest_path


ctk.CTkButton(
    profile_scroll, text="Change Photo", command=on_change_photo,
    height=34, width=140, corner_radius=10, fg_color=INPUT_BG,
    hover_color="#352c54", text_color=TEXT_COLOR, font=("Segoe UI", 12)
).pack(pady=(0, 18))


def labeled_field(label_text, height=36):
    ctk.CTkLabel(
        profile_scroll, text=label_text, font=("Segoe UI", 12), text_color=MUTED
    ).pack(anchor="w", padx=14, pady=(6, 2))
    entry = ctk.CTkEntry(
        profile_scroll, height=height, font=("Segoe UI", 13), fg_color=INPUT_BG,
        text_color=TEXT_COLOR, corner_radius=10, border_width=0
    )
    entry.pack(fill="x", padx=14)
    return entry


name_entry = labeled_field("Name")
name_entry.insert(0, profile.get("name", ""))

birth_year_entry = labeled_field("Birth year")
if profile.get("birth_year"):
    birth_year_entry.insert(0, str(profile["birth_year"]))

birthplace_entry = labeled_field("Birthplace")
birthplace_entry.insert(0, profile.get("birthplace", ""))

location_entry = labeled_field("Currently living in")
location_entry.insert(0, profile.get("current_location", ""))

ctk.CTkLabel(
    profile_scroll, text="About you and your life", font=("Segoe UI", 12), text_color=MUTED
).pack(anchor="w", padx=14, pady=(6, 2))
bio_box = ctk.CTkTextbox(
    profile_scroll, height=100, font=("Segoe UI", 13), fg_color=INPUT_BG,
    text_color=TEXT_COLOR, corner_radius=10, border_width=0
)
bio_box.pack(fill="x", padx=14)
bio_box.insert("1.0", profile.get("bio", ""))

profile_save_status = ctk.CTkLabel(
    profile_scroll, text="", font=("Segoe UI", 11, "italic"), text_color=ACCENT
)
profile_save_status.pack(pady=(10, 0))


def on_save_profile():
    global profile
    birth_year_text = birth_year_entry.get().strip()
    birth_year_value = int(birth_year_text) if birth_year_text.isdigit() else None

    profile = {
        "name": name_entry.get().strip(),
        "birth_year": birth_year_value,
        "birthplace": birthplace_entry.get().strip(),
        "current_location": location_entry.get().strip(),
        "bio": bio_box.get("1.0", "end").strip(),
        "picture_path": profile.get("picture_path", ""),
    }
    database.save_profile(profile)
    profile_save_status.configure(text="Saved.")
    app.after(2000, lambda: profile_save_status.configure(text=""))


ctk.CTkButton(
    profile_scroll, text="Save Profile", command=on_save_profile,
    height=40, corner_radius=12, fg_color=ACCENT, hover_color=ACCENT_HOVER,
    text_color="#1a1530", font=("Segoe UI", 13, "bold")
).pack(pady=(14, 16))

# ===================== SPLASH: ANIMATED LOGO INTRO =====================
# A short, self-contained animation: three rings start overlapped at the
# center and weave outward into Loominous's trefoil mark, then the wordmark
# fades in. Built as a sequence of pre-rendered PIL frames (no video file
# needed) cycled on a single label -- the classic lightweight way to
# animate in Tkinter.


def build_logo_mark(size, progress):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    radius = size * 0.24
    thickness = max(3, int(size * 0.055))
    offset = radius * 0.62 * progress

    colors = [(196, 181, 247, 255), (152, 132, 224, 255), (108, 92, 184, 255)]
    for i, color in enumerate(colors):
        angle = math.radians(-90 + i * 120)
        ox = cx + offset * math.cos(angle)
        oy = cy + offset * math.sin(angle)
        bbox = [ox - radius, oy - radius, ox + radius, oy + radius]
        draw.ellipse(bbox, outline=color, width=thickness)
    return img


def build_splash_background(w, h):
    img = Image.new("RGB", (w, h), (20, 16, 38))
    draw = ImageDraw.Draw(img)
    cx, cy = w / 2, h * 0.40
    max_r = max(w, h) * 0.7
    steps = 36
    glow = (92, 78, 158)
    base = (20, 16, 38)
    for i in range(steps, 0, -1):
        t = i / steps
        r = max_r * t
        falloff = (1 - t) ** 1.3
        color = tuple(int(base[c] + (glow[c] - base[c]) * falloff) for c in range(3))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    return img


def run_splash():
    splash_bg = build_splash_background(WINDOW_W, WINDOW_H)
    mark_size = 220
    mx, my = (WINDOW_W - mark_size) // 2, int(WINDOW_H * 0.30)

    total_frames = 22
    frame_images = []
    for i in range(total_frames):
        t = i / (total_frames - 1)
        eased = 1 - (1 - t) ** 2  # ease-out: fast start, gentle settle
        mark = build_logo_mark(mark_size, eased)
        frame = splash_bg.convert("RGBA")
        frame.paste(mark, (mx, my), mark)
        frame = frame.convert("RGB")
        frame_images.append(ctk.CTkImage(light_image=frame, dark_image=frame, size=(WINDOW_W, WINDOW_H)))

    splash_frame = ctk.CTkFrame(app, fg_color="transparent")
    splash_frame.place(x=0, y=0, relwidth=1, relheight=1)

    splash_label = ctk.CTkLabel(splash_frame, image=frame_images[0], text="")
    splash_label.place(x=0, y=0, relwidth=1, relheight=1)

    wordmark = ctk.CTkLabel(splash_frame, text="", font=("Segoe UI", 30, "bold"), text_color=TEXT_COLOR)
    tagline = ctk.CTkLabel(splash_frame, text="", font=("Segoe UI", 12), text_color=MUTED)

    def play(i=0):
        splash_label.configure(image=frame_images[i])
        splash_label.image = frame_images[i]
        if i < total_frames - 1:
            app.after(32, lambda: play(i + 1))
        else:
            app.after(150, reveal_wordmark)

    def reveal_wordmark():
        wordmark.configure(text="Loominous")
        wordmark.place(relx=0.5, rely=0.58, anchor="center")
        tagline.configure(text="Where your dreams start to speak to each other.")
        tagline.place(relx=0.5, rely=0.645, anchor="center")
        app.after(1100, splash_frame.destroy)

    play()


run_splash()
app.mainloop()
