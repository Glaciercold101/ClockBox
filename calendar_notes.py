import json
import os
import sys
import tkinter as tk
from datetime import date, datetime

CALENDAR_COLORS = [
    {"bg": "#fef3c7", "header": "#fde68a", "fg": "#92400e"},
    {"bg": "#fce7f3", "header": "#f9a8d4", "fg": "#831843"},
    {"bg": "#dcfce7", "header": "#86efac", "fg": "#14532d"},
    {"bg": "#dbeafe", "header": "#93c5fd", "fg": "#1e3a8a"},
    {"bg": "#ffedd5", "header": "#fdba74", "fg": "#7c2d12"},
    {"bg": "#e0e7ff", "header": "#a5b4fc", "fg": "#312e81"},
]

REPEAT_OPTIONS = ["once", "daily", "weekly", "monthly", "yearly"]
REPEAT_LABELS = {
    "once": "Once",
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "yearly": "Yearly",
}


def default_storage_path():
    if sys.platform == "win32" and os.getenv("APPDATA"):
        folder = os.path.join(os.getenv("APPDATA"), "DateTimeBox")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".datetimebox")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "calendar_notes.json")


def parse_date(value, fallback=None):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return fallback or date.today()


def parse_time(value, fallback="09:00"):
    try:
        raw = str(value).strip().lower()
        is_pm = "pm" in raw
        is_am = "am" in raw
        raw = raw.replace("am", "").replace("pm", "").strip()
        for sep in [".", ",", " ", "-", ";", "/"]:
            raw = raw.replace(sep, ":")
        parts = [p for p in raw.split(":") if p != ""]
        if not parts:
            return fallback
        if len(parts) == 1:
            p = parts[0]
            if len(p) == 4 and p.isdigit():
                hour, minute = int(p[:2]), int(p[2:])
            elif len(p) == 3 and p.isdigit():
                hour, minute = int(p[:1]), int(p[1:])
            elif p.isdigit():
                hour, minute = int(p), 0
            else:
                return fallback
        else:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        if is_pm and hour < 12:
            hour += 12
        if is_am and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        pass
    return fallback


