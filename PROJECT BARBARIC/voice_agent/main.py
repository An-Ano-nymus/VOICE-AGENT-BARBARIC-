import os
import speech_recognition as sr
import pyttsx3
from cerebras.cloud.sdk import Cerebras
import subprocess
import time
import json
import platform
import threading
import queue
import ctypes
from ctypes import wintypes
import pyautogui
import importlib.util
import types
import glob
from pathlib import Path
import re

# Initialize text-to-speech engine (prefer Windows SAPI5) and speaking state
def _init_engine():
    try:
        drv = 'sapi5' if platform.system() == 'Windows' else None
        eng = pyttsx3.init(driverName=drv)
        eng.setProperty('rate', 135)
        eng.setProperty('volume', 1.0)
        # Prefer female voice if present
        try:
            voices = eng.getProperty('voices') or []
            if isinstance(voices, (list, tuple)):
                for v in voices:
                    try:
                        nm = getattr(v, 'name', '')
                        if isinstance(nm, str) and 'female' in nm.lower():
                            eng.setProperty('voice', v.id)
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        return eng
    except Exception as e:
        print(f"Failed to init pyttsx3: {e}")
        raise

engine = _init_engine()

# Signal to coordinate with listeners and UI
TTS_IS_PLAYING = threading.Event()

AGENT_NAME = "Barbaric"

# Runtime settings (tunable from UI)
SETTINGS = {
    "language": "en-IN",
    "timeout": 6,
    "phrase_time_limit": 16,
    "always_listen": False,
    "mic_device_index": None,
    "voice_rate": 135,
    "theme": "dark",
    # Use provided Tesseract path by default; can be overridden in UI Settings
    "tesseract_cmd": r"D:\\Raghav\\EVOLUTION\\Image to text via tesseract\\tesseract.exe",
    # Default cursor navigation step (pixels) for voice cursor_nav
    "cursor_step": 80,
    # Guard for self-evolution; when true, LLM can update skills files
    "dev_mode": False,
    # Runtime feature toggles
    "features": {
        "ocr": True,
        "click_text": True,
        "cursor_nav": True,
        "grid_nav": True,
        "skills": False,  # disabled by default
        "safety_confirm": True,
        "tts_prefix": True,
        "speak_ack": True,
    },
}

def update_voice_settings(rate: int | None = None):
    try:
        if rate is not None:
            SETTINGS["voice_rate"] = int(rate)
        engine.setProperty('rate', SETTINGS["voice_rate"])
    except Exception:
        pass

API_KEY = os.environ.get("CEREBRAS_API_KEY", "csk-kjdnkhmmcrw4wfced48mjrjmpejewktm2392kx4k3vm2n56c")
if not API_KEY:
    raise ValueError("Missing Cerebras API key.")
client = Cerebras(api_key=API_KEY)

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8
recognizer.phrase_threshold = 0.3
recognizer.non_speaking_duration = 0.4

# Reusable microphone accessor
def get_microphone():
    return sr.Microphone(device_index=SETTINGS["mic_device_index"]) if SETTINGS["mic_device_index"] is not None else sr.Microphone()

# TTS worker to serialize audio output across threads
_tts_queue: "queue.Queue[str]" = queue.Queue()
_tts_lock = threading.Lock()

def _tts_worker():
    while True:
        text = _tts_queue.get()
        if text is None:
            break
        try:
            # Mark speaking and guard the engine
            TTS_IS_PLAYING.set()
            with _tts_lock:
                try:
                    for chunk in _split_into_tts_chunks(text):
                        if not chunk:
                            continue
                        engine.say(chunk)
                    engine.runAndWait()
                except Exception as inner:
                    # Reinitialize engine once and retry
                    print(f"pyttsx3 failed, restarting engine: {inner}")
                    try:
                        globals()['engine'] = _init_engine()
                        for chunk in _split_into_tts_chunks(text):
                            if not chunk:
                                continue
                            engine.say(chunk)
                        engine.runAndWait()
                    except Exception as inner2:
                        raise inner2
        except Exception as e:
            print(f"pyttsx3 failed: {e}. Trying gTTS fallback...")
            try:
                from gtts import gTTS
                temp_path = "barbaric_tts_fallback.mp3"
                gTTS(text=text, lang='en').save(temp_path)
                _play_mp3_windows(temp_path)
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            except Exception as e2:
                print(f"gTTS fallback also failed: {e2}")
        finally:
            TTS_IS_PLAYING.clear()
            _tts_queue.task_done()

