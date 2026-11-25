"""
DateTimeBox - digital + analog version (v16: only second hand = thin red main needle, hour/minute back to gold)\nAnalog face is frameless / transparent with 3 sub-dials: DAY, DATE, MONTH. Themes: Navy Glory (white outline), Vivid Gold, High-Contrast White
A compact floating date/time clock with day progress, chimes, speech,
and persistent floating notes.
"""

import json
import math
import os
import struct
import subprocess
import sys
import threading
import tkinter as tk
import wave
from datetime import datetime

try:
    import winsound
except ImportError:
    winsound = None

try:
    from calendar_notes import CalendarNotesManager
except Exception as _import_err:
    print(f"Calendar Notes failed to import: {_import_err}")
    CalendarNotesManager = None

CLOCK_WIDTH = 200
CLOCK_HEIGHT = 150
# Analog mode - frameless / wallpaper-transparent, like your reference pic
ANALOG_WIDTH = 320
ANALOG_HEIGHT = 316  # just the face now - no bottom bar in analog
ANALOG_CANVAS = 300
# This colour is used as the transparent key on Windows. Anything painted
# in this colour becomes see-through, so your wallpaper shows through.
TRANSPARENT_KEY = "#010203"
# Vivid gold - more saturated than the old muted #D4AF37, so it pops.
# The real trick for "vivid on ANY wallpaper" is not the fill colour alone,
# it is the black outline + shadow behind it (see drawing code below).
GOLD = "#FFC300"
# Sub-dial needles (DAY / DATE / MONTH) - thin + red, same for all 3 themes
SUBDIAL_NEEDLE = "#FF1A1A"
# Main hands (hour / minute / second) - same thin red as the sub-dials
MAIN_NEEDLE = "#FF1A1A"
GOLD_LIGHT = "#FFE27A"
GOLD_DARK = "#8A5A00"
OUTLINE = "#000000"  # fallback, real outline now comes from the theme
# Three analog themes. Each has its own outline colour:
# gold + contrast use black outline, navy glory uses WHITE outline as requested.
ANALOG_THEMES = {
    "gold_vivid": {"main": "#FFC300", "light": "#FFE27A", "dark": "#8A5A00", "center": "#FFFFFF", "outline": "#000000", "label": "Vivid Gold", "shine": "#FFE27A", "subdial_outline": "#FFFFFF", "subdial_outline_width": 1.0},
    "contrast":   {"main": "#FFFFFF", "light": "#FFFFFF", "dark": "#000000", "center": "#FFFFFF", "outline": "#000000", "label": "High-Contrast White", "shine": "#FFFFFF", "subdial_outline": "#FFFFFF", "subdial_outline_width": 1.0},
    "navy_glory": {"main": "#1233A6", "light": "#7AA8FF", "dark": "#0A1F5C", "center": "#FFFFFF", "outline": "#FFFFFF", "label": "Navy Glory Shine ", "shine": "#C0D2FF", "subdial_center": "#071A4D", "subdial_title": "#071A4D", "subdial_outline": "#FFFFFF", "subdial_outline_width": 1.0},
}
THEME_ORDER = ["navy_glory", "gold_vivid", "contrast"]
RIGHT_COL_WIDTH = 110
DATE_FONT_SIZE = 42
HOUR_FONT_SIZE = 38

DAY_START_SEC = 6 * 3600
DAY_END_SEC = 18 * 3600
DAY_TOTAL_SEC = DAY_END_SEC - DAY_START_SEC

NOTE_COLORS = [
    {"bg": "#fef3c7", "header": "#fde68a", "fg": "#92400e"},
    {"bg": "#fce7f3", "header": "#f9a8d4", "fg": "#831843"},
    {"bg": "#dcfce7", "header": "#86efac", "fg": "#14532d"},
    {"bg": "#dbeafe", "header": "#93c5fd", "fg": "#1e3a8a"},
    {"bg": "#ffedd5", "header": "#fdba74", "fg": "#7c2d12"},
    {"bg": "#e0e7ff", "header": "#a5b4fc", "fg": "#312e81"},
]


def get_appdata_dir():
    if sys.platform == "win32" and os.getenv("APPDATA"):
        folder = os.path.join(os.getenv("APPDATA"), "DateTimeBox")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".datetimebox")
    os.makedirs(folder, exist_ok=True)
    return folder


