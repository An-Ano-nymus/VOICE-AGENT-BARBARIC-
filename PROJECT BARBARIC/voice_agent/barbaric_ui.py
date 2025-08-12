import sys
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import speech_recognition as sr
import math
import random
import time

# Import your main agent logic
import main as barbaric


class BarbaricUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Barbaric Voice Agent")
        self.geometry("720x720")
        self.configure(bg="#23272e")

        # State
        self.listen_thread = None
        self.listen_stop = threading.Event()
        self.always_listen_var = tk.BooleanVar(value=barbaric.SETTINGS.get("always_listen", False))

        # Build UI
        self.create_widgets()

        # Close handling
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Hook TTS to UI log
        self._orig_speak = barbaric.speak

        def ui_speak(text: str):
            ui_text = text.replace('Barbaric says: ', '')
            self.display_response(ui_text)
            try:
                self._orig_speak(text)
            except Exception:
                pass
        barbaric.speak = ui_speak

        # Register UI so main can call overlay methods
        try:
            barbaric.register_ui(self)
        except Exception:
            pass

        # Theme
        try:
            self.apply_theme(barbaric.SETTINGS.get("theme", "dark"))
        except Exception:
            pass

        # OCR availability info
        try:
            ok, err = barbaric.ocr_is_available()
            if not ok:
                self.display_response("OCR not available. Install Tesseract OCR and set its path in Settings.")
        except Exception:
            pass

        # Auto-start Always Listen
        if self.always_listen_var.get():
            self.start_always_listen()

    def create_widgets(self):
        self.header = tk.Label(self, text="Barbaric Voice Agent", font=("Segoe UI", 20, "bold"), fg="#00ff99", bg="#23272e")
        self.header.pack(pady=10)

        # Visualizer
        self.viz_canvas = tk.Canvas(self, height=100, bg="#0b0f16", highlightthickness=0)
        self.viz_canvas.pack(fill=tk.X, padx=12)
        self._viz_running = False
        self._viz_levels = [0.0] * 40
        self._viz_color = "#00e0ff"
        self._viz_bg = "#0b0f16"
        self._viz_draw_bars()

        # Toolbar
        self.toolbar = tk.Frame(self, bg="#23272e")
        self.toolbar.pack(fill=tk.X, padx=10)
        self.al_toggle = tk.Checkbutton(
            self.toolbar,
            text="Always Listen",
            variable=self.always_listen_var,
            command=self.on_toggle_always_listen,
            bg="#23272e",
            fg="#ffffff",
            selectcolor="#23272e",
            activebackground="#23272e",
        )
        self.al_toggle.pack(side=tk.LEFT)
        self.settings_btn = tk.Button(self.toolbar, text="Settings", command=self.open_settings, bg="#3b3f46", fg="#ffffff")
        self.settings_btn.pack(side=tk.RIGHT)
        self.ocr_btn = tk.Button(self.toolbar, text="Analyze Screen", command=self.on_analyze_screen, bg="#3b3f46", fg="#ffffff")
        self.ocr_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.test_ocr_btn = tk.Button(self.toolbar, text="Test OCR", command=self.on_test_ocr, bg="#3b3f46", fg="#ffffff")
        self.test_ocr_btn.pack(side=tk.RIGHT, padx=(6, 0))

        # IO Area
        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Consolas", 12), bg="#181a20", fg="#ffffff", height=15)
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.text_area.config(state=tk.DISABLED)

        self.status = tk.Label(self, text="Say a command or type below.", font=("Segoe UI", 12), fg="#cccccc", bg="#23272e")
        self.status.pack(pady=5)

        self.input_frame = tk.Frame(self, bg="#23272e")
        self.input_frame.pack(fill=tk.X, padx=10, pady=5)

        self.input_entry = tk.Entry(self.input_frame, font=("Segoe UI", 12), bg="#2c2f36", fg="#ffffff")
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.input_entry.bind('<Return>', self.on_enter)

        self.send_btn = tk.Button(self.input_frame, text="Send", command=self.on_send, bg="#00ff99", fg="#23272e", font=("Segoe UI", 12, "bold"))
        self.send_btn.pack(side=tk.RIGHT)

        self.voice_btn = tk.Button(self, text="Speak", command=self.on_speak, bg="#4da6ff", fg="#23272e", font=("Segoe UI", 12, "bold"))
        self.voice_btn.pack(pady=5)

        # Overlay placeholder
        self._grid_overlay = None

    # ===== Visualizer =====
    def _viz_draw_bars(self):
        c = self.viz_canvas
        c.delete("all")
        w = c.winfo_width() or c.winfo_reqwidth()
        h = c.winfo_height() or 90
        n = len(self._viz_levels)
        gap = 4
        bar_w = max(2, (w - gap * (n + 1)) // n)
        for i, lvl in enumerate(self._viz_levels):
            scale = max(0.02, min(1.0, lvl))
            bh = int(scale * (h - 12))
            x0 = gap + i * (bar_w + gap)
            y0 = h - bh - 6
            x1 = x0 + bar_w
            y1 = h - 6
            c.create_rectangle(x0, y0, x1, y1, fill=self._viz_color, width=0)
            c.create_rectangle(x0, y0, x1, y1, outline="#66ffff", width=1)
        cx = w // 2
        cy = h // 2
        r = 22
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#1bd1ff", width=2)
        if self._viz_running:
            self.after(33, self._viz_draw_bars)

    def _viz_step(self):
        if not self._viz_running:
            return
        n = len(self._viz_levels)
        t = time.time()
        base = 0.06 + 0.02 * math.sin(t * 2.1)
        for i in range(n):
            phase = (i / n) * math.pi * 2
            wave = 0.6 + 0.4 * math.sin(t * 4.0 + phase)
            level = min(1.0, base * (1.5 + wave) + 0.02 * random.random())
            self._viz_levels[i] = self._viz_levels[i] * 0.65 + level * 0.35
        self.after(33, self._viz_step)

    def start_visualizer(self):
        if self._viz_running:
            return
        self._viz_running = True
        self.after(0, self._viz_draw_bars)
        self.after(33, self._viz_step)
        try:
            self.status.config(text="Listening…", fg="#00e0ff")
        except Exception:
            pass

    def stop_visualizer(self):
        if not self._viz_running:
            return
        self._viz_running = False
        try:
            self.status.config(text="Idle.", fg="#cccccc")
        except Exception:
            pass

    # ===== IO =====
    def display_response(self, text):
        def _append():
            self.text_area.config(state=tk.NORMAL)
            self.text_area.insert(tk.END, f"Barbaric: {text}\n")
            self.text_area.see(tk.END)
            self.text_area.config(state=tk.DISABLED)
        self.after(0, _append)

    def on_enter(self, event):
        self.on_send()

    def on_send(self):
        user_input = self.input_entry.get().strip()
        if user_input:
            self.text_area.config(state=tk.NORMAL)
            self.text_area.insert(tk.END, f"You: {user_input}\n")
            self.text_area.config(state=tk.DISABLED)
            self.input_entry.delete(0, tk.END)
            response = barbaric.get_ai_response(user_input)
            barbaric.handle_ai_response(response)

    def on_speak(self):
        self.start_visualizer()
        def _listen_and_process():
            try:
                utterance = barbaric.listen()
                if not utterance:
                    return
                self.after(0, lambda: self._append_user_voice(utterance))
                response = barbaric.get_ai_response(utterance)
                barbaric.handle_ai_response(response)
            except Exception as e:
                self.display_response(f"Voice input failed: {e}")
            finally:
                self.stop_visualizer()
        threading.Thread(target=_listen_and_process, daemon=True).start()

    def _append_user_voice(self, utterance: str):
        self.text_area.config(state=tk.NORMAL)
        self.text_area.insert(tk.END, f"You (voice): {utterance}\n")
        self.text_area.config(state=tk.DISABLED)

    def on_close(self):
        self.stop_always_listen()
        if messagebox.askokcancel("Quit", "Do you want to quit Barbaric?"):
            self.destroy()
            sys.exit()

    # ===== Always Listen =====
    def on_toggle_always_listen(self):
        enabled = bool(self.always_listen_var.get())
        barbaric.SETTINGS["always_listen"] = enabled
        if enabled:
            self.start_always_listen()
        else:
            self.stop_always_listen()

    def start_always_listen(self):
        if self.listen_thread and self.listen_thread.is_alive():
            return
        self.listen_stop.clear()
        self.start_visualizer()

        def _loop():
            try:
                while not self.listen_stop.is_set() and barbaric.SETTINGS.get("always_listen", False):
                    try:
                        utterance = barbaric.listen()
                        if utterance:
                            self.after(0, lambda u=utterance: self._append_user_voice(u))
                            response = barbaric.get_ai_response(utterance)
                            barbaric.handle_ai_response(response)
                        else:
                            self.listen_stop.wait(0.2)
                    except Exception as e:
                        self.after(0, lambda msg=f"Always Listen error: {e}": self.display_response(msg))
                        self.listen_stop.wait(0.5)
            finally:
                self.after(0, self.stop_visualizer)
        self.listen_thread = threading.Thread(target=_loop, daemon=True)
        self.listen_thread.start()

    def stop_always_listen(self):
        self.listen_stop.set()
        self.after(0, self.stop_visualizer)

    # ===== OCR actions =====
    def on_analyze_screen(self):
        def _run():
            try:
                try:
                    ok, err = barbaric.ocr_is_available()
                except Exception:
                    ok, err = False, None
                if not ok:
                    self.display_response("OCR not available. Please configure Tesseract in Settings.")
                    return
                txt = barbaric.screen_ocr()
                snippet = (txt[:800] + '…') if len(txt) > 800 else txt
                self.display_response("Screen OCR:\n" + (snippet or "<no text found>"))
            except Exception as e:
                self.display_response(f"Screen analysis failed: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def on_test_ocr(self):
        def _run():
            try:
                ok, msg = barbaric.test_ocr()
                if ok:
                    self.display_response(f"OCR test passed: {msg}")
                else:
                    self.display_response(f"OCR test failed: {msg}")
            except Exception as e:
                self.display_response(f"OCR test error: {e}")
        threading.Thread(target=_run, daemon=True).start()

    # ===== Settings =====
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg="#23272e")
        win.geometry("560x560")

        # Voice rate
        tk.Label(win, text="Voice rate", bg="#23272e", fg="#ffffff").pack(pady=(10, 0))
        rate_var = tk.IntVar(value=barbaric.SETTINGS.get("voice_rate", 135))
        rate_scale = tk.Scale(win, from_=90, to=200, orient=tk.HORIZONTAL, variable=rate_var, bg="#23272e", fg="#ffffff", highlightthickness=0)
        rate_scale.pack(fill=tk.X, padx=12)

        # Mic device
        tk.Label(win, text="Microphone", bg="#23272e", fg="#ffffff").pack(pady=(10, 0))
        mics = sr.Microphone.list_microphone_names() or ["Default device"]
        mic_names = [str(n) for n in mics]
        current_idx = barbaric.SETTINGS.get("mic_device_index")
        sel_index = current_idx if (isinstance(current_idx, int) and 0 <= current_idx < len(mic_names)) else 0
        mic_var = tk.StringVar(value=mic_names[sel_index])
        mic_menu = tk.OptionMenu(win, mic_var, *mic_names)
        mic_menu.configure(bg="#3b3f46", fg="#ffffff")
        mic_menu.pack(fill=tk.X, padx=12)

        # Cursor step
        tk.Label(win, text="Cursor step (px)", bg="#23272e", fg="#ffffff").pack(pady=(10, 0))
        curstep_var = tk.IntVar(value=int(barbaric.SETTINGS.get("cursor_step", 80)))
        curstep_scale = tk.Scale(win, from_=10, to=300, orient=tk.HORIZONTAL, variable=curstep_var, bg="#23272e", fg="#ffffff", highlightthickness=0)
        curstep_scale.pack(fill=tk.X, padx=12)

        # Theme
        tk.Label(win, text="Theme", bg="#23272e", fg="#ffffff").pack(pady=(10, 0))
        themes = ["dark", "light"]
        theme_var = tk.StringVar(value=barbaric.SETTINGS.get("theme", "dark"))
        theme_menu = tk.OptionMenu(win, theme_var, *themes)
        theme_menu.configure(bg="#3b3f46", fg="#ffffff")
        theme_menu.pack(fill=tk.X, padx=12)

        # Tesseract path
        tk.Label(win, text="Tesseract path (tesseract.exe)", bg="#23272e", fg="#ffffff").pack(pady=(10, 0))
        tess_frame = tk.Frame(win, bg="#23272e")
        tess_frame.pack(fill=tk.X, padx=12)
        tess_var = tk.StringVar(value=str(barbaric.SETTINGS.get("tesseract_cmd") or ""))
        tess_entry = tk.Entry(tess_frame, textvariable=tess_var, bg="#2c2f36", fg="#ffffff")
        tess_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse_tesseract():
            path = filedialog.askopenfilename(title="Select tesseract.exe", filetypes=[("Executable","*.exe"), ("All files","*.*")])
            if path:
                tess_var.set(path)
        tk.Button(tess_frame, text="Browse", command=browse_tesseract, bg="#3b3f46", fg="#ffffff").pack(side=tk.RIGHT, padx=(6, 0))

        def save_settings():
            barbaric.update_voice_settings(rate_var.get())
            try:
                idx = mic_names.index(mic_var.get())
            except ValueError:
                idx = None
            barbaric.SETTINGS["mic_device_index"] = idx
            barbaric.SETTINGS["theme"] = theme_var.get()
            self.apply_theme(theme_var.get())
            try:
                barbaric.SETTINGS["cursor_step"] = int(curstep_var.get())
            except Exception:
                pass
            path = tess_var.get().strip()
            barbaric.SETTINGS["tesseract_cmd"] = path or None
            try:
                ok, err = barbaric.ocr_is_available()
                if ok:
                    messagebox.showinfo("Settings", "OCR is available and configured.")
                else:
                    messagebox.showwarning("Settings", f"OCR not available yet. Details: {err or 'Tesseract not found.'}")
            except Exception:
                pass

        # Feature toggles
        tk.Label(win, text="Features", bg="#23272e", fg="#ffffff", font=("Segoe UI", 12, "bold")).pack(pady=(10, 0))
        feats = barbaric.SETTINGS.setdefault("features", {})
        feat_vars = {}
        def add_toggle(key, label):
            var = tk.BooleanVar(value=bool(feats.get(key, True)))
            feat_vars[key] = var
            cb = tk.Checkbutton(win, text=label, variable=var, bg="#23272e", fg="#ffffff", selectcolor="#23272e", activebackground="#23272e")
            cb.pack(anchor='w', padx=18)
        add_toggle('ocr', 'Enable OCR and Screen Observe')
        add_toggle('click_text', 'Enable Click/Hover/Type by Text')
        add_toggle('cursor_nav', 'Enable Cursor Navigation')
        add_toggle('grid_nav', 'Enable Grid Navigation and Overlay')
        add_toggle('skills', 'Enable Skills (experimental)')
        add_toggle('safety_confirm', 'Safety Confirmation for Dangerous Commands')
        add_toggle('tts_prefix', 'Prefix TTS with Agent Name')
        add_toggle('speak_ack', 'Speak Action Acknowledgements')

        # Dev mode
        dev_var = tk.BooleanVar(value=bool(barbaric.SETTINGS.get('dev_mode', False)))
        dev_cb = tk.Checkbutton(win, text='Developer Mode (allow update_skill)', variable=dev_var, bg="#23272e", fg="#ff8080", selectcolor="#23272e", activebackground="#23272e")
        dev_cb.pack(anchor='w', padx=18, pady=(6, 0))

        def on_save_all():
            save_settings()
            for k, v in feat_vars.items():
                feats[k] = bool(v.get())
            barbaric.SETTINGS['dev_mode'] = bool(dev_var.get())
            messagebox.showinfo("Settings", "Settings saved.")
            win.destroy()

        tk.Button(win, text="Save", command=on_save_all, bg="#00ff99", fg="#23272e").pack(pady=12)

    def apply_theme(self, theme: str):
        if theme == "light":
            bg = "#f5f5f5"; fg = "#000000"; panel = "#e0e0e0"
        else:
            bg = "#23272e"; fg = "#ffffff"; panel = "#181a20"
        self.configure(bg=bg)
        widgets = [
            self.header, self.toolbar, self.status, self.input_frame, self.text_area,
            self.input_entry, self.send_btn, self.voice_btn, self.al_toggle,
            self.settings_btn, self.viz_canvas, getattr(self, 'ocr_btn', None),
            getattr(self, 'test_ocr_btn', None)
        ]
        for w in widgets:
            try:
                if isinstance(w, scrolledtext.ScrolledText):
                    w.configure(bg=panel, fg=fg)
                elif isinstance(w, tk.Entry):
                    w.configure(bg=panel, fg=fg, insertbackground=fg)
                elif isinstance(w, tk.Button) or isinstance(w, tk.Checkbutton):
                    w.configure(bg="#3b3f46", fg=fg, activebackground="#3b3f46")
                else:
                    w.configure(bg=bg, fg=fg)
            except Exception:
                pass

    # ===== Overlay grid =====
    def show_grid_overlay(self):
        try:
            if self._grid_overlay and tk.Toplevel.winfo_exists(self._grid_overlay):
                self._grid_overlay.deiconify()
                self._grid_overlay.lift()
                return
            ov = tk.Toplevel(self)
            ov.overrideredirect(True)
            ov.attributes('-topmost', True)
            try:
                ov.attributes('-alpha', 0.2)
            except Exception:
                pass
            w = self.winfo_screenwidth()
            h = self.winfo_screenheight()
            ov.geometry(f"{w}x{h}+0+0")
            cv = tk.Canvas(ov, bg='black', highlightthickness=0)
            cv.pack(fill=tk.BOTH, expand=True)
            thirds_x = [w//3, 2*w//3]
            thirds_y = [h//3, 2*h//3]
            cv.create_line(thirds_x[0], 0, thirds_x[0], h, fill='#00ffff', width=2)
            cv.create_line(thirds_x[1], 0, thirds_x[1], h, fill='#00ffff', width=2)
            cv.create_line(0, thirds_y[0], w, thirds_y[0], fill='#00ffff', width=2)
            cv.create_line(0, thirds_y[1], w, thirds_y[1], fill='#00ffff', width=2)
            cells = {
                1: (w//6, 5*h//6), 2: (w//2, 5*h//6), 3: (5*w//6, 5*h//6),
                4: (w//6, h//2),   5: (w//2, h//2),   6: (5*w//6, h//2),
                7: (w//6, h//6),   8: (w//2, h//6),   9: (5*w//6, h//6),
            }
            for n, (cx, cy) in cells.items():
                cv.create_text(cx, cy, text=str(n), fill='#00ffff', font=("Segoe UI", 36, "bold"))
            self._grid_overlay = ov
        except Exception as e:
            self.display_response(f"Grid overlay failed: {e}")

    def hide_grid_overlay(self):
        try:
            if self._grid_overlay:
                self._grid_overlay.withdraw()
        except Exception:
            pass


if __name__ == "__main__":
    app = BarbaricUI()
    app.mainloop()