_tts_thread = threading.Thread(target=_tts_worker, daemon=True)
_tts_thread.start()

def speak(text):
    # Always prefix with agent name for clarity
    if SETTINGS.get("features", {}).get("tts_prefix", True):
        if AGENT_NAME.lower() not in text.lower():
            text = f"{AGENT_NAME} says: {text}"
    # Send as a single TTS unit to avoid choppy audio; worker handles splitting
    _tts_queue.put(text)


def _split_into_tts_chunks(text: str, max_len: int = 180) -> list[str]:
    # Prefer sentence boundaries, then fall back to soft wrapping
    try:
        sentences = []
        parts = re.split(r'(?:([.!?]\s)|\n)', text)
        buf = ''
        for p in parts:
            if p is None:
                continue
            buf += p
            if any(ch in p for ch in '.!?\n') and len(buf) >= 1:
                sentences.append(buf.strip())
                buf = ''
        if buf.strip():
            sentences.append(buf.strip())
        # Now wrap long sentences softly
        chunks: list[str] = []
        for s in sentences:
            if len(s) <= max_len:
                chunks.append(s)
            else:
                words = s.split()
                cur = []
                cur_len = 0
                for w in words:
                    if cur_len + len(w) + 1 > max_len and cur:
                        chunks.append(' '.join(cur))
                        cur = [w]
                        cur_len = len(w)
                    else:
                        cur.append(w)
                        cur_len += len(w) + 1
                if cur:
                    chunks.append(' '.join(cur))
        return chunks if chunks else [text]
    except Exception:
        return [text]


# --- Windows-native MP3 playback via winmm (MCI) ---
def _play_mp3_windows(path: str):
    if platform.system() != 'Windows':
        return
    mciSendString = ctypes.windll.winmm.mciSendStringW
    alias = f"barbaric_mp3"
    cmd = f'open "{path}" type mpegvideo alias {alias}'
    mciSendString(cmd, None, 0, None)
    mciSendString(f'play {alias}', None, 0, None)
    # Wait until done
    status_buf = ctypes.create_unicode_buffer(128)
    while True:
        mciSendString(f'status {alias} mode', status_buf, 128, None)
        mode = status_buf.value.strip()
        if mode in ("stopped", "not ready"):
            break
        time.sleep(0.05)
    mciSendString(f'close {alias}', None, 0, None)