APPDATA_DIR = get_appdata_dir()
CONFIG_PATH = os.path.join(APPDATA_DIR, "config.json")
NOTES_PATH = os.path.join(APPDATA_DIR, "notes.json")
CALENDAR_NOTES_PATH = os.path.join(APPDATA_DIR, "calendar_notes.json")
CHIME_QUARTER = os.path.join(APPDATA_DIR, "chime_quarter.wav")
CHIME_HOUR = os.path.join(APPDATA_DIR, "chime_hour.wav")
CHIME_NOON = os.path.join(APPDATA_DIR, "chime_noon.wav")


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def get_ordinal(number):
    if 11 <= number % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def generate_chimes():
    def create_wav(path, notes):
        if os.path.exists(path):
            return
        try:
            sample_rate = 22050
            with wave.open(path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                for frequency, duration in notes:
                    count = int(sample_rate * duration)
                    frames = bytearray()
                    for index in range(count):
                        t = index / sample_rate
                        envelope = math.exp(-3.5 * t)
                        value = (
                            0.7 * math.sin(2 * math.pi * frequency * t)
                            + 0.3 * math.sin(4 * math.pi * frequency * t)
                        )
                        sample = max(-32767, min(32767, int(value * envelope * 18000)))
                        frames.extend(struct.pack("<h", sample))
                    wav_file.writeframes(frames)
        except (OSError, wave.Error) as exc:
            print(f"Chime generation failed: {exc}")

    create_wav(CHIME_QUARTER, [(659.25, 0.7)])
    create_wav(CHIME_HOUR, [(659.25, 0.55), (523.25, 0.95)])
    create_wav(CHIME_NOON, [(783.99, 0.5), (659.25, 0.5), (523.25, 1.2)])


class DateTimeBox:
    def __init__(self, root):
        self.root = root
        self.root.title("DateTime Box")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg="#0f0f0f")

        generate_chimes()

        cfg = load_json(CONFIG_PATH, {})
        self.notes_list = load_json(NOTES_PATH, None)
        if not isinstance(self.notes_list, list) or not self.notes_list:
            self.notes_list = cfg.get("notes_list", [{"text": "", "color_idx": 0}])
        self.notes_list = [
            n for n in self.notes_list if isinstance(n, dict)
        ] or [{"text": "", "color_idx": 0}]
        for note in self.notes_list:
            note.setdefault("text", "")
            note.setdefault("color_idx", 0)

        self.current_note_idx = max(
            0, min(int(cfg.get("current_note_idx", 0)), len(self.notes_list) - 1)
        )
        self.analog_theme = cfg.get("analog_theme", "navy_glory")
        if self.analog_theme not in ("gold_vivid", "contrast", "navy_glory"):
            self.analog_theme = "navy_glory"
        self.clock_mode = cfg.get("clock_mode", "digital")
        if self.clock_mode not in ("digital", "analog"):
            self.clock_mode = "digital"
        self.is_pinned = bool(cfg.get("pinned", False))
        self.is_topmost = bool(cfg.get("topmost", True))
        self.sound_enabled = bool(cfg.get("sound_enabled", True))
        self.opacity_val = float(cfg.get("opacity", 0.92))
        self.note_visible = bool(cfg.get("note_visible", False))
        self.note_geom = cfg.get("note_geom", "")
        if CalendarNotesManager is not None:
            self.calendar_notes = CalendarNotesManager(
                self.root,
                on_reminder=self._on_calendar_reminder,
                storage_path=CALENDAR_NOTES_PATH,
                get_topmost=lambda: self.is_topmost,
            )
        else:
            self.calendar_notes = None
        self.last_announced_slot = None
        self.note_window = None
        self.note_text_widget = None
        self.tooltip_window = None
        self.last_saved_text = ""
        self._drag_offset = (0, 0)
        self._note_drag_offset = (0, 0)

        x, y = int(cfg.get("x", 100)), int(cfg.get("y", 100))
        if self.clock_mode == "analog":
            self.root.geometry(f"{ANALOG_WIDTH}x{ANALOG_HEIGHT}+{x}+{y}")
        else:
            self.root.geometry(f"{CLOCK_WIDTH}x{CLOCK_HEIGHT}+{x}+{y}")
        self.root.attributes("-alpha", self.opacity_val)
        self.root.attributes("-topmost", self.is_topmost)

        self.build_clock()
        self.apply_initial_clock_mode()
        self.menu = tk.Menu(
            root, tearoff=0, bg="#1a1a1a", fg="white",
            activebackground="#333", bd=0
        )
        self.rebuild_menu()

        self.root.bind("<Button-1>", self.click_win)
        self.root.bind("<B1-Motion>", self.drag_win)
        self.root.bind("<ButtonRelease-1>", self.save_position)
        self.root.bind("<Button-3>", self.show_menu)
        self.root.bind("<Control-Button-1>", lambda _e: self.toggle_pin())

        self.update_pin_visual()
        self.update_note_visual()
        self.update_sound_visual()
        self.update_time()
        self.auto_save_loop()

        if self.note_visible and any(n["text"].strip() for n in self.notes_list):
            self.root.after(600, self.show_notes)
        if self.calendar_notes and self.calendar_notes.visible and any(n["text"].strip() for n in self.calendar_notes.notes_list):
            self.root.after(700, self.calendar_notes.show)

    def build_clock(self):
        # ---- DIGITAL FRAME (your original layout, untouched) ----
        self.digital_frame = tk.Frame(self.root, bg="#0f0f0f")
        self.digital_frame.pack(fill="both", expand=True)

        main = tk.Frame(self.digital_frame, bg="#0f0f0f", padx=10, pady=10)
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg="#0f0f0f")
        left.pack(side="left", fill="both", expand=True, padx=(0, 2))

        self.month_label = tk.Label(
            left, text="JAN", fg="#9ca3af", bg="#0f0f0f",
            font=("Segoe UI", 11, "bold")
        )
        self.month_label.pack(anchor="center")

        date_row = tk.Frame(left, bg="#0f0f0f")
        date_row.pack(anchor="w")
        self.date_label = tk.Label(
            date_row, text="01", fg="white", bg="#0f0f0f",
            font=("Segoe UI", DATE_FONT_SIZE, "bold")
        )
        self.date_label.pack(side="left")

        progress = tk.Frame(date_row, bg="#0f0f0f")
        progress.pack(side="left", padx=(6, 0), anchor="center", pady=(4, 0))
        self.progress_canvas = tk.Canvas(
            progress, width=22, height=22, bg="#0f0f0f",
            highlightthickness=0, cursor="hand2"
        )
        self.progress_canvas.pack()
        self.progress_canvas.bind("<Button-1>", self.show_progress_tooltip)
        self.progress_percent_label = tk.Label(
            progress, text="0%", fg="#ef4444", bg="#0f0f0f",
            font=("Segoe UI", 7, "bold"), cursor="hand2"
        )
        self.progress_percent_label.pack()
        self.progress_percent_label.bind("<Button-1>", self.show_progress_tooltip)

        self.weekday_label = tk.Label(
            left, text="Monday", fg="#9ca3af", bg="#0f0f0f",
            font=("Segoe UI", 10, "bold")
        )
        self.weekday_label.pack(anchor="center", pady=(2, 0))

        tk.Frame(main, bg="#2a2a2a", width=1).pack(
            side="left", fill="y", padx=8
        )
        right = tk.Frame(main, bg="#0f0f0f", width=RIGHT_COL_WIDTH)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self.hour_label = tk.Label(
            right, text="00", fg="white", bg="#0f0f0f",
            font=("Segoe UI", HOUR_FONT_SIZE), anchor="e"
        )
        self.hour_label.pack(anchor="e", fill="x")
        self.minute_label = tk.Label(
            right, text="00", fg="white", bg="#0f0f0f",
            font=("Segoe UI", HOUR_FONT_SIZE), anchor="e"
        )
        self.minute_label.pack(anchor="e", fill="x")

        # ---- ANALOG FRAME (new, frameless / transparent) ----
        self.analog_frame = tk.Frame(self.root, bg=TRANSPARENT_KEY)
        # don't pack yet - apply_initial_clock_mode() decides which shows

        self.analog_canvas = tk.Canvas(
            self.analog_frame, width=ANALOG_CANVAS, height=ANALOG_CANVAS,
            bg=TRANSPARENT_KEY, highlightthickness=0, cursor="hand2"
        )
        self.analog_canvas.pack(padx=10, pady=(8, 0))
        # Make the canvas draggable like the rest of the window
        self.analog_canvas.bind("<Button-1>", self.click_win)
        self.analog_canvas.bind("<B1-Motion>", self.drag_win)
        self.analog_canvas.bind("<ButtonRelease-1>", self.save_position)
        self.analog_canvas.bind("<Button-3>", self.show_menu)
        self.analog_canvas.bind("<Double-Button-1>", lambda _e: self.toggle_clock_mode())

        self.analog_info_label = tk.Label(
            self.analog_frame, text="", fg="#D4AF37", bg=TRANSPARENT_KEY,
            font=("Segoe UI", 8, "bold")
        )
        self.analog_info_label.pack(pady=(0, 2))
        self.analog_sub_label = tk.Label(
            self.analog_frame, text="Double-click to switch • Right-click for menu",
            fg="#8a8a8a", bg=TRANSPARENT_KEY, font=("Segoe UI", 7)
        )
        self.analog_sub_label.pack(pady=(0, 2))

        # ---- SHARED CONTROLS (bottom bar, same in both modes) ----
        self.controls_frame = tk.Frame(self.root, bg="#0f0f0f")
        self.controls_frame.pack(fill="x", side="bottom", padx=10, pady=(0, 6))

        self.close_btn = self.make_control(self.controls_frame, "✕", self.close_app)
        self.pin_btn = self.make_control(self.controls_frame, "📌", self.toggle_pin)
        self.note_btn = self.make_control(self.controls_frame, "📝", self.toggle_notes)
        self.cal_btn = self.make_control(self.controls_frame, "📅", self.toggle_calendar_notes)
        self.sound_btn = self.make_control(self.controls_frame, "🔊", self.toggle_sound)
        # The mode switch - the "choice between the two"
        self.mode_btn = self.make_control(self.controls_frame, "◷", self.toggle_clock_mode)

    # ---------- Analog / Digital mode switching ----------
    def apply_initial_clock_mode(self):
        # Called once at startup - show the saved mode without re-saving
        if self.clock_mode == "analog":
            self.digital_frame.pack_forget()
            self.analog_frame.pack(fill="both", expand=True)
            self._apply_transparent_look()
        else:
            self.analog_frame.pack_forget()
            self.digital_frame.pack(fill="both", expand=True)
            self._apply_solid_look()
        self.update_mode_visual()

    def _apply_transparent_look(self):
        # Windows: -transparentcolor makes TRANSPARENT_KEY see-through,
        # so the desktop wallpaper shows through the clock face.
        # On macOS / Linux this flag is ignored, so we fall back to -alpha.
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.attributes("-alpha", 1.0)
        self.analog_frame.configure(bg=TRANSPARENT_KEY)
        self.analog_canvas.configure(bg=TRANSPARENT_KEY)
        # --- FIX: hide EVERYTHING below the face in analog ---
        # No info line, no hint line, no control icons. Only the face floats.
        # You still switch back with: double-click face, or right-click > menu.
        try:
            self.analog_info_label.pack_forget()
            self.analog_sub_label.pack_forget()
            self.controls_frame.pack_forget()
        except tk.TclError:
            pass

    def _apply_solid_look(self):
        try:
            self.root.attributes("-transparentcolor", "")
        except tk.TclError:
            pass
        self.root.configure(bg="#0f0f0f")
        self.root.attributes("-alpha", self.opacity_val)
        self.controls_frame.configure(bg="#0f0f0f")
        for w in self.controls_frame.winfo_children():
            try:
                w.configure(bg="#0f0f0f")
            except tk.TclError:
                pass
        # Digital mode gets its bottom bar back
        try:
            self.controls_frame.pack(fill="x", side="bottom", padx=10, pady=(0, 6))
        except tk.TclError:
            pass

    def update_mode_visual(self):
        # Mode button shows what you will switch TO
        if hasattr(self, "mode_btn"):
            if self.clock_mode == "analog":
                self.mode_btn.config(text="◧", fg="#D4AF37")
            else:
                self.mode_btn.config(text="◷", fg="#666")

    def toggle_clock_mode(self):
        new_mode = "analog" if self.clock_mode == "digital" else "digital"
        self.set_clock_mode(new_mode)

    def toggle_analog_theme(self):
        # Cycle: Navy Glory -> Vivid Gold -> High-Contrast White -> Navy Glory...
        try:
            idx = THEME_ORDER.index(self.analog_theme)
        except ValueError:
            idx = 0
        self.analog_theme = THEME_ORDER[(idx + 1) % len(THEME_ORDER)]
        self.save_config()
        self.rebuild_menu()
        self.update_time()

    def set_clock_mode(self, mode):
        if mode not in ("digital", "analog"):
            return
        self.clock_mode = mode
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if mode == "analog":
            self.digital_frame.pack_forget()
            self.analog_frame.pack(fill="both", expand=True)
            self.root.geometry(f"{ANALOG_WIDTH}x{ANALOG_HEIGHT}+{x}+{y}")
            self._apply_transparent_look()
        else:
            self.analog_frame.pack_forget()
            self.digital_frame.pack(fill="both", expand=True)
            self.root.geometry(f"{CLOCK_WIDTH}x{CLOCK_HEIGHT}+{x}+{y}")
            self._apply_solid_look()
        self.update_mode_visual()
        self.save_config()
        self.rebuild_menu()
        self.update_time()

    # ---------- Analog drawing ----------
    def _polar(self, cx, cy, radius, angle_deg_from_12):
        # 0 deg = 12 o'clock, clockwise
        rad = math.radians(angle_deg_from_12)
        return (cx + radius * math.sin(rad), cy - radius * math.cos(rad))

    def _text_with_halo(self, x, y, text, fill, font):
        # Halo first (white for Navy Glory, black for Gold / White), then main text
        # on top - readable on light AND dark wallpapers
        c = self.analog_canvas
        outline = ANALOG_THEMES.get(self.analog_theme, {}).get("outline", OUTLINE)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            c.create_text(x + dx, y + dy, text=text, fill=outline, font=font)
        c.create_text(x, y, text=text, fill=fill, font=font)

    def _draw_gold_triangle_marker(self, cx, cy, radius, angle):
        # Small triangle like in your reference photo - tip pointing in.
        # Black outline is what keeps it vivid on a light wallpaper.
        pal = ANALOG_THEMES[self.analog_theme]
        tip = self._polar(cx, cy, radius - 10, angle)
        rad = math.radians(angle)
        px, py = math.cos(rad), math.sin(rad)
        base_c = self._polar(cx, cy, radius + 2, angle)
        w = 12  # bigger triangles = clearer at a glance, like the Roman clock
        p1 = (base_c[0] + px * w, base_c[1] + py * w)
        p2 = (base_c[0] - px * w, base_c[1] - py * w)
        self.analog_canvas.create_polygon(
            [tip, p1, p2], fill=pal["main"], outline=pal["outline"], width=2.2
        )

    def _draw_subdial(self, cx, cy, radius, current_idx, total, center_text, title):
        c = self.analog_canvas
        pal = ANALOG_THEMES[self.analog_theme]
        # Outer ring - SINGLE outline only, WHITE on all themes like Navy Glory.
        # Global pal["outline"] stays black for gold/white (hands/markers need it),
        # but the 3 small dials use pal["subdial_outline"] = white so they all
        # look like the blue theme.
        c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                      outline=pal.get("subdial_outline", "#FFFFFF"),
                      width=pal.get("subdial_outline_width", 4.2))
        # Ticks
        for i in range(total):
            ang = i * 360.0 / total
            p1 = self._polar(cx, cy, radius - 2, ang)
            p2 = self._polar(cx, cy, radius - 6, ang)
            c.create_line(p1, p2, fill=pal["dark"], width=1)
        # Needle - thin + red, single line (no thick shadow layer)
        needle_ang = current_idx * 360.0 / total
        tip = self._polar(cx, cy, radius - 8, needle_ang)
        c.create_line(cx, cy, tip[0], tip[1], fill=SUBDIAL_NEEDLE, width=1.5, capstyle="round")
        c.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5, fill=pal["main"], outline=pal.get("subdial_outline", "#FFFFFF"))
        # Centre text + tiny title inside the dial - with halo so white text
        # does not vanish on your light feather wallpaper
        # Blue theme fix: white text + white halo = invisible. So for navy only,
        # sub-dial text is deep navy #071A4D with white halo - dark on white, pops on any wallpaper.
        # Gold / White themes fall back to their original colours, unchanged.
        self._text_with_halo(cx, cy - 10, center_text, pal.get("subdial_center", pal["center"]), ("Segoe UI", 10, "bold"))
        self._text_with_halo(cx, cy + 10, title, pal.get("subdial_title", pal["main"]), ("Segoe UI", 6, "bold"))

    def draw_analog_clock(self, now):
        c = self.analog_canvas
        c.delete("all")
        cx = cy = ANALOG_CANVAS // 2  # 150, 150
        outer_r = 132

        # 1) 12 gold triangle markers - frameless, floating on wallpaper
        for h in range(12):
            self._draw_gold_triangle_marker(cx, cy, outer_r, h * 30)

        # 2) Three chronological sub-dials
        #    Left (9 o'clock) = DAY, Right (3 o'clock) = DATE, Bottom (6 o'clock) = MONTH
        #    Top (12 o'clock) is left clear so the 12 marker stays clean.
        sub_r = 36
        dist = 72
        # DAY - Monday=0 .. Sunday=6
        day_cx, day_cy = cx - dist, cy
        self._draw_subdial(day_cx, day_cy, sub_r, now.weekday(), 7,
                           now.strftime("%a").upper(), "DAY")
        # DATE - 1..31
        date_cx, date_cy = cx + dist, cy
        self._draw_subdial(date_cx, date_cy, sub_r, now.day - 1, 31,
                           f"{now.day:02d}", "DATE")
        # MONTH - Jan=0 .. Dec=11
        mon_cx, mon_cy = cx, cy + dist
        self._draw_subdial(mon_cx, mon_cy, sub_r, now.month - 1, 12,
                           now.strftime("%b").upper(), "MONTH")

        # 3) Hands - all gold, like the reference
        # Smooth second hand: use microseconds so it sweeps, not ticks
        sec_frac = now.second + now.microsecond / 1_000_000.0
        min_frac = now.minute + sec_frac / 60.0
        hour_frac = (now.hour % 12) + min_frac / 60.0

        pal = ANALOG_THEMES[self.analog_theme]

        def hand(angle_deg, length, width, colour, tail=0, thin_red=False):
            tip = self._polar(cx, cy, length, angle_deg)
            if thin_red:
                # Main needle (second hand only) - thin + red, single line
                # like the sub-dial needles. No black shadow layer.
                if tail:
                    back = self._polar(cx, cy, -tail, angle_deg)
                    c.create_line(back[0], back[1], tip[0], tip[1],
                                  fill=MAIN_NEEDLE, width=width, capstyle="round")
                else:
                    c.create_line(cx, cy, tip[0], tip[1],
                                  fill=MAIN_NEEDLE, width=width, capstyle="round")
                return
            # Hour / minute - back to gold with black shadow, as in perfect v14
            if tail:
                back = self._polar(cx, cy, -tail, angle_deg)
                c.create_line(back[0], back[1], tip[0], tip[1],
                              fill=pal["outline"], width=width + 3, capstyle="round")
                c.create_line(back[0], back[1], tip[0], tip[1],
                              fill=colour, width=width, capstyle="round")
            else:
                c.create_line(cx, cy, tip[0], tip[1],
                              fill=pal["outline"], width=width + 3, capstyle="round")
                c.create_line(cx, cy, tip[0], tip[1],
                              fill=colour, width=width, capstyle="round")

        hand(hour_frac * 30, 62, 7, pal["main"])          # hour - gold, back to v14
        hand(min_frac * 6, 96, 5, pal["light"])     # minute - gold, back to v14
        hand(sec_frac * 6, 112, 1.5, MAIN_NEEDLE, tail=20, thin_red=True)  # second = main needle - thin red + tail only

        # Centre hub - colour with white outline
        c.create_oval(cx - 12, cy - 12, cx + 12, cy + 12, fill=pal["main"], outline=pal["outline"], width=2.2)
        c.create_oval(cx - 3.5, cy - 3.5, cx + 3.5, cy + 3.5, fill="#0f0f0f", outline="")
        # --- SHINE (fixed): NO big stipple oval anymore ---
        # That big white oval was the bug in your screenshot. Tkinter's
        # stipple="gray25" does NOT mean translucent on Windows - on many
        # builds it renders as a solid white blob covering the face.
        # So shine is now ONLY this tiny safe glint on the hub. Nothing else.
        if self.analog_theme == "navy_glory":
            c.create_oval(cx - 7, cy - 8, cx - 2, cy - 3, fill="white", outline="")

        # 4) Info line under the face
        percent, hours_left, _ = self.calculate_day_progress()
        self.analog_info_label.config(
            text=f"{now.strftime('%A')}  •  {now.strftime('%d %b %Y')}  •  Day {int(percent)}%"
        )

    @staticmethod
    def make_control(parent, text, command):
        widget = tk.Label(
            parent, text=text, fg="#666", bg=parent.cget("bg"),
            font=("Segoe UI", 11), cursor="hand2"
        )
        widget.pack(side="right", padx=(0, 6))
        widget.bind("<Button-1>", lambda _event: command())
        widget.bind("<Enter>", lambda _event: widget.config(fg="white"))
        return widget

    def save_config(self):
        try:
            cfg = {
                "x": self.root.winfo_x(),
                "y": self.root.winfo_y(),
                "opacity": self.opacity_val,
                "pinned": self.is_pinned,
                "topmost": self.is_topmost,
                "sound_enabled": self.sound_enabled,
                "current_note_idx": self.current_note_idx,
                "note_visible": self.note_visible,
                "note_geom": self.note_geom,
                "clock_mode": self.clock_mode,
                "analog_theme": self.analog_theme,
            }
            self._atomic_json_write(CONFIG_PATH, cfg)
            self._atomic_json_write(NOTES_PATH, self.notes_list)
        except (OSError, tk.TclError) as exc:
            print(f"Save failed: {exc}")

    @staticmethod
    def _atomic_json_write(path, data):
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def save_position(self, _event=None):
        if not self.is_pinned:
            self.save_config()

    def click_win(self, event):
        if not self.is_pinned:
            self._drag_offset = (event.x_root - self.root.winfo_x(),
                                 event.y_root - self.root.winfo_y())

    def drag_win(self, event):
        if self.is_pinned:
            return
        dx, dy = self._drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.update_pin_visual()
        self.save_config()
        self.rebuild_menu()

    def update_pin_visual(self):
        self.pin_btn.config(
            text="📍" if self.is_pinned else "📌",
            fg="#ff5c5c" if self.is_pinned else "#666"
        )

    def update_note_visual(self):
        has_notes = any(n.get("text", "").strip() for n in self.notes_list)
        self.note_btn.config(fg="#fbbf24" if has_notes else "#666")

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.update_sound_visual()
        self.save_config()
        self.rebuild_menu()

    def update_sound_visual(self):
        self.sound_btn.config(
            text="🔊" if self.sound_enabled else "🔇",
            fg="#4ade80" if self.sound_enabled else "#666"
        )

    def play_wav(self, path):
        if not os.path.exists(path):
            return
        try:
            if winsound:
                winsound.PlaySound(path, winsound.SND_FILENAME)
            elif sys.platform == "darwin":
                subprocess.run(["afplay", path], check=False)
            else:
                subprocess.run(["aplay", "-q", path], check=False)
        except OSError as exc:
            print(f"Audio playback failed: {exc}")

    def speak_text(self, text):
        try:
            if sys.platform == "win32":
                # PowerShell's -Command argument handling does not reliably expose
                # trailing command-line arguments through $args. Encode the text
                # and decode it inside PowerShell so the spoken message arrives
                # intact and cannot be interpreted as PowerShell code.
                import base64
                encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
                ps = (
                    "Add-Type -AssemblyName System.Speech; "
                    f"$message = [Text.Encoding]::UTF8.GetString(" 
                    f"[Convert]::FromBase64String('{encoded_text}')); "
                    "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$voice.Rate = 0; $voice.Speak($message); "
                    "$voice.Dispose();"
                )
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                    creationflags=flags, capture_output=True, text=True, timeout=45
                )
                if result.returncode != 0:
                    print("Speech failed:", result.stderr.strip() or result.stdout.strip())
            elif sys.platform == "darwin":
                subprocess.run(["say", text], check=False)
            else:
                subprocess.run(["espeak", text], check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Speech failed: {exc}")

    def announce_time(self, now, chime_type, speak=False):
        def worker():
            if chime_type == "noon":
                self.play_wav(CHIME_NOON)
            elif chime_type == "hour":
                self.play_wav(CHIME_HOUR)
            elif chime_type == "quarter":
                self.play_wav(CHIME_QUARTER)
            if speak:
                hour = now.strftime("%I").lstrip("0") or "12"
                if now.hour == 12:
                    time_phrase = "12 noon"
                elif now.hour == 0:
                    time_phrase = "12 midnight"
                else:
                    time_phrase = f"{hour} {now.strftime('%p')}"
                message = (
                    f"The time now is, {time_phrase}. Today is "
                    f"{now.strftime('%A')} {get_ordinal(now.day)} "
                    f"{now.strftime('%B')}."
                )
                self.speak_text(message)

        threading.Thread(target=worker, daemon=True).start()

    def test_announcement(self):
        now = datetime.now()

        def worker():
            self.play_wav(CHIME_HOUR)
            hour = now.strftime("%I").lstrip("0") or "12"
            minute = now.strftime("%M")
            time_text = f"{hour} {now.strftime('%p')}"
            if minute != "00":
                time_text = f"{hour} {minute} {now.strftime('%p')}"
            message = (
                f"The time now is, {time_text}. Today is "
                f"{now.strftime('%A')} {get_ordinal(now.day)} "
                f"{now.strftime('%B')}."
            )
            self.speak_text(message)

        threading.Thread(target=worker, daemon=True).start()

    def check_clock_chimes(self, now):
        if not self.sound_enabled or now.second > 2:
            return
        if now.minute not in (0, 15, 30, 45):
            return
        slot = (now.year, now.month, now.day, now.hour, now.minute)
        if slot == self.last_announced_slot:
            return
        self.last_announced_slot = slot
        if now.minute:
            self.announce_time(now, "quarter")
        else:
            self.announce_time(now, "noon" if now.hour in (0, 12) else "hour", True)

    def calculate_day_progress(self):
        now = datetime.now()
        seconds = now.hour * 3600 + now.minute * 60 + now.second
        if seconds < DAY_START_SEC:
            percent = 0
            hours_left = (DAY_END_SEC - DAY_START_SEC) / 3600
        elif seconds >= DAY_END_SEC:
            percent, hours_left = 100, 0
        else:
            percent = (seconds - DAY_START_SEC) / DAY_TOTAL_SEC * 100
            hours_left = (DAY_END_SEC - seconds) / 3600
        return percent, hours_left, now

    def draw_progress_ring(self, percent):
        self.progress_canvas.delete("all")
        cx = cy = 11
        radius = 8
        self.progress_canvas.create_oval(
            cx-radius, cy-radius, cx+radius, cy+radius,
            outline="#2a2a2a", width=1.5
        )
        if percent > 0:
            self.progress_canvas.create_arc(
                cx-radius, cy-radius, cx+radius, cy+radius,
                start=90, extent=-percent * 3.6,
                outline="#ef4444", width=2, style="arc"
            )

    def show_progress_tooltip(self, event=None):
        self.hide_tooltip()
        _percent, hours_left, _now = self.calculate_day_progress()
        if hours_left <= 0:
            message = "Day complete! (6am-6pm)"
        elif hours_left < 1:
            message = f"{int(hours_left * 60)} min left today"
        else:
            message = f"{hours_left:.1f} hours left today"

        self.tooltip_window = tk.Toplevel(self.root)
        self.tooltip_window.overrideredirect(True)
        self.tooltip_window.attributes("-topmost", True)
        self.tooltip_window.configure(bg="#1f1f1f")
        tk.Label(
            self.tooltip_window, text=message, bg="#1f1f1f",
            fg="#ef4444", font=("Segoe UI", 9, "bold"), padx=10, pady=6
        ).pack()
        x = event.x_root + 10 if event else self.root.winfo_x() + 40
        y = event.y_root + 10 if event else self.root.winfo_y() + 70
        self.tooltip_window.geometry(f"+{x}+{y}")
        self.root.after(3000, self.hide_tooltip)

    def hide_tooltip(self):
        if self.tooltip_window:
            try:
                if self.tooltip_window.winfo_exists():
                    self.tooltip_window.destroy()
            except tk.TclError:
                pass
            self.tooltip_window = None

    def toggle_notes(self):
        if self.note_window and self.note_window.winfo_exists():
            self.hide_notes()
        else:
            self.show_notes()

    def toggle_calendar_notes(self):
        if self.calendar_notes:
            try:
                self.calendar_notes.toggle()
            except Exception as exc:
                print(f"Calendar Notes open failed: {exc}")
        else:
            print("Calendar Notes is not loaded - check calendar_notes.py import error above")

    def _on_calendar_reminder(self, note):
        if not self.calendar_notes:
            print("Calendar reminder: calendar_notes is None, cannot show")
            return
        try:
            for idx, item in enumerate(self.calendar_notes.notes_list):
                if item.get("text") == note.get("text") and item.get("date") == note.get("date") and item.get("time") == note.get("time"):
                    self.calendar_notes.current_idx = idx
                    break
        except (AttributeError, TypeError):
            pass

        def _show():
            try:
                if not (self.calendar_notes.window and self.calendar_notes.window.winfo_exists()):
                    self.calendar_notes.show()
                else:
                    self.calendar_notes.refresh_display()
                    self.calendar_notes.window.lift()
                    self.calendar_notes.window.attributes("-topmost", True)
            except Exception as exc:
                print(f"Calendar reminder show failed: {exc}")
        self.root.after(0, _show)

        def worker():
            if self.sound_enabled:
                self.play_wav(CHIME_HOUR)
                text = str(note.get("text", "")).strip().replace("\n", " ")
                if text:
                    self.speak_text(f"Reminder: {text}")
        threading.Thread(target=worker, daemon=True).start()

    def show_notes(self):
        if self.note_window and self.note_window.winfo_exists():
            self.note_window.lift()
            return

        self.note_window = tk.Toplevel(self.root)
        self.note_window.overrideredirect(True)
        self.note_window.attributes("-topmost", self.is_topmost)
        self.note_window.attributes("-alpha", 0.97)
        default_geometry = (
            f"260x200+{self.root.winfo_x()+240}+{self.root.winfo_y()}"
        )
        try:
            self.note_window.geometry(self.note_geom or default_geometry)
        except tk.TclError:
            self.note_window.geometry(default_geometry)

        self.note_header = tk.Frame(self.note_window, height=30)
        self.note_header.pack(fill="x")
        self.note_header.bind("<Button-1>", self.start_note_drag)
        self.note_header.bind("<B1-Motion>", self.do_note_drag)

        self.note_nav = tk.Frame(self.note_header)
        self.note_nav.pack(side="left", padx=4)

        self.prev_btn = tk.Label(self.note_nav, text="◀", cursor="hand2")
        self.prev_btn.pack(side="left", padx=2)
        self.prev_btn.bind("<Button-1>", lambda _e: self.browse_note(-1))

        self.note_count_label = tk.Label(self.note_nav, font=("Segoe UI", 9, "bold"))
        self.note_count_label.pack(side="left", padx=4)

        self.next_btn = tk.Label(self.note_nav, text="▶", cursor="hand2")
        self.next_btn.pack(side="left", padx=2)
        self.next_btn.bind("<Button-1>", lambda _e: self.browse_note(1))

        self.add_btn = tk.Label(self.note_nav, text="＋", cursor="hand2")
        self.add_btn.pack(side="left", padx=(6, 2))
        self.add_btn.bind("<Button-1>", lambda _e: self.add_new_note())

        self.note_actions = tk.Frame(self.note_header)
        self.note_actions.pack(side="right", padx=4)
        self.delete_btn = tk.Label(self.note_actions, text="🗑", cursor="hand2")
        self.delete_btn.pack(side="left", padx=4)
        self.delete_btn.bind("<Button-1>", lambda _e: self.delete_current_note())
        self.note_close_btn = tk.Label(self.note_actions, text="✕", cursor="hand2")
        self.note_close_btn.pack(side="left", padx=4)
        self.note_close_btn.bind("<Button-1>", lambda _e: self.hide_notes())

        self.note_text_widget = tk.Text(
            self.note_window, font=("Segoe UI", 10), bd=0,
            padx=10, pady=8, wrap="word", highlightthickness=0
        )
        self.note_text_widget.pack(fill="both", expand=True)
        self.note_text_widget.bind("<KeyRelease>", lambda _e: self.save_current_note_text())

        self.note_footer = tk.Frame(self.note_window, height=26)
        self.note_footer.pack(fill="x", pady=(0, 4))
        self.status_label = tk.Label(
            self.note_footer, text="Saved", font=("Segoe UI", 7)
        )
        self.status_label.pack(side="right", padx=8)
        tk.Label(
            self.note_footer, text="Color:", font=("Segoe UI", 8)
        ).pack(side="left", padx=8)

        for index, color in enumerate(NOTE_COLORS):
            dot = tk.Label(
                self.note_footer, text="●", fg=color["header"],
                cursor="hand2", font=("Segoe UI", 14)
            )
            dot.pack(side="left", padx=2)
            dot.bind(
                "<Button-1>",
                lambda _e, color_index=index: self.change_note_color(color_index)
            )

        self.note_visible = True
        self.refresh_note_display()
        self.note_text_widget.focus_set()
        self.save_config()

    def apply_note_colors(self):
        note = self.notes_list[self.current_note_idx]
        color = NOTE_COLORS[note.get("color_idx", 0) % len(NOTE_COLORS)]
        self.note_window.configure(bg=color["bg"])
        self.note_header.configure(bg=color["header"])
        self.note_nav.configure(bg=color["header"])
        self.note_actions.configure(bg=color["header"])
        for widget in (
            self.prev_btn, self.note_count_label, self.next_btn, self.add_btn,
            self.delete_btn, self.note_close_btn
        ):
            widget.configure(bg=color["header"], fg=color["fg"])
        self.note_text_widget.configure(
            bg=color["bg"], fg=color["fg"], insertbackground=color["fg"]
        )
        self.note_footer.configure(bg=color["bg"])
        for widget in self.note_footer.winfo_children():
            if widget.winfo_class() == "Label" and widget.cget("text") != "●":
                widget.configure(bg=color["bg"], fg=color["fg"])

    def hide_notes(self):
        if self.note_window:
            try:
                self.note_geom = self.note_window.geometry()
                self.save_current_note_text()
                self.note_window.destroy()
            except tk.TclError:
                pass
        self.note_window = None
        self.note_text_widget = None
        self.note_visible = False
        self.save_config()

    def start_note_drag(self, event):
        self._note_drag_offset = (event.x_root - self.note_window.winfo_x(),
                                  event.y_root - self.note_window.winfo_y())

    def do_note_drag(self, event):
        if not self.note_window:
            return
        dx, dy = self._note_drag_offset
        self.note_window.geometry(f"+{event.x_root-dx}+{event.y_root-dy}")

    def save_current_note_text(self):
        if not self.note_text_widget:
            return
        try:
            text = self.note_text_widget.get("1.0", "end-1c")
            if text != self.notes_list[self.current_note_idx].get("text", ""):
                self.notes_list[self.current_note_idx]["text"] = text
                self.last_saved_text = text
                self.update_note_visual()
                self.save_config()
                if self.status_label.winfo_exists():
                    self.status_label.config(text="Saved ✓")
                    self.root.after(
                        1000,
                        lambda: self.status_label.config(text="Saved")
                        if self.status_label and self.status_label.winfo_exists()
                        else None
                    )
        except tk.TclError:
            pass

    def auto_save_loop(self):
        if self.note_window and self.note_text_widget:
            self.save_current_note_text()
        try:
            self.root.after(1000, self.auto_save_loop)
        except tk.TclError:
            pass

    def browse_note(self, direction):
        self.save_current_note_text()
        self.current_note_idx = (
            self.current_note_idx + direction
        ) % len(self.notes_list)
        self.refresh_note_display()

    def refresh_note_display(self):
        if not self.note_window or not self.note_text_widget:
            return
        note = self.notes_list[self.current_note_idx]
        self.apply_note_colors()
        self.note_text_widget.delete("1.0", "end")
        self.note_text_widget.insert("1.0", note.get("text", ""))
        self.last_saved_text = note.get("text", "")
        self.note_count_label.config(
            text=f"{self.current_note_idx + 1} / {len(self.notes_list)}"
        )
        self.save_config()

    def add_new_note(self):
        self.save_current_note_text()
        color_index = len(self.notes_list) % len(NOTE_COLORS)
        self.notes_list.append({"text": "", "color_idx": color_index})
        self.current_note_idx = len(self.notes_list) - 1
        self.refresh_note_display()
        self.note_text_widget.focus_set()

    def delete_current_note(self):
        if len(self.notes_list) <= 1:
            self.notes_list[0]["text"] = ""
        else:
            del self.notes_list[self.current_note_idx]
            self.current_note_idx = min(
                self.current_note_idx, len(self.notes_list) - 1
            )
        self.refresh_note_display()
        self.update_note_visual()
        self.save_config()

    def change_note_color(self, index):
        self.notes_list[self.current_note_idx]["color_idx"] = index
        self.refresh_note_display()

    def set_opacity_preset(self, value):
        self.opacity_val = value
        if self.clock_mode == "analog":
            # Analog uses -transparentcolor, not -alpha, so keep it crisp.
            # Opacity is still saved and will apply when you switch back to digital.
            pass
        else:
            self.root.attributes("-alpha", value)
        self.save_config()

    def toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.root.attributes("-topmost", self.is_topmost)
        if self.note_window:
            self.note_window.attributes("-topmost", self.is_topmost)
        if self.calendar_notes:
            self.calendar_notes.sync_topmost()
        self.rebuild_menu()
        self.save_config()

    def rebuild_menu(self):
        self.menu.delete(0, "end")
        self.menu.add_command(
            label="◷ Switch to Analog Clock" if self.clock_mode == "digital"
            else "◧ Switch to Digital Clock",
            command=self.toggle_clock_mode
        )
        # Show current theme, clicking cycles to the next one
        _next_idx = (THEME_ORDER.index(self.analog_theme) + 1) % len(THEME_ORDER) if self.analog_theme in THEME_ORDER else 0
        _next_label = ANALOG_THEMES[THEME_ORDER[_next_idx]]["label"]
        _cur_label = ANALOG_THEMES.get(self.analog_theme, {}).get("label", self.analog_theme)
        self.menu.add_command(
            label=f"🎨 Analog Color ",
            command=self.toggle_analog_theme
        )
        self.menu.add_separator()
        self.menu.add_command(
            label="🔊 Talking Clock: ON" if self.sound_enabled
            else "🔇 Talking Clock: OFF",
            command=self.toggle_sound
        )
        self.menu.add_command(
            label="🔔 Test Chime & Voice", command=self.test_announcement
        )
        self.menu.add_separator()
        for value, label in (
            (1.0, "Opacity 100%"),
            (0.9, "Opacity 90%"),
            (0.7, "Opacity 70%"),
        ):
            self.menu.add_command(
                label=label, command=lambda v=value: self.set_opacity_preset(v)
            )
        self.menu.add_separator()
        self.menu.add_command(label="📝 Floating Notes", command=self.toggle_notes)
        self.menu.add_command(label="📅 Calendar Notes", command=self.toggle_calendar_notes)
        self.menu.add_separator()
        self.menu.add_command(
            label="📍 Unpin Position" if self.is_pinned else "📌 Pin Position",
            command=self.toggle_pin
        )
        self.menu.add_command(
            label="✓ Always on top" if self.is_topmost else "Always on top",
            command=self.toggle_topmost
        )
        self.menu.add_separator()
        self.menu.add_command(label="Close", command=self.close_app)

    def show_menu(self, event):
        # FIX: double-click menu bug - two causes, both fixed here
        # 1) <Button-3> was bound on BOTH root AND analog_canvas. A right-click
        #    on the canvas bubbled to root, so show_menu() ran TWICE, posting
        #    the menu twice. The 2nd post cancelled the 1st grab, so the 1st
        #    click on any item was swallowed and you needed a 2nd click.
        #    Returning "break" stops the bubbling, so it only posts once.
        # 2) tk_popup() + grab_release() in finally: on Windows tk_popup()
        #    returns immediately, so grab_release() ran BEFORE you clicked,
        #    stealing the grab. menu.post() does not have that problem.
        self.rebuild_menu()
        try:
            self.menu.post(event.x_root, event.y_root)
        except Exception:
            pass
        return "break"

    def close_app(self):
        if self.note_window:
            try:
                self.note_geom = self.note_window.geometry()
            except tk.TclError:
                pass
            self.save_current_note_text()
        if self.calendar_notes:
            try:
                if self.calendar_notes.window and self.calendar_notes.window.winfo_exists():
                    self.calendar_notes.geom = self.calendar_notes.window.geometry()
                self.calendar_notes.save_current()
                self.calendar_notes.save()
            except tk.TclError:
                pass
        self.save_config()
        self.root.destroy()

    def update_time(self):
        now = datetime.now()
        self.check_clock_chimes(now)
        if self.calendar_notes:
            self.calendar_notes.check_due(now)
        if self.clock_mode == "analog":
            self.draw_analog_clock(now)
            # Keep digital labels in sync too, so switching back is instant
            self.month_label.config(text=now.strftime("%b").upper())
            self.date_label.config(text=now.strftime("%d"))
            self.weekday_label.config(text=now.strftime("%A"))
            self.hour_label.config(text=now.strftime("%H"))
            self.minute_label.config(text=now.strftime("%M"))
            # 200ms = smooth sweeping second hand
            self.root.after(200, self.update_time)
        else:
            self.month_label.config(text=now.strftime("%b").upper())
            self.date_label.config(text=now.strftime("%d"))
            self.weekday_label.config(text=now.strftime("%A"))
            self.hour_label.config(text=now.strftime("%H"))
            self.minute_label.config(text=now.strftime("%M"))
            percent, _hours_left, _now = self.calculate_day_progress()
            self.progress_percent_label.config(text=f"{int(percent)}%")
            self.draw_progress_ring(percent)
            self.root.after(1000, self.update_time)


if __name__ == "__main__":
    root = tk.Tk()
    app = DateTimeBox(root)
    root.mainloop()
