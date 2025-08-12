import sys
import os
import threading
import tkinter as tk
from tkinter import scrolledtext
from tkinter import messagebox
from tkinter import filedialog
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
        self.geometry("600x400")
        self.configure(bg="#23272e")

        # Background listening control and state
        self.listen_thread = None
        self.listen_stop = threading.Event()
        self.always_listen_var = tk.BooleanVar(value=barbaric.SETTINGS.get("always_listen", False))

        # Build UI first
        self.create_widgets()
        
        # Window close handling
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Wrap original speak to both TTS and UI log (after widgets exist)
        self._orig_speak = barbaric.speak

        def ui_speak(text: str):
            # Normalize text for UI (avoid double prefix from agent)
            ui_text = text.replace('Barbaric says: ', '')
            self.display_response(ui_text)
            try:
                self._orig_speak(text)
            except Exception:
                pass

        barbaric.speak = ui_speak
        
        # Apply current theme
        try:
            self.apply_theme(barbaric.SETTINGS.get("theme", "dark"))
        except Exception:
            pass

        # Check OCR availability once and inform user if missing
        try:
            ok, err = barbaric.ocr_is_available()
            if not ok:
                self.display_response("OCR not available. Install Tesseract OCR and set its path in Settings to enable on-screen text interactions.")
        except Exception:
            pass

        # Auto-start Always Listen if enabled
        if self.always_listen_var.get():
            self.start_always_listen()

    def create_widgets(self):
        self.header = tk.Label(self, text="Barbaric Voice Agent", font=("Arial", 20, "bold"), fg="#00ff99", bg="#23272e")
        self.header.pack(pady=10)

        # Visualizer (Jarvis-like audio bars)
        self.viz_canvas = tk.Canvas(self, height=90, bg="#0b0f16", highlightthickness=0)
        self.viz_canvas.pack(fill=tk.X, padx=12)
        self._viz_running = False
        self._viz_levels = [0.0] * 40  # 40 bars
        self._viz_color = "#00e0ff"
        self._viz_bg = "#0b0f16"
        self._viz_draw_bars()  # initial draw

        # Toolbar with Always Listen toggle and Settings button
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

        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Consolas", 12), bg="#181a20", fg="#ffffff", height=15)
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.text_area.config(state=tk.DISABLED)

        self.status = tk.Label(self, text="Say a command or type below.", font=("Arial", 12), fg="#cccccc", bg="#23272e")
        self.status.pack(pady=5)

        self.input_frame = tk.Frame(self, bg="#23272e")
        self.input_frame.pack(fill=tk.X, padx=10, pady=5)

        self.input_entry = tk.Entry(self.input_frame, font=("Arial", 12), bg="#2c2f36", fg="#ffffff")
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.input_entry.bind('<Return>', self.on_enter)

        self.send_btn = tk.Button(self.input_frame, text="Send", command=self.on_send, bg="#00ff99", fg="#23272e", font=("Arial", 12, "bold"))
        self.send_btn.pack(side=tk.RIGHT)

        self.voice_btn = tk.Button(self, text="Speak", command=self.on_speak, bg="#4da6ff", fg="#23272e", font=("Arial", 12, "bold"))
        self.voice_btn.pack(pady=5)

    # ===== Visualizer logic =====
    def _viz_draw_bars(self):
        c = self.viz_canvas
        c.delete("all")
        w = c.winfo_width() or c.winfo_reqwidth()
        h = c.winfo_height() or 90
        n = len(self._viz_levels)
        gap = 4
        bar_w = max(2, (w - gap * (n + 1)) // n)
        for i, lvl in enumerate(self._viz_levels):
            # Smooth visual scale
            scale = max(0.02, min(1.0, lvl))
            bh = int(scale * (h - 12))
            x0 = gap + i * (bar_w + gap)
            y0 = h - bh - 6
            x1 = x0 + bar_w
            y1 = h - 6
            # Neon-like bar with two layers
            c.create_rectangle(x0, y0, x1, y1, fill=self._viz_color, width=0)
            c.create_rectangle(x0, y0, x1, y1, outline="#66ffff", width=1)
        # Draw a subtle center ring
        cx = w // 2
        cy = h // 2
        r = 22
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#1bd1ff", width=2)
        if self._viz_running:
            # schedule next draw
            self.after(33, self._viz_draw_bars)  # ~30 FPS

    def _viz_step(self):
        if not self._viz_running:
            return
        # Animate with multi-phase waves and a small jitter
        n = len(self._viz_levels)
        t = time.time()
        base = 0.06 + 0.02 * math.sin(t * 2.1)
        for i in range(n):
            phase = (i / n) * math.pi * 2
            wave = 0.6 + 0.4 * math.sin(t * 4.0 + phase)
            level = min(1.0, base * (1.5 + wave) + 0.02 * random.random())
            self._viz_levels[i] = self._viz_levels[i] * 0.65 + level * 0.35
        # schedule next frame
        self.after(33, self._viz_step)

    def start_visualizer(self):
        if self._viz_running:
            return
        self._viz_running = True
        # restart draw loop
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
        # canvas will stop auto-updates on next draw
        try:
            self.status.config(text="Idle.", fg="#cccccc")
        except Exception:
            pass

    def display_response(self, text):
        # Thread-safe UI update
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
            # Directly call the agent's response logic for text input
            response = barbaric.get_ai_response(user_input)
            barbaric.handle_ai_response(response)

    def on_speak(self):
        # Run listen in a short worker to avoid blocking UI
        # Start visualizer on main thread first
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

    # Always Listen management
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
        # Start visualizer on main thread while Always Listen active
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
                            # Small idle sleep to reduce CPU
                            self.listen_stop.wait(0.2)
                    except Exception as e:
                        # Schedule UI update from worker thread
                        self.after(0, lambda msg=f"Always Listen error: {e}": self.display_response(msg))
                        self.listen_stop.wait(0.5)
            finally:
                self.after(0, self.stop_visualizer)

        self.listen_thread = threading.Thread(target=_loop, daemon=True)
        self.listen_thread.start()

    def stop_always_listen(self):
        self.listen_stop.set()
        # thread daemon will exit on its own
        self.after(0, self.stop_visualizer)

    def on_analyze_screen(self):
        # Run OCR in background and display summary
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

    # Settings dialog
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg="#23272e")
        win.geometry("480x400")

        # Voice rate
        tk.Label(win, text="Voice rate", bg="#23272e", fg="#ffffff").pack(pady=(10, 0))
        rate_var = tk.IntVar(value=barbaric.SETTINGS.get("voice_rate", 135))
        rate_scale = tk.Scale(win, from_=90, to=200, orient=tk.HORIZONTAL, variable=rate_var, bg="#23272e", fg="#ffffff", highlightthickness=0)
        rate_scale.pack(fill=tk.X, padx=12)

        # Microphone device
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
            # Apply voice rate
            barbaric.update_voice_settings(rate_var.get())
            # Apply mic device
            try:
                idx = mic_names.index(mic_var.get())
            except ValueError:
                idx = None
            barbaric.SETTINGS["mic_device_index"] = idx
            # Apply theme
            barbaric.SETTINGS["theme"] = theme_var.get()
            self.apply_theme(theme_var.get())
            # Apply cursor step
            try:
                barbaric.SETTINGS["cursor_step"] = int(curstep_var.get())
            except Exception:
                pass
            # Apply tesseract path
            path = tess_var.get().strip()
            barbaric.SETTINGS["tesseract_cmd"] = path or None
            # Quick OCR check
            try:
                ok, err = barbaric.ocr_is_available()
                if ok:
                    messagebox.showinfo("Settings", "OCR is available and configured.")
                else:
                    messagebox.showwarning("Settings", f"OCR not available yet. Details: {err or 'Tesseract not found.'}")
            except Exception:
                pass
            win.destroy()

        tk.Button(win, text="Save", command=save_settings, bg="#00ff99", fg="#23272e").pack(pady=12)

    def apply_theme(self, theme: str):
        if theme == "light":
            bg = "#f5f5f5"; fg = "#000000"; panel = "#e0e0e0"; accent = "#007acc"
        else:
            bg = "#23272e"; fg = "#ffffff"; panel = "#181a20"; accent = "#00ff99"
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


if __name__ == "__main__":
    app = BarbaricUI()
    app.mainloop()