def listen():
    # Avoid listening while TTS is speaking to prevent feedback and timeouts
    if TTS_IS_PLAYING.is_set():
        # Wait briefly for TTS to finish instead of immediately bailing
        waited = 0.0
        while TTS_IS_PLAYING.is_set() and waited < 3.0:
            time.sleep(0.05)
            waited += 0.05
        if TTS_IS_PLAYING.is_set():
            return ''

    with get_microphone() as source:
        print('Listening...')
        # Quick ambient calibration (int seconds for type-checkers)
        recognizer.adjust_for_ambient_noise(source, duration=1)
        try:
            audio = recognizer.listen(source, timeout=SETTINGS["timeout"], phrase_time_limit=SETTINGS["phrase_time_limit"])
        except sr.WaitTimeoutError:
            print('Listening timed out while waiting for speech.')
            # Do not speak here to avoid spamming UI; return quietly
            return ''
        try:
            # Try Google with alternatives and choose the longest/best
            recog = getattr(recognizer, "recognize_google")  # type: ignore[attr-defined]
            result_all = recog(audio, language=SETTINGS["language"], show_all=True)  # type: ignore[call-arg]
            candidate = ''
            if isinstance(result_all, dict) and 'alternative' in result_all:
                alts = result_all.get('alternative') or []
                # Prefer transcript with highest confidence/longest length
                def score(alt):
                    txt = (alt.get('transcript') or '').strip()
                    conf = alt.get('confidence', 0.0)
                    return (conf, len(txt))
                if alts:
                    best = max(alts, key=score)
                    candidate = (best.get('transcript') or '').strip()
            if not candidate:
                candidate = recog(audio, language=SETTINGS["language"])  # type: ignore[attr-defined]
            candidate = (candidate or '').strip()
            # If result seems too short, attempt a brief follow-up capture to complete it
            if len(candidate.split()) < 4:
                try:
                    audio2 = recognizer.listen(source, timeout=1.2, phrase_time_limit=3)
                    result2 = recog(audio2, language=SETTINGS["language"])  # type: ignore[attr-defined]
                    if result2:
                        candidate = (candidate + ' ' + result2).strip()
                except Exception:
                    pass
            print(f'You said: {candidate}')
            return candidate
        except sr.UnknownValueError:
            print('Sorry, I did not understand.')
            return ''

def execute_command(command):
    try:
        print(f"[Barbaric] Executing shell command: {command}")
        if SETTINGS.get("features", {}).get("speak_ack", True):
            speak(f"Executing command: {command}")
        dangerous = ['del ', 'erase ', 'format ', 'shutdown', 'rd ', 'rmdir ', 'reg ', 'diskpart', 'net user', 'net localgroup', 'taskkill', 'powershell Remove-']
        if SETTINGS.get("features", {}).get("safety_confirm", True):
            if any(d in command.lower() for d in dangerous):
                speak("Warning: This command may be dangerous. Do you want to continue?")
                confirmation = listen().lower()
                if 'yes' not in confirmation and 'हाँ' not in confirmation and 'haan' not in confirmation:
                    speak("Command cancelled for your safety.")
                    return
        completed = subprocess.run(command, shell=True, capture_output=True, text=True)
        if completed.stdout:
            print(completed.stdout)
            if SETTINGS.get("features", {}).get("speak_ack", True):
                speak(f"Command output: {completed.stdout[:200]}")
        if completed.stderr:
            print(completed.stderr)
            if SETTINGS.get("features", {}).get("speak_ack", True):
                speak(f"Command error: {completed.stderr[:200]}")
    except Exception as e:
        speak('Command execution failed.')
        print('Error:', e)

def type_text(text):
    try:
        pyautogui.write(text, interval=0.05)
    except Exception as e:
        speak('Failed to type text.')
        print('Type text error:', e)

def control_mouse(action, value=None, speed: float | None = None):
    try:
        if action == 'move' and value and isinstance(value, (list, tuple)) and len(value) == 2:
            dur = 0.2 if speed is None else max(0.01, float(speed))
            pyautogui.moveTo(value[0], value[1], duration=dur)
        elif action == 'move_by' and value and isinstance(value, (list, tuple)) and len(value) == 2:
            dur = 0.2 if speed is None else max(0.01, float(speed))
            pyautogui.moveRel(value[0], value[1], duration=dur)
        elif action == 'click':
            pyautogui.click()
        elif action == 'double_click':
            pyautogui.doubleClick()
        elif action == 'right_click':
            pyautogui.rightClick()
        elif action == 'scroll':
            try:
                amt = 0
                if isinstance(value, (list, tuple)):
                    amt = int(value[0]) if value else 0
                elif value is not None:
                    amt = int(value)
                pyautogui.scroll(amt)
            except Exception:
                pyautogui.scroll(-300)
        elif action == 'drag' and value and isinstance(value, (list, tuple)) and len(value) == 2:
            dur = 0.2 if speed is None else max(0.01, float(speed))
            pyautogui.dragTo(value[0], value[1], duration=dur, button='left')
        elif action == 'path' and isinstance(value, list):
            dur = 0.2 if speed is None else max(0.01, float(speed))
            for pt in value:
                if isinstance(pt, (list, tuple)) and len(pt) == 2:
                    pyautogui.moveTo(pt[0], pt[1], duration=dur)
        else:
            speak('Unknown mouse action or missing value.')
    except Exception as e:
        speak('Failed to control mouse.')
        print('Mouse control error:', e)