class CalendarNotesManager:
    def __init__(self, root, on_reminder=None, storage_path=None, get_topmost=None):
        self.root = root
        self.on_reminder = on_reminder
        self.storage_path = storage_path or default_storage_path()
        self.get_topmost = get_topmost
        self.notes_list = []
        self.current_idx = 0
        self.visible = False
        self.geom = ""
        self.window = None
        self.text_widget = None
        self.status_label = None
        self.date_button = None
        self.time_entry = None
        self.repeat_var = None
        self.enabled_var = None
        self.calendar_popup = None
        self._cal_frame = None
        self._quick = None
        self.calendar_visible = True
        self.popup_year = date.today().year
        self.popup_month = date.today().month
        self._drag_offset = (0, 0)
        self._updating = False
        self.load()

    def load(self):
        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError):
            data = {}
        if isinstance(data, list):
            raw_list = data
            meta = {}
        elif isinstance(data, dict):
            raw_list = data.get("notes", [])
            meta = data
        else:
            raw_list = []
            meta = {}
        today = date.today().isoformat()
        cleaned = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            cleaned.append({
                "text": str(item.get("text", "")),
                "date": parse_date(item.get("date", today), date.today()).isoformat(),
                "time": parse_time(item.get("time", "09:00")),
                "repeat": item.get("repeat", "once") if item.get("repeat") in REPEAT_OPTIONS else "once",
                "enabled": bool(item.get("enabled", True)),
                "color_idx": int(item.get("color_idx", 0)) if str(item.get("color_idx", 0)).lstrip("-").isdigit() else 0,
                "last_fired": str(item.get("last_fired", "")),
            })
        self.notes_list = cleaned or [{
            "text": "", "date": today, "time": "09:00",
            "repeat": "once", "enabled": True, "color_idx": 0, "last_fired": "",
        }]
        self.current_idx = max(0, min(int(meta.get("current_idx", 0)), len(self.notes_list) - 1)) if isinstance(meta, dict) else 0
        self.visible = bool(meta.get("visible", False)) if isinstance(meta, dict) else False
        self.geom = str(meta.get("geom", "")) if isinstance(meta, dict) else ""

    def save(self):
        try:
            data = {
                "notes": self.notes_list,
                "current_idx": self.current_idx,
                "visible": self.visible,
                "geom": self.geom,
            }
            temporary = self.storage_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.storage_path)
        except OSError:
            pass

    def current_note(self):
        if not self.notes_list:
            self.notes_list = [{
                "text": "", "date": date.today().isoformat(), "time": "09:00",
                "repeat": "once", "enabled": True, "color_idx": 0, "last_fired": "",
            }]
        return self.notes_list[self.current_idx]

    def toggle(self):
        try:
            is_open = bool(self.window and self.window.winfo_exists())
        except tk.TclError:
            is_open = False
            self.window = None
        if is_open:
            self.hide()
        else:
            self.show()

    def show(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", self.get_topmost() if self.get_topmost else True)
        self.window.attributes("-alpha", 0.97)
        default_geom = f"300x600+{self.root.winfo_x() + 500}+{self.root.winfo_y()}"
        try:
            self.window.geometry(self.geom or default_geom)
        except tk.TclError:
            self.window.geometry(default_geom)
        header = tk.Frame(self.window, height=30)
        header.pack(fill="x")
        header.bind("<Button-1>", self._start_drag)
        header.bind("<B1-Motion>", self._do_drag)
        self._header = header
        nav = tk.Frame(header)
        nav.pack(side="left", padx=4)
        self._nav = nav
        prev_btn = tk.Label(nav, text="◀", cursor="hand2")
        prev_btn.pack(side="left", padx=2)
        prev_btn.bind("<Button-1>", lambda _e: self.browse(-1))
        self.prev_btn = prev_btn
        self.count_label = tk.Label(nav, font=("Segoe UI", 9, "bold"))
        self.count_label.pack(side="left", padx=4)
        next_btn = tk.Label(nav, text="▶", cursor="hand2")
        next_btn.pack(side="left", padx=2)
        next_btn.bind("<Button-1>", lambda _e: self.browse(1))
        self.next_btn = next_btn
        add_btn = tk.Label(nav, text="＋", cursor="hand2")
        add_btn.pack(side="left", padx=(6, 2))
        add_btn.bind("<Button-1>", lambda _e: self.add_new())
        self.add_btn = add_btn
        title = tk.Label(nav, text="📅", cursor="hand2")
        title.pack(side="left", padx=(6, 0))
        actions = tk.Frame(header)
        actions.pack(side="right", padx=4)
        self._actions = actions
        delete_btn = tk.Label(actions, text="🗑", cursor="hand2")
        delete_btn.pack(side="left", padx=4)
        delete_btn.bind("<Button-1>", lambda _e: self.delete_current())
        self.delete_btn = delete_btn
        close_btn = tk.Label(actions, text="✕", cursor="hand2")
        close_btn.pack(side="left", padx=4)
        close_btn.bind("<Button-1>", lambda _e: self.hide())
        self.close_btn = close_btn
        controls = tk.Frame(self.window)
        controls.pack(fill="x", padx=6, pady=(6, 2))
        self._controls = controls
        self.date_button = tk.Button(
            controls, text="", font=("Segoe UI", 9, "bold"),
            cursor="hand2", relief="solid", bd=1, command=self.open_calendar_popup
        )
        self.date_button.pack(side="left", padx=(0, 4))
        tk.Label(controls, text="at", font=("Segoe UI", 9)).pack(side="left")
        self.time_entry = tk.Entry(controls, width=6, font=("Segoe UI", 9), justify="center")
        self.time_entry.pack(side="left", padx=4)
        self.time_entry.bind("<FocusOut>", lambda _e: self.save_current_and_normalise())
        self.time_entry.bind("<Return>", lambda _e: self.save_current_and_normalise())
        self.time_entry.bind("<KeyRelease>", lambda _e: self.save_current())
        self.repeat_var = tk.StringVar(value="once")
        repeat_menu = tk.OptionMenu(controls, self.repeat_var, *[REPEAT_LABELS[v] for v in REPEAT_OPTIONS], command=lambda _v: self.save_current())
        repeat_menu.config(font=("Segoe UI", 8), bd=1, relief="solid", cursor="hand2")
        repeat_menu.pack(side="left", padx=2)
        self.repeat_menu = repeat_menu
        self.enabled_var = tk.BooleanVar(value=True)
        enabled_check = tk.Checkbutton(
            controls, text="🔔", variable=self.enabled_var,
            font=("Segoe UI", 9), cursor="hand2", command=self.save_current
        )
        enabled_check.pack(side="left", padx=2)
        self.enabled_check = enabled_check
        self.text_widget = tk.Text(
            self.window, font=("Segoe UI", 10), bd=0,
            padx=10, pady=8, wrap="word", highlightthickness=0
        )
        self.text_widget.pack(fill="both", expand=True)
        self.text_widget.bind("<KeyRelease>", lambda _e: self.save_current())
        footer = tk.Frame(self.window, height=26)
        footer.pack(fill="x", pady=(0, 4))
        self._footer = footer
        self.status_label = tk.Label(footer, text="Saved", font=("Segoe UI", 7))
        self.status_label.pack(side="right", padx=8)
        tk.Label(footer, text="Color:", font=("Segoe UI", 8)).pack(side="left", padx=8)
        self._color_dots = []
        for index, color in enumerate(CALENDAR_COLORS):
            dot = tk.Label(footer, text="●", fg=color["header"], cursor="hand2", font=("Segoe UI", 14))
            dot.pack(side="left", padx=2)
            dot.bind("<Button-1>", lambda _e, idx=index: self.change_color(idx))
            self._color_dots.append(dot)
        # Quick actions + inline calendar - created LAST, after text/footer exist,
        # so refresh_display / _build_calendar_grid can never crash the open.
        try:
            quick = tk.Frame(self.window)
            quick.pack(fill="x", padx=6, pady=(2, 0), before=self.text_widget)
            self._quick = quick
            tk.Button(quick, text="+1 min", font=("Segoe UI", 8, "bold"), cursor="hand2", relief="solid", bd=1, command=self.set_plus_one_min).pack(side="left", padx=(0, 4))
            tk.Button(quick, text="Test bell + voice", font=("Segoe UI", 8, "bold"), cursor="hand2", relief="solid", bd=1, command=self.test_reminder).pack(side="left")
            self._cal_frame = tk.Frame(self.window, bg="white", bd=1, relief="solid")
            # Created after footer so all widgets exist, but packed BEFORE the
            # text box so it sits between the controls and the text, as intended.
            self._cal_frame.pack(fill="x", padx=6, pady=(4, 4), before=self.text_widget)
            _sel = parse_date(self.current_note().get("date"), date.today())
            self.popup_year = _sel.year
            self.popup_month = _sel.month
            self._build_calendar_grid()
        except Exception as exc:
            print(f"Calendar grid failed, opening notes without it: {exc}")
            self._cal_frame = None
        self.visible = True
        self.refresh_display()
        self.text_widget.focus_set()
        self.save()

    def apply_colors(self):
        if not self.window:
            return
        note = self.current_note()
        color = CALENDAR_COLORS[note.get("color_idx", 0) % len(CALENDAR_COLORS)]
        self.window.configure(bg=color["bg"])
        self._header.configure(bg=color["header"])
        self._nav.configure(bg=color["header"])
        self._actions.configure(bg=color["header"])
        for widget in (self.prev_btn, self.count_label, self.next_btn, self.add_btn, self.delete_btn, self.close_btn):
            widget.configure(bg=color["header"], fg=color["fg"])
        self._controls.configure(bg=color["bg"])
        try:
            if getattr(self, "_quick", None) is not None:
                self._quick.configure(bg=color["bg"])
        except tk.TclError:
            pass
        self.date_button.configure(bg="white", fg=color["fg"], activebackground=color["header"])
        self.text_widget.configure(bg=color["bg"], fg=color["fg"], insertbackground=color["fg"])
        self._footer.configure(bg=color["bg"])
        for widget in self._footer.winfo_children():
            if widget.winfo_class() == "Label" and widget.cget("text") != "●":
                widget.configure(bg=color["bg"], fg=color["fg"])

    def refresh_display(self):
        if not self.window or not self.text_widget:
            return
        self._updating = True
        try:
            note = self.current_note()
            self.apply_colors()
            self.text_widget.delete("1.0", "end")
            self.text_widget.insert("1.0", note.get("text", ""))
            shown_date = parse_date(note.get("date"), date.today())
            self.date_button.config(text=shown_date.strftime("%a %d %b %Y"))
            self.time_entry.delete(0, "end")
            self.time_entry.insert(0, note.get("time", "09:00"))
            label = REPEAT_LABELS.get(note.get("repeat", "once"), "Once")
            self.repeat_var.set(label)
            self.enabled_var.set(bool(note.get("enabled", True)))
            self.count_label.config(text=f"{self.current_idx + 1} / {len(self.notes_list)}")
            self._update_status()
            if self._cal_frame is not None:
                try:
                    self._build_calendar_grid()
                except Exception as exc:
                    print(f"Calendar grid rebuild failed: {exc}")
        finally:
            self._updating = False

    def save_current(self):
        if not self.text_widget or self._updating:
            return
        try:
            note = self.current_note()
            text = self.text_widget.get("1.0", "end-1c")
            time_value = parse_time(self.time_entry.get(), note.get("time", "09:00"))
            repeat_label_to_value = {v: k for k, v in REPEAT_LABELS.items()}
            repeat_value = repeat_label_to_value.get(self.repeat_var.get(), "once")
            changed = (
                text != note.get("text", "")
                or time_value != note.get("time", "09:00")
                or repeat_value != note.get("repeat", "once")
                or bool(self.enabled_var.get()) != bool(note.get("enabled", True))
            )
            note["text"] = text
            note["time"] = time_value
            note["repeat"] = repeat_value
            note["enabled"] = bool(self.enabled_var.get())
            if changed:
                self.save()
            self._update_status()
        except tk.TclError:
            pass

    def save_current_and_normalise(self):
        self.save_current()
        try:
            if self.time_entry and self.time_entry.winfo_exists():
                stored = self.current_note().get("time", "09:00")
                if self.time_entry.get() != stored:
                    self._updating = True
                    try:
                        self.time_entry.delete(0, "end")
                        self.time_entry.insert(0, stored)
                    finally:
                        self._updating = False
        except tk.TclError:
            pass

    def browse(self, direction):
        self.save_current()
        self.current_idx = (self.current_idx + direction) % len(self.notes_list)
        self.refresh_display()
        self.save()

    def add_new(self):
        self.save_current()
        color_index = len(self.notes_list) % len(CALENDAR_COLORS)
        self.notes_list.append({
            "text": "", "date": date.today().isoformat(), "time": "09:00",
            "repeat": "once", "enabled": True, "color_idx": color_index, "last_fired": "",
        })
        self.current_idx = len(self.notes_list) - 1
        self.refresh_display()
        self.save()
        if self.text_widget:
            self.text_widget.focus_set()

    def delete_current(self):
        if len(self.notes_list) <= 1:
            self.notes_list[0].update({"text": "", "enabled": True, "repeat": "once", "last_fired": ""})
        else:
            del self.notes_list[self.current_idx]
            self.current_idx = min(self.current_idx, len(self.notes_list) - 1)
        self.refresh_display()
        self.save()

    def change_color(self, index):
        self.current_note()["color_idx"] = index
        self.refresh_display()
        self.save()

    def hide(self):
        if self.window:
            try:
                self.geom = self.window.geometry()
                self.save_current()
                self.window.destroy()
            except tk.TclError:
                pass
        self.window = None
        self.text_widget = None
        self._cal_frame = None
        self._quick = None
        self.visible = False
        self.close_calendar_popup()
        self.save()

    def sync_topmost(self):
        if self.window and self.window.winfo_exists():
            try:
                self.window.attributes("-topmost", self.get_topmost() if self.get_topmost else True)
            except tk.TclError:
                pass

    def _start_drag(self, event):
        if not self.window:
            return
        self._drag_offset = (event.x_root - self.window.winfo_x(), event.y_root - self.window.winfo_y())

    def _do_drag(self, event):
        if not self.window:
            return
        dx, dy = self._drag_offset
        self.window.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _update_status(self):
        try:
            if not self.status_label:
                return
            if not self.status_label.winfo_exists():
                return
            note = self.current_note()
            label = REPEAT_LABELS.get(note.get("repeat", "once"), "Once")
            bell = "ON" if note.get("enabled", True) else "OFF"
            shown = parse_date(note.get("date"), date.today()).strftime("%a %d %b")
            self.status_label.config(text=f"{shown} {note.get('time', '09:00')} {label} Bell {bell}")
        except Exception:
            pass

    def set_plus_one_min(self):
        self.save_current()
        from datetime import timedelta
        nxt = datetime.now() + timedelta(minutes=1)
        note = self.current_note()
        note["date"] = nxt.date().isoformat()
        note["time"] = nxt.strftime("%H:%M")
        note["enabled"] = True
        self.popup_year = nxt.year
        self.popup_month = nxt.month
        self.save()
        self.refresh_display()

    def test_reminder(self):
        self.save_current()
        if self.on_reminder:
            self.on_reminder(dict(self.current_note()))

    def open_calendar_popup(self):
        if self._cal_frame is None:
            return
        try:
            if self.calendar_visible:
                self._cal_frame.pack_forget()
                self.calendar_visible = False
            else:
                try:
                    self._cal_frame.pack(fill="x", padx=6, pady=(4, 4), before=self.text_widget)
                except tk.TclError:
                    self._cal_frame.pack(fill="x", padx=6, pady=(4, 4))
                self.calendar_visible = True
                _sel = parse_date(self.current_note().get("date"), date.today())
                self.popup_year = _sel.year
                self.popup_month = _sel.month
                self._build_calendar_grid()
        except Exception as exc:
            print(f"Calendar toggle failed: {exc}")

    def _build_calendar_grid(self):
        frame = self._cal_frame
        if frame is None:
            return
        try:
            if not frame.winfo_exists():
                return
        except tk.TclError:
            return
        for child in frame.winfo_children():
            child.destroy()
        header = tk.Frame(frame, bg="#1e3a8a")
        header.pack(fill="x")
        prev_btn = tk.Label(header, text="◀", fg="white", bg="#1e3a8a", cursor="hand2", font=("Segoe UI", 10, "bold"))
        prev_btn.pack(side="left", padx=8, pady=6)
        prev_btn.bind("<Button-1>", lambda _e: self._shift_calendar_month(-1))
        title = tk.Label(header, text=datetime(self.popup_year, self.popup_month, 1).strftime("%B %Y"), fg="white", bg="#1e3a8a", font=("Segoe UI", 10, "bold"))
        title.pack(side="left", expand=True)
        next_btn = tk.Label(header, text="▶", fg="white", bg="#1e3a8a", cursor="hand2", font=("Segoe UI", 10, "bold"))
        next_btn.pack(side="right", padx=8, pady=6)
        next_btn.bind("<Button-1>", lambda _e: self._shift_calendar_month(1))
        close_btn = tk.Label(header, text="✕", fg="white", bg="#1e3a8a", cursor="hand2")
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda _e: self.open_calendar_popup())
        weekdays = tk.Frame(frame, bg="white")
        weekdays.pack(fill="x", padx=6, pady=(6, 2))
        for idx, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            tk.Label(weekdays, text=name, font=("Segoe UI", 8, "bold"), bg="white", fg="#64748b", width=5).grid(row=0, column=idx)
        grid = tk.Frame(frame, bg="white")
        grid.pack(fill="x", padx=6, pady=4)
        first = date(self.popup_year, self.popup_month, 1)
        start_offset = first.weekday()
        if self.popup_month == 12:
            next_first = date(self.popup_year + 1, 1, 1)
        else:
            next_first = date(self.popup_year, self.popup_month + 1, 1)
        days_in_month = (next_first - first).days
        selected = parse_date(self.current_note().get("date"), date.today())
        today = date.today()
        for cell in range(42):
            row, col = divmod(cell, 7)
            day_num = cell - start_offset + 1
            if 1 <= day_num <= days_in_month:
                cell_date = date(self.popup_year, self.popup_month, day_num)
                is_selected = cell_date == selected
                is_today = cell_date == today
                btn = tk.Button(
                    grid, text=str(day_num), width=5,
                    font=("Segoe UI", 10, "bold") if is_selected or is_today else ("Segoe UI", 10),
                    bg="#1e3a8a" if is_selected else ("#dbeafe" if is_today else "white"),
                    fg="white" if is_selected else ("#1e3a8a" if is_today else "black"),
                    activebackground="#1e3a8a", activeforeground="white",
                    relief="solid" if is_selected else "flat", bd=1 if is_selected else 0,
                    cursor="hand2", command=lambda d=cell_date: self.set_date(d)
                )
                btn.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")
            else:
                tk.Label(grid, text="", width=5, bg="white").grid(row=row, column=col)

    def _shift_calendar_month(self, delta):
        month = self.popup_month + delta
        year = self.popup_year
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self.popup_year = year
        self.popup_month = month
        self._build_calendar_grid()

    def set_date(self, new_date):
        self.save_current()
        self.current_note()["date"] = new_date.isoformat()
        self.save()
        self.refresh_display()

    def close_calendar_popup(self):
        self.calendar_popup = None

    def is_due_today(self, note, today):
        start = parse_date(note.get("date"), today)
        if today < start:
            return False
        repeat = note.get("repeat", "once")
        if repeat == "once":
            return today == start
        if repeat == "daily":
            return True
        if repeat == "weekly":
            return today.weekday() == start.weekday()
        if repeat == "monthly":
            return today.day == start.day
        if repeat == "yearly":
            return today.month == start.month and today.day == start.day
        return False

    def check_due(self, now):
        if self.window and self.text_widget:
            try:
                self.save_current()
            except tk.TclError:
                pass
        fired = []
        for note in self.notes_list:
            if not note.get("enabled", True):
                continue
            if not str(note.get("text", "")).strip():
                continue
            if now.strftime("%H:%M") != parse_time(note.get("time", "09:00")):
                continue
            if not self.is_due_today(note, now.date()):
                continue
            occurrence = f"{now.date().isoformat()} {parse_time(note.get('time', '09:00'))} {note.get('repeat', 'once')}"
            if note.get("last_fired") == occurrence:
                continue
            note["last_fired"] = occurrence
            fired.append(dict(note))
        if fired:
            self.save()
            for note in fired:
                if self.on_reminder:
                    self.on_reminder(note)
        return fired