def control_window(op: str):
    try:
        op = (op or '').lower()
        if op == 'maximize':
            pyautogui.hotkey('win', 'up')
        elif op == 'minimize':
            pyautogui.hotkey('win', 'down')
        elif op == 'close':
            pyautogui.hotkey('alt', 'f4')
        elif op == 'switch':
            pyautogui.hotkey('alt', 'tab')
        else:
            speak('Unknown window operation.')
    except Exception as e:
        speak('Failed to control window.')
        print('Window control error:', e)

def press_keys(keys):
    try:
        if isinstance(keys, str):
            pyautogui.press(keys)
        elif isinstance(keys, list):
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
        else:
            speak('Unknown key format.')
    except Exception as e:
        speak('Failed to press keys.')
        print('Key press error:', e)

def get_ai_response(user_input):
    # Add context for more accurate and optimized LLM responses
    system_context = f"OS: {platform.system()} {platform.release()} | Python: {platform.python_version()} | User: {os.getlogin()}"
    system_prompt = (
    f"You are Barbaric, a smart AI voice assistant for Windows. System context: {system_context}. "
        "For any user request, generate a JSON array of steps. "
        "For system actions, generate Windows shell commands (cmd.exe or PowerShell) in the 'command' field. "
        "To type text, use: {\"action\": \"type\", \"text\": \"the text to type\"}. "
        "To control the mouse, use: {\"action\": \"mouse\", \"mouse_action\": \"move|move_by|path|click|double_click|right_click|scroll|drag\", \"value\": value, \"speed\": optional_speed}. "
    "For easy cursor navigation, use: {\"action\": \"cursor_nav\", \"direction\": \"up|down|left|right|center|top_left|top_right|bottom_left|bottom_right\", \"amount\": optional_pixels}. "
    "To snap to a 3x3 grid cell (like numpad), use: {\"action\": \"grid_nav\", \"cell\": 1-9} where 1=bottom_left, 5=center, 9=top_right. "
        "To press keys, use: {\"action\": \"key\", \"keys\": \"enter\"} or {\"action\": \"key\", \"keys\": [\"ctrl\", \"c\"]}. "
    "To control windows, use: {\"action\": \"window\", \"op\": \"maximize|minimize|close|switch\"}. "
    "To observe the screen, use: {\"action\": \"observe\"}. "
    "To interact by visible text, use: {\"action\": \"click_text\", \"text\": \"label\"}, {\"action\": \"double_click_text\", \"text\": \"label\"}, {\"action\": \"hover_text\", \"text\": \"label\"}, or {\"action\": \"type_at_text\", \"text\": \"label\", \"value\": \"input\"}. "
    "To show or hide the on-screen navigation grid, use: {\"action\": \"show_grid\"} or {\"action\": \"hide_grid\"}. "
    "To run a custom skill, use: {\"action\": \"run_skill\", \"name\": \"skill_name\", \"payload\": { ... }}. "
    "When developer mode is enabled, you may update a skill via: {\"action\": \"update_skill\", \"name\": \"skill_name\", \"code\": \"python module text\"}. Restrict changes to skills only. "
    "When OCR is unavailable, fall back to key/mouse actions or ask the user to install Tesseract. "
        "For chat, use 'action': 'chat' and 'response'. "
        "For each command step, use: {\"action\": \"command\", \"command\": \"<windows shell command>\"}. "
        "For confirmation, use action: 'confirm' and provide a response. "
        "Always use English for all JSON keys and values, responses can be conversational. "
        "Be concise and only generate the minimum steps needed. "
        "Example: [{\"action\": \"command\", \"command\": \"notepad.exe\"}, {\"action\": \"type\", \"text\": \"hello world\"}, {\"action\": \"mouse\", \"mouse_action\": \"move\", \"value\": [100,200]}, {\"action\": \"chat\", \"response\": \"Done!\"}] "
    )
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        model="gpt-oss-120b",
    )
    # Handle non-streaming and streaming results defensively
    try:
        choices = getattr(chat_completion, 'choices', None)
        if choices:
            msg = choices[0].message
            content = getattr(msg, 'content', None)
            if not content and isinstance(msg, dict):
                content = msg.get('content', '')
            return content or ''
    except Exception:
        pass
    # If it's an iterator/stream, accumulate deltas
    try:
        parts = []
        for evt in chat_completion:
            try:
                delta = getattr(evt, 'delta', None)
                if delta is None and isinstance(evt, dict):
                    delta = evt.get('delta')
                if delta:
                    parts.append(delta)
            except Exception:
                continue
        return ''.join(parts)
    except Exception:
        return ''

def handle_ai_response(ai_response):
    try:
        data = json.loads(ai_response)
        steps = data if isinstance(data, list) else [data]
        for step in steps:
            action = step.get('action')
            if action == 'command':
                cmd = step.get('command', '')
                if cmd:
                    if SETTINGS.get("features", {}).get("speak_ack", True):
                        speak(f'Executing: {cmd}')
                    execute_command(cmd)
                else:
                    speak('No command provided by AI.')
            elif action == 'type':
                text_to_type = step.get('text', '')
                if text_to_type:
                    if SETTINGS.get("features", {}).get("speak_ack", True):
                        speak(f'Typing: {text_to_type}')
                    type_text(text_to_type)
                else:
                    speak('No text provided to type.')
            elif action == 'mouse':
                mouse_action = step.get('mouse_action', '')
                mouse_value = step.get('value', None)
                speed = step.get('speed', None)
                if SETTINGS.get("features", {}).get("speak_ack", True):
                    speak(f'Performing mouse action: {mouse_action}')
                control_mouse(mouse_action, mouse_value, speed)
            elif action == 'cursor_nav':
                if not SETTINGS.get("features", {}).get("cursor_nav", True):
                    speak('Cursor navigation is disabled in settings.')
                    continue
                direction = step.get('direction', '')
                amount = step.get('amount', None)
                cursor_nav(direction, amount)
            elif action == 'grid_nav':
                if not SETTINGS.get("features", {}).get("grid_nav", True):
                    speak('Grid navigation is disabled in settings.')
                    continue
                cell = step.get('cell', None)
                grid_nav(cell)
            elif action == 'window':
                op = step.get('op', '')
                control_window(op)
            elif action == 'observe':
                if not SETTINGS.get("features", {}).get("ocr", True):
                    speak('OCR features are disabled in settings.')
                    continue
                txt = screen_ocr()
                summary = (txt[:600] + '…') if txt and len(txt) > 600 else (txt or '')
                if summary:
                    speak('I analyzed the screen and found some text.')
                    print('SCREEN OCR:\n', summary)
                else:
                    speak('I could not read any text from the screen.')
            elif action == 'click_text':
                if not (SETTINGS.get("features", {}).get("ocr", True) and SETTINGS.get("features", {}).get("click_text", True)):
                    speak('Click by text is disabled in settings.')
                    continue
                label = step.get('text', '')
                if label:
                    ok = click_by_text(label)
                    if not ok:
                        speak('I could not find that text on screen.')
            elif action == 'double_click_text':
                if not (SETTINGS.get("features", {}).get("ocr", True) and SETTINGS.get("features", {}).get("click_text", True)):
                    speak('Click by text is disabled in settings.')
                    continue
                label = step.get('text', '')
                if label:
                    ok = click_by_text(label, clicks=2)
                    if not ok:
                        speak('I could not find that text on screen.')
            elif action == 'hover_text':
                if not (SETTINGS.get("features", {}).get("ocr", True) and SETTINGS.get("features", {}).get("click_text", True)):
                    speak('Hover by text is disabled in settings.')
                    continue
                label = step.get('text', '')
                if label:
                    ok = click_by_text(label, clicks=0, move_only=True)
                    if not ok:
                        speak('I could not locate that text to hover.')
            elif action == 'type_at_text':
                if not (SETTINGS.get("features", {}).get("ocr", True) and SETTINGS.get("features", {}).get("click_text", True)):
                    speak('Type at text is disabled in settings.')
                    continue
                label = step.get('text', '')
                value = step.get('value', '')
                if label and value:
                    ok = click_by_text(label)
                    if ok:
                        type_text(value)
                    else:
                        speak('I could not find the target field by text.')
            elif action == 'run_skill':
                if not SETTINGS.get("features", {}).get("skills", False):
                    speak('Skills are disabled in settings.')
                    continue
                name = step.get('name', '')
                payload = step.get('payload', {})
                res = run_skill(name, payload)
                if res is not None:
                    out = str(res)
                    print('Skill result:', out)
                    speak(out[:200])
            elif action == 'update_skill':
                if not SETTINGS.get("features", {}).get("skills", False):
                    speak('Skills are disabled in settings.')
                elif not SETTINGS.get('dev_mode'):
                    speak('Developer mode is off; code updates are blocked.')
                else:
                    name = step.get('name', '')
                    code = step.get('code', '')
                    ok, msg = update_skill(name, code)
                    speak(msg)
            elif action == 'show_grid':
                if not SETTINGS.get("features", {}).get("grid_nav", True):
                    speak('Grid navigation is disabled in settings.')
                    continue
                _ui = get_ui()
                fn = getattr(_ui, 'show_grid_overlay', None) if _ui else None
                if callable(fn):
                    fn()
                else:
                    speak('Grid overlay not available.')
            elif action == 'hide_grid':
                if not SETTINGS.get("features", {}).get("grid_nav", True):
                    continue
                _ui = get_ui()
                fn = getattr(_ui, 'hide_grid_overlay', None) if _ui else None
                if callable(fn):
                    fn()
                else:
                    speak('Grid overlay not available.')
            elif action == 'key':
                keys = step.get('keys', '')
                press_keys(keys)
            elif action == 'chat':
                resp = step.get('response', '')
                print('AI:', resp)
                speak(resp)
            elif action == 'confirm':
                resp = step.get('response', '')
                print('AI:', resp)
                speak(resp)
                confirmation = listen().lower()
                if 'yes' in confirmation:
                    continue
                else:
                    speak('Workflow cancelled.')
                    break
            else:
                speak('Sorry, I did not understand the AI workflow step.')
    except Exception as e:
        print('AI raw response:', ai_response)
        speak('Sorry, I could not process the AI response.')
        print('Error:', e)

def main():
    speak(f"Hello! I am {AGENT_NAME}, your smart assistant. How can I help you today?")
    while True:
        user_input = listen()
        if user_input:
            if 'exit' in user_input.lower() or 'बंद' in user_input:
                speak('Goodbye!')
                break
            ai_response = get_ai_response(user_input)
            handle_ai_response(ai_response)

if __name__ == '__main__':
    main()

# ===== Screen observation helpers =====
def _get_pytesseract():
    """Attempt to import pytesseract and configure tesseract_cmd if provided. Returns (module_or_None, error_str_or_None)."""
    try:
        import pytesseract as _pt
        cmd = SETTINGS.get('tesseract_cmd')
        if cmd:
            try:
                _pt.pytesseract.tesseract_cmd = cmd
            except Exception:
                pass
        return _pt, None
    except Exception as e:
        return None, str(e)


def screen_ocr() -> str:
    try:
        _pt, err = _get_pytesseract()
        if _pt is None:
            print('pytesseract not available:', err)
            return ''
        img = pyautogui.screenshot()
        gray = img.convert('L')
        text = _pt.image_to_string(gray)
        return text or ''
    except Exception as e:
        print('OCR failed:', e)
        return ''

def click_by_text(target: str, clicks: int = 1, move_only: bool = False) -> bool:
    try:
        if not target:
            return False
        _pt, err = _get_pytesseract()
        if _pt is None:
            print('pytesseract not available:', err)
            return False
        target_l = target.strip().lower()
        img = pyautogui.screenshot()
        gray = img.convert('L')
        data = _pt.image_to_data(gray, output_type=_pt.Output.DICT)
        best_idx = -1
        best_score = 0.0
        for i, txt in enumerate(data.get('text', [])):
            t = (txt or '').strip()
            if not t:
                continue
            tl = t.lower()
            score = 1.0 if target_l == tl else (0.7 if target_l in tl or tl in target_l else 0.0)
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx >= 0:
            x = int(data['left'][best_idx]) + int(data['width'][best_idx]) // 2
            y = int(data['top'][best_idx]) + int(data['height'][best_idx]) // 2
            pyautogui.moveTo(x, y, duration=0.15)
            if not move_only:
                if clicks >= 2:
                    pyautogui.doubleClick()
                elif clicks == 1:
                    pyautogui.click()
            return True
        return False
    except Exception as e:
        print('click_by_text failed:', e)
        return False

def ocr_is_available() -> tuple[bool, str | None]:
    """Quick check whether OCR stack is usable."""
    _pt, err = _get_pytesseract()
    if _pt is None:
        return False, err
    try:
        # quick noop to ensure tesseract path is respected
        _ = _pt.get_tesseract_version()
        return True, None
    except Exception as e:
        return False, str(e)


def test_ocr() -> tuple[bool, str]:
    """Quick OCR self-test. Uses a generated image if PIL is available; otherwise falls back to version check."""
    _pt, err = _get_pytesseract()
    if _pt is None:
        return False, f"pytesseract not available: {err}"
    # Try with a generated image containing known text
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        img = Image.new("L", (400, 120), color=255)
        draw = ImageDraw.Draw(img)
        text = "Barbaric OCR OK"
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        draw.text((20, 35), text, fill=0, font=font)
        out = _pt.image_to_string(img)
        if "barbaric" in (out or '').lower() and "ocr" in (out or '').lower():
            return True, f"Success: {out.strip()}"
        return False, f"Unexpected OCR result: {out.strip()}"
    except Exception:
        # Fallback: report Tesseract version as a minimal verification
        try:
            ver = _pt.get_tesseract_version()
            return True, f"Tesseract available: {ver}"
        except Exception as e2:
            return False, f"Tesseract not working: {e2}"


# ===== Cursor navigation helpers =====
def cursor_nav(direction: str, amount: int | None = None):
    try:
        direction = (direction or '').lower()
        step = SETTINGS.get('cursor_step', 80)
        dist = int(amount) if amount is not None else int(step)
        sw, sh = pyautogui.size()
        x, y = pyautogui.position()
        if direction == 'up':
            y = max(0, y - dist)
        elif direction == 'down':
            y = min(sh - 1, y + dist)
        elif direction == 'left':
            x = max(0, x - dist)
        elif direction == 'right':
            x = min(sw - 1, x + dist)
        elif direction in ('center', 'centre'):
            x, y = sw // 2, sh // 2
        elif direction == 'top_left':
            x, y = 0 + 10, 0 + 10
        elif direction == 'top_right':
            x, y = sw - 10, 0 + 10
        elif direction == 'bottom_left':
            x, y = 0 + 10, sh - 10
        elif direction == 'bottom_right':
            x, y = sw - 10, sh - 10
        else:
            speak('Unknown cursor direction.')
            return
        pyautogui.moveTo(x, y, duration=0.12)
    except Exception as e:
        print('cursor_nav error:', e)


def grid_nav(cell):
    try:
        # Map 1..9 like numpad to a 3x3 grid across the screen
        if isinstance(cell, str) and cell.isdigit():
            cell = int(cell)
        if not isinstance(cell, int) or not (1 <= cell <= 9):
            speak('Unknown grid cell.')
            return
        sw, sh = pyautogui.size()
        thirds_x = [int(sw * 1/6), int(sw * 3/6), int(sw * 5/6)]
        thirds_y = [int(sh * 5/6), int(sh * 3/6), int(sh * 1/6)]  # 1 is bottom-left, 9 top-right
        grid_map = {
            1: (thirds_x[0], thirds_y[0]), 2: (thirds_x[1], thirds_y[0]), 3: (thirds_x[2], thirds_y[0]),
            4: (thirds_x[0], thirds_y[1]), 5: (thirds_x[1], thirds_y[1]), 6: (thirds_x[2], thirds_y[1]),
            7: (thirds_x[0], thirds_y[2]), 8: (thirds_x[1], thirds_y[2]), 9: (thirds_x[2], thirds_y[2]),
        }
        x, y = grid_map[cell]
        pyautogui.moveTo(x, y, duration=0.12)
    except Exception as e:
        print('grid_nav error:', e)


# ===== Self-evolving skills system =====
_SKILLS: dict[str, types.ModuleType] = {}
_UI_REF: object | None = None


def register_ui(ui_obj: object):
    """Called by UI to allow main to control overlays, etc."""
    global _UI_REF
    _UI_REF = ui_obj


def get_ui() -> object | None:
    return _UI_REF


def skills_dir() -> Path:
    base = Path(__file__).resolve().parent
    return base / 'skills'


def load_skills() -> None:
    global _SKILLS
    _SKILLS = {}
    sdir = skills_dir()
    if not sdir.exists():
        return
    for path in sdir.glob('*.py'):
        name = path.stem
        mod = _import_module_from_path(f'voice_agent.skills.{name}', path)
        if mod is not None:
            _SKILLS[name] = mod


def reload_skills() -> None:
    load_skills()


def run_skill(name: str, payload: dict | None = None):
    try:
        if not name:
            return 'No skill name provided.'
        if not _SKILLS:
            load_skills()
        mod = _SKILLS.get(name)
        if not mod:
            return f'Skill {name} not found.'
        fn = getattr(mod, 'run', None)
        if not callable(fn):
            return f'Skill {name} has no run()'
        ctx = {
            'os': platform.system(),
            'python': platform.python_version(),
        }
        return fn(payload or {}, ctx)
    except Exception as e:
        return f'Skill error: {e}'


def update_skill(name: str, code: str) -> tuple[bool, str]:
    try:
        if not name or not code:
            return False, 'Missing skill name or code.'
        # Restrict to safe filename
        safe = ''.join(ch for ch in name if ch.isalnum() or ch in ('_', '-')).strip('_-')
        if not safe:
            return False, 'Invalid skill name.'
        sdir = skills_dir()
        sdir.mkdir(parents=True, exist_ok=True)
        fpath = sdir / f'{safe}.py'
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(code)
        # Load/Reload module
        mod = _import_module_from_path(f'voice_agent.skills.{safe}', fpath)
        if mod is None:
            return False, 'Failed to load updated skill.'
        _SKILLS[safe] = mod
        return True, f'Skill {safe} updated.'
    except Exception as e:
        return False, f'Update failed: {e}'


def _import_module_from_path(fullname: str, path: Path) -> types.ModuleType | None:
    try:
        spec = importlib.util.spec_from_file_location(fullname, str(path))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            return mod
        return None
    except Exception as e:
        print('Import skill failed:', e)
        return None
