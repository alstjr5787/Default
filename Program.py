# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, scrolledtext
import configparser
import os
import sys
from datetime import datetime, date
import asyncio
import threading
import requests
import re
import telegram
from telegram import Update
from telegram import Bot # Explicitly import Bot for type hinting and direct use
from telegram.ext import Application as BotApplication, MessageHandler, filters, ContextTypes
from PIL import ImageGrab
import time # Needed for potential sleep in area selector if needed
import traceback # For detailed error logging
import platform     # *** 추가/수정됨 ***
import subprocess   # *** 추가/수정됨 ***
import pyperclip    # *** 추가/수정됨 *** (pip install pyperclip 필요)

# --- 전역 상수 ---
SETTINGS_FILE = 'Setting.ini'
LOGIN_PREFS_SECTION = 'LoginPreferences'
LOGIN_PREFS_USER_KEY = 'LastUsername'
LOGIN_PREFS_SAVE_KEY = 'SaveIDChecked'
CAPTURE_INTERVAL_KEY = 'CaptureIntervalMinutes'
USE_SPECIFIC_AREA_KEY = 'UseSpecificAreaCapture'
CAPTURE_X1_KEY = 'CaptureX1'
CAPTURE_Y1_KEY = 'CaptureY1'
CAPTURE_X2_KEY = 'CaptureX2'
CAPTURE_Y2_KEY = 'CaptureY2'
HARDWARE_ID_URL = "http://jukson.dothome.co.kr/hdd.txt" # *** 추가/수정됨 ***

# --- 전역 변수 (봇 컨트롤러용) ---
BOT_TOKEN = None
CHAT_ID = None
TELEGRAM_BOT_APPLICATION = None
BOT_THREAD = None
BOT_EVENT_LOOP = None
CAPTURE_INTERVAL_MINUTES = 30
USE_SPECIFIC_AREA_CAPTURE = False
CAPTURE_COORDS = {'x1': 0, 'y1': 0, 'x2': 0, 'y2': 0}

# --- GUI 요소 전역 참조 (봇 컨트롤러용) ---
PERIODIC_CAPTURE_ACTIVE = True # 자동 캡처 활성화 상태 (기본값: 활성)
token_entry_main_app = None
chat_id_entry_main_app = None
start_bot_button_main_app = None
stop_bot_button_main_app = None
log_text_widget_main_app = None
bot_status_label_main_app = None
interval_minutes_entry_main_app = None
use_specific_area_var_main_app = None
specific_area_checkbox_main_app = None
coord_x1_entry_main_app = None
coord_y1_entry_main_app = None
coord_x2_entry_main_app = None
coord_y2_entry_main_app = None
coords_entry_widgets_main_app = []
select_area_button_main_app = None # 영역 선택 버튼 전역 참조 추가

original_stdout = sys.stdout
original_stderr = sys.stderr
_main_app_root_ref = None


# --- TextRedirector 클래스 ---
class TextRedirector:
    def __init__(self, widget):
        self.widget = widget

    def write(self, st):
        if not self.widget or not self.widget.winfo_exists(): return
        try:
            self.widget.configure(state='normal')
            lines = st.splitlines(True)
            for line in lines:
                prefix = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] " if line.strip() else ""
                self.widget.insert(tk.END, prefix + line)
            self.widget.see(tk.END)
            self.widget.configure(state='disabled')
        except tk.TclError:
            pass
        except Exception:
            pass # GUI 파괴 시 발생하는 일반 예외 무시

    def flush(self):
        pass


# --- GUI 작업 스케줄링 및 메시지 박스 헬퍼 ---
def schedule_gui_task(task, *args):
    if _main_app_root_ref and _main_app_root_ref.winfo_exists():
        _main_app_root_ref.after_idle(task, *args)
    # *** 추가/수정됨: 로그인 창에서도 스케줄링 가능하도록 수정 ***
    elif hasattr(sys, '_login_window_ref_') and sys._login_window_ref_.winfo_exists():
        # print("Debug: Scheduling task for login window")
        sys._login_window_ref_.after_idle(task, *args)
    else:
        # print("Debug: No valid root/window for schedule_gui_task")
        pass

def _show_messagebox_error_main_thread(title, message):
    """Shows error messagebox, potentially delayed on macOS."""
    print(f"📦 Scheduling Error Messagebox: Title='{title}', Message='{message[:100]}...'")
    parent_window = _main_app_root_ref if _main_app_root_ref and _main_app_root_ref.winfo_exists() else getattr(sys, '_login_window_ref_', None)
    if parent_window and parent_window.winfo_exists():
        parent_window.after(50, lambda t=title, m=message, p=parent_window: messagebox.showerror(t, m, parent=p))
    else:
         print("   - Warning: No valid parent window for error messagebox.")

def _show_messagebox_showinfo_main_thread(title, message):
    """Shows info messagebox, potentially delayed on macOS."""
    print(f"📦 Scheduling Info Messagebox: Title='{title}', Message='{message[:100]}...'")
    parent_window = _main_app_root_ref if _main_app_root_ref and _main_app_root_ref.winfo_exists() else getattr(sys, '_login_window_ref_', None)
    if parent_window and parent_window.winfo_exists():
        parent_window.after(50, lambda t=title, m=message, p=parent_window: messagebox.showinfo(t, m, parent=p))
    else:
         print("   - Warning: No valid parent window for info messagebox.")

def _show_messagebox_showwarning_main_thread(title, message):
    """Shows warning messagebox, potentially delayed on macOS."""
    print(f"📦 Scheduling Warning Messagebox: Title='{title}', Message='{message[:100]}...'")
    parent_window = _main_app_root_ref if _main_app_root_ref and _main_app_root_ref.winfo_exists() else getattr(sys, '_login_window_ref_', None)
    if parent_window and parent_window.winfo_exists():
        parent_window.after(50, lambda t=title, m=message, p=parent_window: messagebox.showwarning(t, m, parent=p))
    else:
         print("   - Warning: No valid parent window for warning messagebox.")


def _update_button_state_main_app(button, state):
    if button and button.winfo_exists(): button.config(state=state)

def _update_bot_status_label_main_app(is_running):
    global bot_status_label_main_app
    if not bot_status_label_main_app or not bot_status_label_main_app.winfo_exists(): return
    status_text, status_color = ("🟢 로직 실행 중", "green") if is_running else ("🔴 로직 중지됨", "red")
    bot_status_label_main_app.config(text=status_text, fg=status_color)


# --- GUI 값 변경 시 전역 변수 즉시 업데이트 함수 ---
def _update_global_interval_from_gui(event=None):
    global CAPTURE_INTERVAL_MINUTES, interval_minutes_entry_main_app
    if not interval_minutes_entry_main_app or not interval_minutes_entry_main_app.winfo_exists(): return
    try:
        val_str = interval_minutes_entry_main_app.get()
        val_int = int(val_str)
        if val_int > 0:
            if CAPTURE_INTERVAL_MINUTES != val_int:
                CAPTURE_INTERVAL_MINUTES = val_int
                print(f"ℹ️ 전송 간격 실시간 업데이트: {CAPTURE_INTERVAL_MINUTES} 분")
        else:
             print(f"⚠️ 전송 간격은 0보다 커야 합니다. ({val_int})")
             # Optionally revert to previous value or show warning
             interval_minutes_entry_main_app.delete(0, tk.END)
             interval_minutes_entry_main_app.insert(0, str(CAPTURE_INTERVAL_MINUTES)) # Revert
             _show_messagebox_showwarning_main_thread("입력 오류", "자동 전송 간격은 0보다 큰 숫자여야 합니다.")
    except ValueError:
        print(f"⚠️ 전송 간격은 숫자여야 합니다. ('{val_str}')")
        # Optionally revert or show warning
        if interval_minutes_entry_main_app.winfo_exists(): # Check again before reverting
            interval_minutes_entry_main_app.delete(0, tk.END)
            interval_minutes_entry_main_app.insert(0, str(CAPTURE_INTERVAL_MINUTES)) # Revert
            _show_messagebox_showwarning_main_thread("입력 오류", "자동 전송 간격은 숫자로 입력해야 합니다.")


# --- GUI 값 변경 시 전역 변수 즉시 업데이트 함수 ---
def _update_global_coords_from_gui(event=None):
    global CAPTURE_COORDS, USE_SPECIFIC_AREA_CAPTURE
    global coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app

    all_coord_entries = [coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app]
    if not all(entry and entry.winfo_exists() for entry in all_coord_entries): return

    coord_keys = ['x1', 'y1', 'x2', 'y2']
    temp_coords_int = {}
    current_gui_values = {} # Store current GUI values before attempting conversion

    try:
        for i, entry_widget in enumerate(all_coord_entries):
            val_str = entry_widget.get().strip()
            current_gui_values[coord_keys[i]] = val_str # Store the string value read
            if not val_str:
                 # Don't show error on empty field during focus out, just print info
                 print(f"ℹ️ 좌표 필드({coord_keys[i]}) 비어있음. 전역 변수 업데이트 안 함.")
                 return # Stop processing if any field is empty

            temp_coords_int[coord_keys[i]] = int(val_str) # Try conversion

        # Basic validation: x1 < x2 and y1 < y2
        x1, y1, x2, y2 = temp_coords_int['x1'], temp_coords_int['y1'], temp_coords_int['x2'], temp_coords_int['y2']
        if x1 < x2 and y1 < y2:
            if CAPTURE_COORDS != temp_coords_int:
                CAPTURE_COORDS = temp_coords_int.copy()
                #print(f"✅ 특정 영역 좌표 실시간 업데이트 완료: {CAPTURE_COORDS}")
        else:
            # Show warning messagebox if validation fails
            warning_msg = f"좌표값이 유효하지 않습니다.\nX1 ({x1})은 X2 ({x2})보다 작아야 하고,\nY1 ({y1})은 Y2 ({y2})보다 작아야 합니다."
            print(f"⚠️ {warning_msg}")
            # Use the HELPER function which now includes a delay
            _show_messagebox_showwarning_main_thread("좌표 오류", warning_msg)
            # Keep invalid values in GUI, but global CAPTURE_COORDS is not updated here

    except ValueError:
        # Show warning messagebox if conversion fails
        invalid_values = [v for v in current_gui_values.values() if not v.isdigit() and v]
        warning_msg = f"좌표값은 숫자로만 입력해야 합니다.\n잘못된 값: {invalid_values}"
        print(f"⚠️ {warning_msg}")
        # Use the HELPER function which now includes a delay
        _show_messagebox_showwarning_main_thread("입력 오류", warning_msg)
        # Keep invalid values in GUI, global CAPTURE_COORDS is not updated


def on_specific_area_toggle_changed():
    global use_specific_area_var_main_app, coords_entry_widgets_main_app, USE_SPECIFIC_AREA_CAPTURE, select_area_button_main_app

    if not use_specific_area_var_main_app: return
    is_checked = use_specific_area_var_main_app.get()
    USE_SPECIFIC_AREA_CAPTURE = is_checked
    #print(f"ℹ️ 특정 영역 사용 실시간 업데이트: {USE_SPECIFIC_AREA_CAPTURE}")
    new_state_entries = tk.NORMAL if is_checked else tk.DISABLED
    new_state_button = tk.NORMAL if is_checked else tk.DISABLED # Enable button only when checkbox is checked

    for entry_widget in coords_entry_widgets_main_app:
        if entry_widget and entry_widget.winfo_exists(): entry_widget.config(state=new_state_entries)

    # Update the select area button state
    if select_area_button_main_app and select_area_button_main_app.winfo_exists():
        select_area_button_main_app.config(state=new_state_button)

    # If enabling, read current values from GUI to update globals, in case they were changed while disabled
    if is_checked:
        _update_global_coords_from_gui()


# --- 로그인 환경설정 로드/저장 함수 ---
def load_login_preferences(filename=SETTINGS_FILE):
    config = configparser.ConfigParser()
    username = None
    save_checked = False
    if os.path.exists(filename):
        try:
            config.read(filename, encoding='utf-8')
            if config.has_section(LOGIN_PREFS_SECTION):
                username = config.get(LOGIN_PREFS_SECTION, LOGIN_PREFS_USER_KEY, fallback=None)
                save_checked = config.getboolean(LOGIN_PREFS_SECTION, LOGIN_PREFS_SAVE_KEY, fallback=False)
                if not username: save_checked = False # Ensure consistent state
        except Exception as e:
            print(f"❌ 로그인 환경설정 로드 중 오류: {e}")
            return None, False # Return default on error
    return username, save_checked


def save_login_preferences(username_to_save, save_id_bool, filename=SETTINGS_FILE):
    config = configparser.ConfigParser()
    try:
        if os.path.exists(filename):
            config.read(filename, encoding='utf-8')
        if not config.has_section(LOGIN_PREFS_SECTION):
            config.add_section(LOGIN_PREFS_SECTION)

        if save_id_bool and username_to_save:
            config.set(LOGIN_PREFS_SECTION, LOGIN_PREFS_USER_KEY, username_to_save)
            config.set(LOGIN_PREFS_SECTION, LOGIN_PREFS_SAVE_KEY, 'true')
        else:
            config.set(LOGIN_PREFS_SECTION, LOGIN_PREFS_USER_KEY, '')
            config.set(LOGIN_PREFS_SECTION, LOGIN_PREFS_SAVE_KEY, 'false')

        with open(filename, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        print(f"ℹ️ 로그인 환경설정 저장: 아이디 저장됨={save_id_bool and bool(username_to_save)}")
    except Exception as e:
        print(f"❌ 로그인 환경설정 저장 실패: {e}")

# *** 추가/수정됨: 하드웨어 ID 관련 함수 시작 ***
def get_serial_number():
    """Get serial number for Windows (disk) or macOS (platform)."""
    serial_number = None
    system = platform.system()
    print(f"ℹ️ 시스템 정보 확인: {system}")
    try:
        if system == "Windows":
            # Try WMIC first (might require admin on some systems)
            try:
                output = subprocess.check_output("wmic path win32_physicalmedia get SerialNumber", shell=True, stderr=subprocess.DEVNULL, timeout=5)
                lines = output.decode('utf-8', errors='ignore').split('\n')
                serials = [line.strip() for line in lines if line.strip() and line.strip().lower() != 'serialnumber']
                if serials: serial_number = serials[0]; print(f"✅ WMIC (PhysicalMedia) SerialNumber: {serial_number}")
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e_wmic1:
                print(f"⚠️ WMIC (PhysicalMedia) 실패: {e_wmic1}. DiskDrive 시도...")
                try:
                    output = subprocess.check_output("wmic diskdrive get SerialNumber", shell=True, stderr=subprocess.DEVNULL, timeout=5)
                    lines = output.decode('utf-8', errors='ignore').split('\n')
                    serials = [line.strip() for line in lines if line.strip() and line.strip().lower() != 'serialnumber']
                    if serials: serial_number = serials[0]; print(f"✅ WMIC (DiskDrive) SerialNumber: {serial_number}")
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e_wmic2:
                    print(f"⚠️ WMIC (DiskDrive) 실패: {e_wmic2}")
                    # Add fallback for Volume Serial Number if others fail
                    try:
                         output = subprocess.check_output("vol c:", shell=True, stderr=subprocess.DEVNULL, timeout=5)
                         lines = output.decode('utf-8', errors='ignore').splitlines()
                         for line in lines:
                              if "volume serial number is" in line.lower():
                                   serial_number = line.split(" is ")[-1].strip()
                                   print(f"✅ Volume Serial Number (vol c:): {serial_number}")
                                   break
                    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e_vol:
                         print(f"⚠️ Volume Serial Number (vol c:) 실패: {e_vol}")


        elif system == "Darwin": # macOS
            try:
                result = subprocess.check_output(
                    "ioreg -d2 -c IOPlatformExpertDevice | awk -F\\\" '/IOPlatformSerialNumber/{print $(NF-1)}'",
                    shell=True, stderr=subprocess.DEVNULL, timeout=5
                )
                serial_number = result.decode('utf-8', errors='ignore').strip()
                print(f"✅ macOS IOPlatformSerialNumber: {serial_number}")
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e_mac:
                 print(f"⚠️ macOS IOPlatformSerialNumber 가져오기 실패: {e_mac}")

        else: # Linux or other systems
            print(f"⚠️ 지원되지 않는 시스템({system}) 또는 시리얼 번호 조회 불가.")
            # Optionally try dmidecode on Linux if available and permissions allow
            # try:
            #     output = subprocess.check_output(['sudo', 'dmidecode', '-s', 'system-serial-number'], ...)
            # except: pass
            serial_number = None

    except Exception as e:
        print(f"❌ 시리얼 번호 조회 중 예상치 못한 오류: {e}")
        serial_number = None

    # Basic validation: Ensure it's not empty or just whitespace
    if serial_number and serial_number.strip():
         return serial_number.strip()
    else:
         print("❌ 유효한 시리얼 번호를 얻지 못했습니다.")
         return None


def check_serial_registration(serial_number_to_check):
    """Checks if the serial number is in the online list.
    Returns: True (registered), False (not registered), None (error during check).
    """
    if not serial_number_to_check:
        print("❌ 시리얼 번호가 없어 등록 여부를 확인할 수 없습니다.")
        return None # Indicate check couldn't be performed

    print(f"ℹ️ 서버에서 등록된 시리얼 목록 확인 중... (URL: {HARDWARE_ID_URL})")
    try:
        response = requests.get(HARDWARE_ID_URL, timeout=10) # Add timeout
        response.raise_for_status() # Check for HTTP errors (4xx, 5xx)

        registered_serials = [s.strip() for s in response.text.splitlines() if s.strip()]
        print(f"   - 서버에서 {len(registered_serials)}개의 시리얼 로드됨.")

        is_found = serial_number_to_check in registered_serials
        if is_found:
            print(f"✅ 시리얼 번호 '{serial_number_to_check}'가 서버 목록에 등록되어 있습니다.")
            return True
        else:
            print(f"⚠️ 시리얼 번호 '{serial_number_to_check}'가 서버 목록에 없습니다.")
            return False

    except requests.exceptions.Timeout:
        print(f"❌ 서버 연결 시간 초과 ({HARDWARE_ID_URL}). 등록 확인 실패.")
        return None # Indicate error
    except requests.exceptions.HTTPError as e:
         print(f"❌ 서버 응답 오류 ({e.response.status_code}) ({HARDWARE_ID_URL}). 등록 확인 실패.")
         return None
    except requests.exceptions.RequestException as e:
        print(f"❌ 서버 연결 오류 ({HARDWARE_ID_URL}): {e}. 등록 확인 실패.")
        return None # Indicate error
    except Exception as e:
        print(f"❌ 등록 여부 확인 중 예상치 못한 오류: {e}")
        return None # Indicate error
# *** 추가/수정됨: 하드웨어 ID 관련 함수 끝 ***


# --- 새 라이선스 코드 입력 창 클래스 ---
class CodeUpdateWindow(tk.Toplevel):
    # ... (이전과 동일) ...
    pass


# --- LoginRegisterWindow 클래스 ---
class LoginRegisterWindow(tk.Toplevel):
    def __init__(self, master, success_callback_func):
        super().__init__(master)
        self.master_root = master
        self.success_callback = success_callback_func
        self.title("로그인 및 회원가입")
        window_width = 400
        window_height = 300 # Reduced height slightly
        center_x = int(self.winfo_screenwidth() / 2 - window_width / 2)
        center_y = int(self.winfo_screenheight() / 2 - window_height / 2)
        self.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_closing_login_window)
        self.attributes('-topmost', True) # Keep login window on top initially
        sys._login_window_ref_ = self # *** 추가/수정됨: 스케줄러에서 참조할 수 있도록 설정 ***

        self.tabs = ttk.Notebook(self)
        self.login_tab = ttk.Frame(self.tabs, padding="10")
        self.register_tab = ttk.Frame(self.tabs, padding="10")
        self.tabs.add(self.login_tab, text="로그인")
        self.tabs.add(self.register_tab, text="회원가입")
        self.tabs.pack(expand=1, fill="both")

        self._init_login_tab()
        self._init_register_tab()

        # Bind Enter key for convenience
        self.login_password_entry.bind("<Return>", lambda event: self._trigger_login())
        self.register_code_entry.bind("<Return>", lambda event: self._trigger_register())

    def destroy(self):
         # *** 추가/수정됨: 창 파괴 시 참조 제거 ***
         if hasattr(sys, '_login_window_ref_') and sys._login_window_ref_ == self:
              del sys._login_window_ref_
         super().destroy()

    def _on_closing_login_window(self):
        print("로그인 창 X 버튼 클릭됨. 프로그램 종료.")
        # Ensure main application root is properly destroyed
        if self.master_root and self.master_root.winfo_exists():
            self.master_root.destroy()
        else: # If master_root is somehow gone, exit process
             sys.exit("로그인 창 닫힘으로 인한 종료")

    # ... _init_login_tab, _init_register_tab (이전과 동일) ...
    def _init_login_tab(self):
        frame = self.login_tab # Use frame for consistency
        tk.Label(frame, text="아이디:").pack(pady=(5, 2), anchor='w')
        self.login_username_entry = tk.Entry(frame, width=40)
        self.login_username_entry.pack(fill='x', pady=(0, 5))

        tk.Label(frame, text="비밀번호:").pack(pady=(0, 2), anchor='w')
        self.login_password_entry = tk.Entry(frame, show="*", width=40)
        self.login_password_entry.pack(fill='x', pady=(0, 5))

        self.save_id_var = tk.BooleanVar()
        self.save_id_checkbox = tk.Checkbutton(frame, text="아이디 저장", variable=self.save_id_var)
        self.save_id_checkbox.pack(anchor='w', pady=(0, 10))

        self.login_button = tk.Button(frame, text="로그인", command=self._trigger_login, width=15, height=2)
        self.login_button.pack(pady=5)

        # Load saved preferences
        saved_username, save_id_status = load_login_preferences()
        if saved_username:
            self.login_username_entry.insert(0, saved_username)
            if save_id_status: # Focus password if ID is saved
                self.login_password_entry.focus_set()
            else: # Focus username if ID not saved or empty
                self.login_username_entry.focus_set()
        else:
             self.login_username_entry.focus_set() # Focus username if nothing saved
        self.save_id_var.set(save_id_status)

    def _init_register_tab(self):
        frame = self.register_tab
        tk.Label(frame, text="아이디:").pack(pady=(5, 2), anchor='w')
        self.register_username_entry = tk.Entry(frame, width=40)
        self.register_username_entry.pack(fill='x', pady=(0, 5))

        tk.Label(frame, text="비밀번호:").pack(pady=(0, 2), anchor='w')
        self.register_password_entry = tk.Entry(frame, show="*", width=40)
        self.register_password_entry.pack(fill='x', pady=(0, 5))

        tk.Label(frame, text="라이선스 코드:").pack(pady=(0, 2), anchor='w') # Renamed label
        self.register_code_entry = tk.Entry(frame, width=40)
        self.register_code_entry.pack(fill='x', pady=(0, 10))

        self.register_button = tk.Button(frame, text="회원가입", command=self._trigger_register, width=15, height=2)
        self.register_button.pack(pady=5)

    def _set_ui_state_during_request(self, is_requesting):
        state = tk.DISABLED if is_requesting else tk.NORMAL
        # Check existence before configuring
        if hasattr(self, 'login_button') and self.login_button.winfo_exists():
            self.login_button.config(state=state)
        if hasattr(self, 'register_button') and self.register_button.winfo_exists():
            self.register_button.config(state=state)

    # ... _handle_expired_license, _on_code_update_finished (이전과 동일) ...
    def _handle_expired_license(self, username):
        if not self.winfo_exists(): return
        user_choice = messagebox.askyesno("라이선스 만료", "만료된 회원입니다. 코드 등록이 필요합니다.\n새 코드를 등록하시겠습니까?", parent=self)
        if user_choice:
            print(f"사용자 '{username}'가 새 코드 등록을 선택했습니다.")
            # Pass self (LoginRegisterWindow) as the master for CodeUpdateWindow
            code_window = CodeUpdateWindow(self, username, self._on_code_update_finished)
            # grab_set() is handled inside CodeUpdateWindow now
        else:
            print("사용자가 새 코드 등록을 거부했습니다.")
            # Show info message in main thread
            _show_messagebox_showinfo_main_thread("알림", "라이선스 갱신 없이 프로그램을 사용할 수 없습니다.")
            # Re-enable login button after user dismissal
            schedule_gui_task(self._set_ui_state_during_request, False)

    def _on_code_update_finished(self, username, success, message):
        if not self.winfo_exists(): return
        if success:
            # Use the delayed messagebox helper
            _show_messagebox_showinfo_main_thread("알림", f"{message}\n다시 로그인해주세요.")
            # Clear only password field, keep username
            if hasattr(self, 'login_password_entry') and self.login_password_entry.winfo_exists():
                self.login_password_entry.delete(0, tk.END)
            # Focus password field after successful code update
            if hasattr(self, 'login_password_entry') and self.login_password_entry.winfo_exists():
                 self.login_password_entry.focus_set()

        else:
            # Use the delayed messagebox helper
            _show_messagebox_error_main_thread("코드 등록 실패", message)
        # Always re-enable buttons after code update attempt
        self._set_ui_state_during_request(False)


    # *** 추가/수정됨: _login_task 에 하드웨어 ID 체크 로직 통합 ***
    def _login_task(self, username, password):
        # Save preferences regardless of login outcome
        save_id_pref = self.save_id_var.get()
        save_login_preferences(username if save_id_pref else "", save_id_pref)

        try:
            url = 'http://jukson.dothome.co.kr/License_login.php'
            data = {'username': username, 'password': password, 'submit': 'login'}
            response = requests.post(url, data=data, timeout=15)
            response.raise_for_status()
            result = response.text.strip()

            if result.startswith('로그인 성공'):
                print("✅ 로그인 인증 성공. 하드웨어 ID 확인 중...")

                # --- 하드웨어 ID 체크 시작 ---
                serial_number = get_serial_number()
                if not serial_number:
                    # 시리얼 번호 조회 실패 시 오류 메시지 표시 및 로그인 중단
                    schedule_gui_task(_show_messagebox_error_main_thread, "인증 오류", "하드웨어 시리얼 번호를 가져올 수 없습니다.\n관리자에게 문의하세요.")
                    schedule_gui_task(self._set_ui_state_during_request, False) # 버튼 활성화
                    return # 로그인 절차 중단

                # 서버에서 등록 여부 확인
                registration_status = check_serial_registration(serial_number)

                if registration_status is None:
                    # 서버 확인 중 오류 발생 시 메시지 표시 및 로그인 중단
                    schedule_gui_task(_show_messagebox_error_main_thread, "인증 오류", "하드웨어 등록 정보 확인 중 오류가 발생했습니다.\n네트워크 연결을 확인하거나 잠시 후 다시 시도하세요.")
                    schedule_gui_task(self._set_ui_state_during_request, False) # 버튼 활성화
                    return # 로그인 절차 중단

                if registration_status is False:
                    # 등록되지 않은 시리얼 번호일 경우
                    try:
                        pyperclip.copy(serial_number)
                        print(f"📋 시리얼 번호 '{serial_number}' 클립보드에 복사됨.")
                        msg = f"등록되지 않은 사용자입니다.\n시리얼: {serial_number}\n\n(시리얼 번호가 클립보드에 복사되었습니다)"
                    except Exception as e_clip:
                         print(f"❌ 클립보드 복사 중 오류: {e_clip}")
                         msg = f"등록되지 않은 사용자입니다.\n시리얼: {serial_number}\n\n(클립보드 복사 실패)"

                    schedule_gui_task(_show_messagebox_showwarning_main_thread, "미등록 사용자", msg)
                    schedule_gui_task(self._set_ui_state_during_request, False) # 버튼 활성화
                    return # 로그인 절차 중단
                # --- 하드웨어 ID 체크 끝 (등록된 사용자) ---

                print("✅ 하드웨어 ID 등록 확인됨. 라이선스 만료일 확인 중...")
                # 등록된 사용자이므로 기존 라이선스 만료일 확인 로직 진행
                expired_date_obj = self._get_expired_date_task(username)
                if expired_date_obj:
                    days_left = (expired_date_obj - date.today()).days
                    if days_left >= 0:
                        print(f"✅ 라이선스 유효. 남은 기간: {days_left}일.")
                        schedule_gui_task(_show_messagebox_showinfo_main_thread, "로그인 성공", f"등록된 사용자입니다.\n남은 기간: {days_left}일")
                        schedule_gui_task(self.success_callback, days_left)
                        schedule_gui_task(self.destroy)
                    else: # 만료 (days_left < 0)
                        print(f"⚠️ 라이선스 만료됨 (만료일: {expired_date_obj}).")
                        schedule_gui_task(self._handle_expired_license, username)
                        # 버튼 상태는 _handle_expired_license 에서 관리됨
                else: # 만료일 정보 가져오기 실패
                    schedule_gui_task(_show_messagebox_error_main_thread, "로그인 오류", "라이선스 만료일 정보를 가져올 수 없습니다.\n관리자에게 문의하세요.")
                    schedule_gui_task(self._set_ui_state_during_request, False) # 버튼 활성화

            else: # 로그인 실패 (ID/PW 불일치 등 서버 메시지)
                schedule_gui_task(_show_messagebox_error_main_thread, "로그인 실패", result)
                schedule_gui_task(self._set_ui_state_during_request, False) # 버튼 활성화

        except requests.exceptions.Timeout:
             schedule_gui_task(_show_messagebox_error_main_thread, "연결 에러", "로그인 서버 연결 시간 초과 (15초).\n인터넷 연결을 확인하세요.")
             schedule_gui_task(self._set_ui_state_during_request, False)
        except requests.exceptions.HTTPError as e:
             schedule_gui_task(_show_messagebox_error_main_thread, "서버 에러", f"서버 응답 오류: {e.response.status_code}.\n잠시 후 다시 시도하거나 관리자에게 문의하세요.")
             schedule_gui_task(self._set_ui_state_during_request, False)
        except requests.exceptions.RequestException as e:
            schedule_gui_task(_show_messagebox_error_main_thread, "연결 에러", f"서버 연결 중 문제 발생:\n{e}")
            schedule_gui_task(self._set_ui_state_during_request, False)
        except Exception as e:
            print(f"❌ 로그인 처리 중 예상치 못한 오류: {e}") # 상세 로그 추가
            print(traceback.format_exc())
            schedule_gui_task(_show_messagebox_error_main_thread, "처리 에러", f"로그인 처리 중 알 수 없는 오류:\n{e}")
            schedule_gui_task(self._set_ui_state_during_request, False)


    # ... _get_expired_date_task, _register_task, _clear_register_fields, _trigger_login, _trigger_register (이전과 동일) ...
    def _get_expired_date_task(self, username):
        try:
            url = 'http://jukson.dothome.co.kr/License_user.php'
            response = requests.get(url, timeout=15) # Increased timeout
            response.raise_for_status()
            html_content = response.text

            # Improved Regex to handle variations in spacing and case
            pattern = re.compile(
                r'Username:\s*(.*?)\s*-\s*Expired Date:\s*(\d{4}-\d{2}-\d{2})',
                re.IGNORECASE | re.MULTILINE
            )
            matches = pattern.findall(html_content)

            for found_user, date_str in matches:
                if found_user.strip().lower() == username.lower():
                    try:
                        return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
                    except ValueError:
                        print(f"❌ 날짜 형식 오류: '{date_str}' for user '{username}'")
                        return None # Found user but invalid date format

            print(f"❌ 사용자 '{username}'의 만료일 정보를 찾을 수 없습니다.")
            return None # User not found in the list

        except requests.exceptions.Timeout:
            print(f"❌ 만료일 정보 가져오기 시간 초과 (15초)")
        except requests.exceptions.HTTPError as e:
            print(f"❌ 만료일 정보 가져오기 서버 오류: {e.response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"❌ 만료일 정보 가져오기 연결 오류: {e}")
        except Exception as e:
            print(f"❌ 만료일 정보 처리 중 알 수 없는 오류: {e}")
        return None

    def _register_task(self, username, password, code):
        try:
            url = 'http://jukson.dothome.co.kr/License_register_process.php'
            data = {'username': username, 'password': password, 'code': code}
            response = requests.post(url, data=data, timeout=15) # Increased timeout
            response.raise_for_status()
            result = response.text.strip()
            # Show result, whether success or failure message from server
            # Use the delayed messagebox helper
            schedule_gui_task(_show_messagebox_showinfo_main_thread, "회원가입 결과", result)
            # If registration is successful, clear fields and switch to login tab
            if "성공" in result or "successfully" in result.lower():
                 schedule_gui_task(self._clear_register_fields)
                 schedule_gui_task(self.tabs.select, self.login_tab) # Switch to login tab
                 schedule_gui_task(self.login_username_entry.focus_set)

        except requests.exceptions.Timeout:
             schedule_gui_task(_show_messagebox_error_main_thread, "연결 에러", "회원가입 서버 연결 시간 초과 (15초).")
        except requests.exceptions.HTTPError as e:
             schedule_gui_task(_show_messagebox_error_main_thread, "서버 에러", f"서버 응답 오류: {e.response.status_code}.\n{e.response.text[:100]}")
        except requests.exceptions.RequestException as e:
            schedule_gui_task(_show_messagebox_error_main_thread, "연결 에러", f"회원가입 요청 중 문제 발생:\n{e}")
        except Exception as e:
            schedule_gui_task(_show_messagebox_error_main_thread, "처리 에러", f"회원가입 처리 중 알 수 없는 오류:\n{e}")
        finally:
            schedule_gui_task(self._set_ui_state_during_request, False) # Always re-enable button

    def _clear_register_fields(self):
        if hasattr(self, 'register_username_entry') and self.register_username_entry.winfo_exists(): self.register_username_entry.delete(0, tk.END)
        if hasattr(self, 'register_password_entry') and self.register_password_entry.winfo_exists(): self.register_password_entry.delete(0, tk.END)
        if hasattr(self, 'register_code_entry') and self.register_code_entry.winfo_exists(): self.register_code_entry.delete(0, tk.END)

    def _trigger_login(self):
        username = self.login_username_entry.get().strip()
        password = self.login_password_entry.get().strip()
        if not (username and password):
             # Use the delayed messagebox helper
             _show_messagebox_showwarning_main_thread("입력 오류", "아이디와 비밀번호를 모두 입력하세요.")
             return
        self._set_ui_state_during_request(True) # Disable buttons
        threading.Thread(target=self._login_task, args=(username, password), daemon=True).start()

    def _trigger_register(self):
        username = self.register_username_entry.get().strip()
        password = self.register_password_entry.get().strip()
        code = self.register_code_entry.get().strip()
        if not (username and password and code):
            # Use the delayed messagebox helper
            _show_messagebox_showwarning_main_thread("입력 오류", "아이디, 비밀번호, 라이선스 코드를 모두 입력하세요.")
            return
        # Basic validation (example: username length)
        if len(username) < 4:
            # Use the delayed messagebox helper
            _show_messagebox_showwarning_main_thread("입력 오류", "아이디는 4자 이상이어야 합니다.")
            return
        self._set_ui_state_during_request(True) # Disable buttons
        threading.Thread(target=self._register_task, args=(username, password, code), daemon=True).start()


# --- 화면 영역 선택 창 (Canvas bg 수정됨) ---
class ScreenAreaSelector(tk.Toplevel):
    """마우스 드래그로 화면 영역을 선택하는 Toplevel 창 클래스"""
    def __init__(self, master, callback_on_select):
        print("  [ScreenAreaSelector] Initializing...") # Log start
        super().__init__(master)
        self.master = master
        self.callback = callback_on_select
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        # Canvas 옵션을 저장할 딕셔너리 사용
        self.canvas_options = {"cursor": "crosshair", "highlightthickness": 0}

        try:
            print("  [ScreenAreaSelector] Setting geometry...")
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            self.geometry(f"{screen_width}x{screen_height}+0+0")
            print("  [ScreenAreaSelector] Setting overrideredirect...")
            self.overrideredirect(True)

            # Transparency - Attempt with waiting for visibility
            alpha_success = False
            try:
                print("  [ScreenAreaSelector] Waiting for visibility...")
                self.wait_visibility() # Wait for window to be mapped
                print("  [ScreenAreaSelector] Setting alpha attribute...")
                self.attributes('-alpha', 0.3)
                alpha_success = True # Mark alpha as successful
                print("  [ScreenAreaSelector] Alpha set successfully.")
                # Alpha 성공 시 canvas_options에서 bg 제거 (기본값 사용)
            except tk.TclError as e:
                print(f"  [ScreenAreaSelector] Warning: Alpha attribute failed: {e}. Using grey background.")
                self.config(bg='grey') # Set window background as fallback
                self.canvas_options['bg'] = 'grey' # Set canvas background explicitly
            except Exception as e:
                 print(f"  [ScreenAreaSelector] Warning: Unexpected error during alpha setting: {e}. Using grey background.")
                 self.config(bg='grey')
                 self.canvas_options['bg'] = 'grey'

            print("  [ScreenAreaSelector] Setting topmost attribute...")
            self.attributes('-topmost', True)

            print(f"  [ScreenAreaSelector] Creating Canvas with options: {self.canvas_options}...")
            # 준비된 옵션 딕셔너리를 사용하여 Canvas 생성
            self.canvas = tk.Canvas(self, **self.canvas_options)
            self.canvas.pack(fill="both", expand=True)
            print("  [ScreenAreaSelector] Canvas created.")

            print("  [ScreenAreaSelector] Creating Info Label...")
            # Ensure label background matches canvas or is distinct
            label_bg = "black" if alpha_success else "grey" # Adjust label bg based on alpha
            self.info_label = tk.Label(self.canvas, text="화면 영역을 드래그하여 선택하세요 (취소: Esc)",
                                       bg=label_bg, fg="white", font=("Arial", 14))
            self.info_label.place(relx=0.5, rely=0.05, anchor=tk.CENTER)

            print("  [ScreenAreaSelector] Binding events...")
            self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
            self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)
            self.bind("<Escape>", self.cancel_selection)

            print("  [ScreenAreaSelector] Setting grab...")
            self.grab_set()

            print("  [ScreenAreaSelector] Forcing focus...")
            self.focus_force()

            print("  [ScreenAreaSelector] Initialization complete.")

        except tk.TclError as e:
            print(f"❌ [ScreenAreaSelector] TclError during initialization: {e}")
            self.after_idle(self.destroy)
            raise
        except Exception as e:
            print(f"❌ [ScreenAreaSelector] Unexpected error during initialization: {e}")
            self.after_idle(self.destroy)
            raise

    def on_mouse_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = None
        if self.info_label and self.info_label.winfo_exists(): self.info_label.config(text="드래그 중...") # Update info text

    def on_mouse_drag(self, event):
        cur_x, cur_y = (event.x, event.y)
        if self.start_x is None or self.start_y is None: return # Avoid error if drag starts outside?

        if self.rect_id:
            self.canvas.delete(self.rect_id)

        x1, y1 = min(self.start_x, cur_x), min(self.start_y, cur_y)
        x2, y2 = max(self.start_x, cur_x), max(self.start_y, cur_y)

        self.rect_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline='red', width=2, dash=(4, 4) # Dashed outline
        )
        # Display current coordinates/size during drag
        if self.info_label and self.info_label.winfo_exists(): self.info_label.config(text=f"선택 중: ({x1},{y1}) - ({x2},{y2}) [{x2-x1}x{y2-y1}]")

    def on_mouse_release(self, event):
        end_x, end_y = (event.x, event.y)
        self.grab_release()
        # Use after_idle to destroy to avoid potential conflicts
        self.after_idle(self.destroy)

        # Ensure start coordinates exist (handle click without drag)
        if self.start_x is None or self.start_y is None:
            print("⚠️ 영역 선택 오류: 시작점 없음 (클릭만 함).")
            if self.callback: self.callback(None); return

        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        # Minimum size check (e.g., 10x10 pixels)
        if abs(x1 - x2) < 10 or abs(y1 - y2) < 10:
             print("⚠️ 영역 선택 취소됨 (선택 영역이 너무 작음: 10x10 미만).")
             if self.callback: self.callback(None); return

        print(f"영역 선택 완료: ({x1}, {y1}, {x2}, {y2})")
        if self.callback:
            # Call callback after slight delay to ensure selector is gone
            if self.master and self.master.winfo_exists():
                 self.master.after(10, self.callback, (x1, y1, x2, y2))

    def cancel_selection(self, event=None):
        print("ℹ️ 영역 선택 취소됨 (Escape).")
        self.grab_release()
        self.after_idle(self.destroy)
        if self.callback:
            # Call callback after slight delay to ensure selector is gone
            if self.master and self.master.winfo_exists():
                 self.master.after(10, self.callback, None)


# --- 영역 선택 결과 처리 콜백 ---
def update_coords_from_selection(selected_coords):
    """Callback function called by ScreenAreaSelector upon completion."""
    global coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app, use_specific_area_var_main_app

    if not _main_app_root_ref or not _main_app_root_ref.winfo_exists(): return # Main window gone

    if selected_coords:
        x1, y1, x2, y2 = selected_coords
        entries = [coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app]
        coords_values = [x1, y1, x2, y2]

        if all(entry and entry.winfo_exists() for entry in entries):
            #print(f"ℹ️ 영역 선택 결과로 좌표 엔트리 업데이트: {selected_coords}")
            current_state = tk.NORMAL if use_specific_area_var_main_app.get() else tk.DISABLED
            for i, entry in enumerate(entries):
                # Temporarily enable to insert text, then restore state
                entry.config(state=tk.NORMAL)
                entry.delete(0, tk.END)
                entry.insert(0, str(coords_values[i]))
                entry.config(state=current_state) # Restore original state

            # Trigger global update *after* GUI entries are populated
            schedule_gui_task(_update_global_coords_from_gui)
        else:
            print("❌ 영역 선택 콜백: 좌표 입력 위젯 중 일부가 존재하지 않습니다.")
    else:
        print("ℹ️ 영역 선택이 취소되었거나 유효하지 않습니다. 좌표 변경 없음.")

# --- 영역 선택기 여는 함수 ---
def open_area_selector():
    """Opens the screen area selection window."""
    if not _main_app_root_ref or not _main_app_root_ref.winfo_exists():
        print("❌ 영역 선택기 열기 실패: 메인 앱 창을 찾을 수 없습니다.")
        _show_messagebox_error_main_thread("오류", "메인 창을 찾을 수 없어 영역 선택기를 열 수 없습니다.")
        return

    print("화면 영역 선택 선택중...")
    try:
        # Instantiation might fail
        selector = ScreenAreaSelector(_main_app_root_ref, update_coords_from_selection)
        print("영역 선택기 창 생성 성공.")
        # Modality is handled by grab_set in the selector itself
    except tk.TclError as e:
         # Catch TclError specifically, often from grab_set or window attributes
         print(f"❌ 영역 선택기 생성 중 TclError 발생: {e}")
         # Print detailed traceback to console/log for debugging
         print(traceback.format_exc())
         _show_messagebox_error_main_thread("영역 선택 오류", f"화면 영역 선택 창을 여는 중 시스템 오류가 발생했습니다.\n(TclError: {e})\n\n로그를 확인해주세요.")
    except Exception as e:
        # Catch any other unexpected errors during creation
        print(f"❌ 영역 선택기 생성 중 예상치 못한 오류: {e}")
        print(traceback.format_exc()) # Print full traceback for debugging
        _show_messagebox_error_main_thread("오류", f"영역 선택기 실행 중 오류 발생:\n{e}\n\n로그를 확인해주세요.")


# --- 메인 앱 설정 로드/저장 ---
def save_settings_to_file_main_app(config_obj, filename=SETTINGS_FILE):
    try:
        with open(filename, 'w', encoding='utf-8') as configfile:
            config_obj.write(configfile)
        print(f"✅ 설정이 '{filename}' 파일에 저장되었습니다.")
        return True
    except Exception as e:
        print(f"❌ 설정 파일 저장 실패: {e}")
        _show_messagebox_error_main_thread("오류", f"설정 파일 저장 실패:\n{e}")
        return False

def load_settings_globally_main_app(filename=SETTINGS_FILE):
    global BOT_TOKEN, CHAT_ID, CAPTURE_INTERVAL_MINUTES, USE_SPECIFIC_AREA_CAPTURE, CAPTURE_COORDS
    global token_entry_main_app, chat_id_entry_main_app, interval_minutes_entry_main_app
    global use_specific_area_var_main_app, coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app

    # Define defaults directly here
    defaults = {
        'BOT_TOKEN': '', # Default to empty, user must input
        'CHAT_ID': '',   # Default to empty
        CAPTURE_INTERVAL_KEY: '30',
        USE_SPECIFIC_AREA_KEY: 'false',
        CAPTURE_X1_KEY: '0', CAPTURE_Y1_KEY: '0',
        CAPTURE_X2_KEY: '100', CAPTURE_Y2_KEY: '100' # Default non-zero area
    }
    config = configparser.ConfigParser()

    # Ensure file exists with basic structure if not present
    if not os.path.exists(filename):
        print(f"⚠️ 설정 파일 '{filename}'이 없어 기본값으로 새로 생성합니다.")
        config['Settings'] = defaults # Create Settings section with defaults
        if not config.has_section(LOGIN_PREFS_SECTION): config.add_section(LOGIN_PREFS_SECTION)
        config.set(LOGIN_PREFS_SECTION, LOGIN_PREFS_USER_KEY, '')
        config.set(LOGIN_PREFS_SECTION, LOGIN_PREFS_SAVE_KEY, 'false')
        save_settings_to_file_main_app(config, filename) # Save the new default file
        # Read it back to ensure consistency (though config object already has it)
        config.read(filename, encoding='utf-8')
    else:
        try:
             # Read existing file, using defaults for missing keys
            config.read(filename, encoding='utf-8')
        except Exception as e:
             print(f"❌ 설정 파일 '{filename}' 읽기 오류: {e}. 기본값을 사용합니다.")
             # Fallback: Use defaults if read fails
             config = configparser.ConfigParser() # Reset config object
             config['Settings'] = defaults # Apply defaults

    # Ensure 'Settings' section exists even if file was manually emptied
    if 'Settings' not in config:
        config['Settings'] = {} # Create empty section, defaults will apply via get()

    try:
        settings_section = 'Settings'
        # Use .get() with fallback to defaults dictionary
        BOT_TOKEN = config.get(settings_section, 'BOT_TOKEN', fallback=defaults['BOT_TOKEN'])
        chat_id_str = config.get(settings_section, 'CHAT_ID', fallback=defaults['CHAT_ID'])
        try:
            # Allow empty CHAT_ID, handle None case later
            CHAT_ID = int(chat_id_str) if chat_id_str else None
        except ValueError:
            CHAT_ID = None # Treat invalid number as None (empty)
            print(f"❌ 오류: CHAT_ID '{chat_id_str}'는 정수여야 합니다. 비워둡니다.")
            _show_messagebox_error_main_thread("설정 오류", f"CHAT_ID '{chat_id_str}'는 정수여야 합니다.\n값을 비웁니다.")

        # Use getint/getboolean with fallback to defaults
        CAPTURE_INTERVAL_MINUTES = config.getint(settings_section, CAPTURE_INTERVAL_KEY, fallback=int(defaults[CAPTURE_INTERVAL_KEY]))
        USE_SPECIFIC_AREA_CAPTURE = config.getboolean(settings_section, USE_SPECIFIC_AREA_KEY, fallback=defaults[USE_SPECIFIC_AREA_KEY]=='true')
        CAPTURE_COORDS['x1'] = config.getint(settings_section, CAPTURE_X1_KEY, fallback=int(defaults[CAPTURE_X1_KEY]))
        CAPTURE_COORDS['y1'] = config.getint(settings_section, CAPTURE_Y1_KEY, fallback=int(defaults[CAPTURE_Y1_KEY]))
        CAPTURE_COORDS['x2'] = config.getint(settings_section, CAPTURE_X2_KEY, fallback=int(defaults[CAPTURE_X2_KEY]))
        CAPTURE_COORDS['y2'] = config.getint(settings_section, CAPTURE_Y2_KEY, fallback=int(defaults[CAPTURE_Y2_KEY]))

        # Validate loaded coordinates
        if not (CAPTURE_COORDS['x1'] < CAPTURE_COORDS['x2'] and CAPTURE_COORDS['y1'] < CAPTURE_COORDS['y2']):
             print(f"⚠️ 로드된 특정 영역 좌표가 유효하지 않습니다: {CAPTURE_COORDS}. 기본값(0,0,100,100)으로 재설정합니다.")
             CAPTURE_COORDS = {'x1': 0, 'y1': 0, 'x2': 100, 'y2': 100} # Reset to a valid default

        print(f"설정 로드 완료. CHAT_ID: {CHAT_ID}, Interval: {CAPTURE_INTERVAL_MINUTES} min, UseArea: {USE_SPECIFIC_AREA_CAPTURE}, Coords: {CAPTURE_COORDS}")

        # Schedule GUI updates using lambda to capture current values
        if token_entry_main_app and token_entry_main_app.winfo_exists():
             schedule_gui_task(lambda w=token_entry_main_app, v=BOT_TOKEN: (w.delete(0, tk.END), w.insert(0, v or "")))
        if chat_id_entry_main_app and chat_id_entry_main_app.winfo_exists():
             schedule_gui_task(lambda w=chat_id_entry_main_app, v=CHAT_ID: (w.delete(0, tk.END), w.insert(0, str(v) if v is not None else "")))
        if interval_minutes_entry_main_app and interval_minutes_entry_main_app.winfo_exists():
             schedule_gui_task(lambda w=interval_minutes_entry_main_app, v=CAPTURE_INTERVAL_MINUTES: (w.delete(0, tk.END), w.insert(0, str(v))))
        if use_specific_area_var_main_app:
             schedule_gui_task(lambda var=use_specific_area_var_main_app, val=USE_SPECIFIC_AREA_CAPTURE: var.set(val))

        coord_entries_gui = [coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app]
        coord_keys_load = ['x1', 'y1', 'x2', 'y2']
        for i, entry_widget in enumerate(coord_entries_gui):
            if entry_widget and entry_widget.winfo_exists():
                 coord_val = CAPTURE_COORDS[coord_keys_load[i]]
                 schedule_gui_task(lambda w=entry_widget, v=coord_val: (w.delete(0, tk.END), w.insert(0, str(v))))

        # Crucially, call the toggle function *after* setting the checkbox variable and coord entries
        # This ensures the initial state (enabled/disabled) of entries and the select button is correct.
        schedule_gui_task(on_specific_area_toggle_changed)

    except (configparser.Error, ValueError, TypeError) as e:
        print(f"❌ 설정 파일 처리 중 치명적 오류: {e}")
        _show_messagebox_error_main_thread("설정 로드 오류", f"설정 파일 처리 실패: {e}\n프로그램 기본값을 사용합니다.")
        # Reset to hardcoded defaults on critical error
        BOT_TOKEN = ''
        CHAT_ID = None
        CAPTURE_INTERVAL_MINUTES = 30
        USE_SPECIFIC_AREA_CAPTURE = False
        CAPTURE_COORDS = {'x1': 0, 'y1': 0, 'x2': 100, 'y2': 100}
        # Attempt to update GUI with these hardcoded defaults too
        if token_entry_main_app and token_entry_main_app.winfo_exists(): schedule_gui_task(lambda w=token_entry_main_app: (w.delete(0, tk.END), w.insert(0, '')))
        if chat_id_entry_main_app and chat_id_entry_main_app.winfo_exists(): schedule_gui_task(lambda w=chat_id_entry_main_app: (w.delete(0, tk.END), w.insert(0, '')))
        if interval_minutes_entry_main_app and interval_minutes_entry_main_app.winfo_exists(): schedule_gui_task(lambda w=interval_minutes_entry_main_app: (w.delete(0, tk.END), w.insert(0, '30')))
        if use_specific_area_var_main_app: schedule_gui_task(lambda var=use_specific_area_var_main_app: var.set(False))
        coord_entries_gui = [coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app];
        coord_defaults = [0, 0, 100, 100]
        for i, entry_widget in enumerate(coord_entries_gui):
             if entry_widget and entry_widget.winfo_exists(): schedule_gui_task(lambda w=entry_widget, v=coord_defaults[i]: (w.delete(0, tk.END), w.insert(0, str(v))))
        schedule_gui_task(on_specific_area_toggle_changed) # Update state based on default USE_SPECIFIC_AREA_CAPTURE


def on_save_settings_gui_main_app():
    global BOT_TOKEN, CHAT_ID, CAPTURE_INTERVAL_MINUTES, USE_SPECIFIC_AREA_CAPTURE, CAPTURE_COORDS

    # Ensure global vars reflect current GUI state before saving
    _update_global_interval_from_gui() # Reads interval entry, updates global CAPTURE_INTERVAL_MINUTES
    _update_global_coords_from_gui() # Reads coord entries, updates global CAPTURE_COORDS

    gui_bot_token = token_entry_main_app.get().strip()
    gui_chat_id_str = chat_id_entry_main_app.get().strip()

    # Validate required fields
    if not gui_bot_token:
        _show_messagebox_showwarning_main_thread("입력 오류", "BOT_TOKEN을 입력해주세요.")
        return
    if not gui_chat_id_str:
        _show_messagebox_showwarning_main_thread("입력 오류", "CHAT_ID를 입력해주세요.")
        return

    try:
        gui_chat_id_int = int(gui_chat_id_str)
    except ValueError:
        _show_messagebox_showwarning_main_thread("입력 오류", "CHAT_ID는 숫자여야 합니다.")
        return

    # Interval validation already done by _update_global_interval_from_gui, but double-check
    if CAPTURE_INTERVAL_MINUTES <= 0:
        _show_messagebox_showwarning_main_thread("입력 오류", "전송 간격은 0보다 큰 숫자여야 합니다.")
        return

    # Coordinate validation already done by _update_global_coords_from_gui, but double-check
    if USE_SPECIFIC_AREA_CAPTURE:
        if not (CAPTURE_COORDS['x1'] < CAPTURE_COORDS['x2'] and CAPTURE_COORDS['y1'] < CAPTURE_COORDS['y2']):
            _show_messagebox_showwarning_main_thread("좌표 오류", "특정 영역 좌표가 유효하지 않습니다 (X1 < X2, Y1 < Y2).\n좌표를 수정하거나 '특정영역 사용'을 해제하세요.")
            return

    # Update global variables that might not have been updated by FocusOut events
    BOT_TOKEN = gui_bot_token
    CHAT_ID = gui_chat_id_int
    # USE_SPECIFIC_AREA_CAPTURE is updated by checkbox toggle
    # CAPTURE_INTERVAL_MINUTES and CAPTURE_COORDS updated by _update funcs

    # Proceed to save validated and updated global values to file
    config = configparser.ConfigParser()
    if os.path.exists(SETTINGS_FILE):
        try:
            config.read(SETTINGS_FILE, encoding='utf-8')
        except configparser.Error as e:
             print(f"경고: 설정 파일 읽기 실패 ({e}). 새 파일처럼 저장합니다.")
             config = configparser.ConfigParser() # Reset if read failed

    if 'Settings' not in config: config.add_section('Settings')

    config['Settings']['BOT_TOKEN'] = BOT_TOKEN
    config['Settings']['CHAT_ID'] = str(CHAT_ID)
    config['Settings'][CAPTURE_INTERVAL_KEY] = str(CAPTURE_INTERVAL_MINUTES)
    config['Settings'][USE_SPECIFIC_AREA_KEY] = 'true' if USE_SPECIFIC_AREA_CAPTURE else 'false'
    config['Settings'][CAPTURE_X1_KEY] = str(CAPTURE_COORDS['x1'])
    config['Settings'][CAPTURE_Y1_KEY] = str(CAPTURE_COORDS['y1'])
    config['Settings'][CAPTURE_X2_KEY] = str(CAPTURE_COORDS['x2'])
    config['Settings'][CAPTURE_Y2_KEY] = str(CAPTURE_COORDS['y2'])

    if save_settings_to_file_main_app(config, SETTINGS_FILE):
        _show_messagebox_showinfo_main_thread("성공",
                          "설정이 파일에 저장되었습니다!\n봇 재시작 시 일부 변경사항(토큰, ID 등)이 적용됩니다.")
        print("✅ 전역 설정 값 업데이트 및 파일 저장 완료.")
    else:
        # Error message shown by save_settings_to_file_main_app
        pass

# --- 텔레그램 봇 관련 함수 ---
async def handle_text_message_main_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텔레그램 텍스트 메시지('plz', 'start', 'stop')를 처리합니다."""
    global PERIODIC_CAPTURE_ACTIVE, CHAT_ID

    # Ignore messages if chat_id is not set or doesn't match
    if CHAT_ID is None or not update.message or update.message.chat_id != CHAT_ID or not update.message.text:
        if update.message: # Log ignored messages from other chats if needed
             # print(f"Ignoring message from chat_id {update.message.chat_id} (expected {CHAT_ID})")
             pass
        return

    received_text = update.message.text.lower().strip()
    sender_info = update.effective_user.username or update.effective_user.first_name

    print(f"💬 ({sender_info}) 메시지 수신: '{received_text}'")

    if received_text == 'plz':
        print(f"⚡️ 'plz' 명령 수신. 실시간 화면 캡처 요청.")
        # Create a job-like context manually for the capture function
        # Pass None for job as it's not a scheduled job
        manual_context = ContextTypes.DEFAULT_TYPE(application=context.application, chat_id=CHAT_ID, user_id=update.effective_user.id)
        manual_context._job = None # Explicitly set job to None
        await capture_and_send_for_bot_main_app(manual_context)

    elif received_text == 'stop':
        if PERIODIC_CAPTURE_ACTIVE:
            PERIODIC_CAPTURE_ACTIVE = False
            print(f"🛑 'stop' 명령 수신. 자동 캡처를 비활성화합니다.")
            feedback_message = "✅ 자동 화면 캡처 전송을 중지합니다. (봇은 계속 실행됩니다)"
        else:
            print(f"ℹ️ 'stop' 명령 수신. 자동 캡처는 이미 비활성화 상태입니다.")
            feedback_message = "ℹ️ 자동 화면 캡처는 이미 중지된 상태입니다."
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text=feedback_message)
        except Exception as e:
            print(f"❌ 'stop' 확인 메시지 전송 실패: {e}")

    elif received_text == 'start':
        if not PERIODIC_CAPTURE_ACTIVE:
            PERIODIC_CAPTURE_ACTIVE = True
            print(f"'start' 명령 수신. 자동 캡처를 활성화합니다.")
            interval_msg = f"{CAPTURE_INTERVAL_MINUTES}분 간격"
            feedback_message = f"자동 화면 캡처 전송을 시작합니다 ({interval_msg}). 다음 정기 전송부터 적용됩니다."
        else:
            print(f"'start' 명령 수신. 자동 캡처는 이미 활성화 상태입니다.")
            feedback_message = f"ℹ️ 자동 화면 캡처는 이미 실행 중입니다 ({CAPTURE_INTERVAL_MINUTES}분 간격)."
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text=feedback_message)
        except Exception as e:
            print(f"❌ 'start' 확인 메시지 전송 실패: {e}")

    # Other text messages are ignored by this handler


async def capture_and_send_for_bot_main_app(context: ContextTypes.DEFAULT_TYPE):
    """주기적으로 또는 'plz' 요청 시 화면을 캡처하고 텔레그램으로 전송합니다."""
    global PERIODIC_CAPTURE_ACTIVE, CHAT_ID, USE_SPECIFIC_AREA_CAPTURE, CAPTURE_COORDS

    # Use context.chat_id if available (for manual calls), otherwise use global CHAT_ID
    current_chat_id = getattr(context, 'chat_id', CHAT_ID)
    if current_chat_id is None:
        print("❌ 캡처 오류 (봇): CHAT_ID가 설정되지 않았습니다.")
        return

    # Determine if this is a periodic job run or a manual trigger
    is_periodic_job = context.job and context.job.name == 'periodic_capture'
    job_name_display = "주기적" if is_periodic_job else "수동(plz)"

    # For periodic jobs, check the active flag
    if is_periodic_job and not PERIODIC_CAPTURE_ACTIVE:
        current_time_str = datetime.now().strftime('%H:%M:%S')
        print(f"[{current_time_str}] 😴 자동 캡처가 'stop' 상태입니다. 이번 실행({job_name_display})을 건너뜁니다.")
        return

    # --- Proceed with capture ---
    print(f"({job_name_display}) 캡처 및 전송 시작 -> CHAT_ID: {current_chat_id}")
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f'bot_screenshot_{timestamp}.png'
    bbox_to_use = None
    capture_mode = "전체 화면" # Default capture mode description

    if USE_SPECIFIC_AREA_CAPTURE:
        # Read directly from global CAPTURE_COORDS (updated by GUI interactions)
        x1, y1 = CAPTURE_COORDS.get('x1', 0), CAPTURE_COORDS.get('y1', 0)
        x2, y2 = CAPTURE_COORDS.get('x2', 0), CAPTURE_COORDS.get('y2', 0)

        if x1 < x2 and y1 < y2:
            bbox_to_use = (x1, y1, x2, y2)
            capture_mode = f"특정 영역 {bbox_to_use}"
            print(f"ℹ️ {capture_mode} 캡처 시도.")
        else:
            print(f"⚠️ 저장된 특정 영역 좌표가 유효하지 않음 (x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}). 전체 화면을 캡처합니다.")
            # Keep bbox_to_use = None

    screenshot_success = False
    error_message = None
    try:
        screenshot = ImageGrab.grab(bbox=bbox_to_use, all_screens=True) # Try all_screens=True
        screenshot.save(filename)
        screenshot_success = True
        print(f"{capture_mode} 캡처 성공: '{filename}'")
    except Exception as e:
        error_message = f"캡처 중 오류 ({capture_mode}): {e}"
        print(f"❌ {error_message}")
        # If specific area failed, try full screen as fallback ONCE
        if bbox_to_use is not None:
            print("ℹ️ 특정 영역 캡처 실패. 전체 화면으로 재시도합니다.")
            bbox_to_use = None # Reset to full screen
            capture_mode = "전체 화면 (재시도)"
            try:
                screenshot = ImageGrab.grab(bbox=bbox_to_use, all_screens=True)
                screenshot.save(filename)
                screenshot_success = True
                print(f"{capture_mode} 캡처 성공: '{filename}'")
            except Exception as e_fallback:
                 error_message = f"전체 화면 재캡처 중 오류: {e_fallback}"
                 print(f"❌ {error_message}")
        # If full screen (initial or fallback) failed, screenshot_success remains False

    # Send if screenshot was successful
    if screenshot_success:
        try:
            caption = f"실시간 화면 ({capture_mode}) - {now.strftime('%Y-%m-%d %H:%M:%S')}"
            with open(filename, 'rb') as f:
                # Use context.bot which should be available
                await context.bot.send_photo(chat_id=current_chat_id, photo=f, caption=caption)
            print(f"({job_name_display}) 그룹({current_chat_id}) 전송 완료")
        except telegram.error.TelegramError as e:
            error_message = f"Telegram 전송 오류: {e}"
            print(f"❌ ({job_name_display}) 그룹({current_chat_id}) 전송 실패: {e}")
        except AttributeError:
             error_message = "Telegram 전송 오류: context.bot 사용 불가"
             print(f"❌ ({job_name_display}) 그룹({current_chat_id}) 전송 실패: {error_message}")
        except Exception as e:
            error_message = f"전송 중 알 수 없는 오류: {e}"
            print(f"❌ ({job_name_display}) 그룹({current_chat_id}) 전송 중 일반 오류: {e}")

    # Send error message to chat if any error occurred during capture or send
    if error_message:
         try:
              # Use context.bot if available
              if hasattr(context, 'bot'):
                   await context.bot.send_message(chat_id=current_chat_id, text=f"⚠️ 캡처/전송 오류 발생:\n{error_message}")
              else:
                   print(f"❌ 오류 메시지 전송 불가 (context.bot 없음): {error_message}")
         except Exception as e_report:
              print(f"❌ 오류 보고 메시지 전송 실패: {e_report}")

    # Cleanup the temporary file
    if os.path.exists(filename):
        try:
            os.remove(filename)
        except Exception as e_del:
            print(f"❌ 임시 파일 삭제 오류 ('{filename}'): {e_del}")


def run_telegram_bot_polling_main_app():
    global BOT_TOKEN, CHAT_ID, TELEGRAM_BOT_APPLICATION, BOT_EVENT_LOOP, CAPTURE_INTERVAL_MINUTES
    global start_bot_button_main_app, stop_bot_button_main_app # GUI elements

    # Use copies for this thread instance
    current_thread_token = BOT_TOKEN
    current_thread_chat_id = CHAT_ID
    current_interval_minutes = CAPTURE_INTERVAL_MINUTES

    # Validate inputs before starting
    if not current_thread_token:
        print("❌ 봇 시작 불가: BOT_TOKEN이 설정되지 않았습니다.")
        schedule_gui_task(_show_messagebox_error_main_thread, "시작 오류", "BOT_TOKEN을 설정하고 저장한 후 시작해주세요.")
        # Ensure GUI state reflects stopped status
        schedule_gui_task(_update_button_state_main_app, start_bot_button_main_app, tk.NORMAL)
        schedule_gui_task(_update_button_state_main_app, stop_bot_button_main_app, tk.DISABLED)
        schedule_gui_task(_update_bot_status_label_main_app, False)
        return

    if current_thread_chat_id is None:
        print("❌ 봇 시작 불가: CHAT_ID가 설정되지 않았습니다.")
        schedule_gui_task(_show_messagebox_error_main_thread, "시작 오류", "CHAT_ID를 설정하고 저장한 후 시작해주세요.")
        schedule_gui_task(_update_button_state_main_app, start_bot_button_main_app, tk.NORMAL)
        schedule_gui_task(_update_button_state_main_app, stop_bot_button_main_app, tk.DISABLED)
        schedule_gui_task(_update_bot_status_label_main_app, False)
        return

    actual_interval_seconds = current_interval_minutes * 60
    if actual_interval_seconds <= 0:
        print(f"⚠️ 잘못된 전송 간격 ({current_interval_minutes}분), 최소 1분(60초)으로 설정합니다.")
        actual_interval_seconds = 60 # Minimum interval 1 minute

    #print(f"⏳ Telegram Bot 스레드 시작 중... (Token: {current_thread_token[:10]}..., CHAT_ID: {current_thread_chat_id}, Interval: {actual_interval_seconds / 60:.1f} 분)")

    # Setup event loop for this thread
    BOT_EVENT_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(BOT_EVENT_LOOP)

    try:
        # Build Application
        app_builder = BotApplication.builder().token(current_thread_token)
        TELEGRAM_BOT_APPLICATION = app_builder.build()

        # Add message handler for 'plz', 'start', 'stop'
        text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message_main_app)
        TELEGRAM_BOT_APPLICATION.add_handler(text_handler)

        # Schedule periodic capture job
        first_run_delay = 15
        TELEGRAM_BOT_APPLICATION.job_queue.run_repeating(
            capture_and_send_for_bot_main_app,
            interval=actual_interval_seconds,
            first=first_run_delay,
            name='periodic_capture',
            chat_id=current_thread_chat_id, # Pass chat_id to job context
            user_id=None # No specific user for periodic job
        )
        print(f"주기적 캡처 작업 등록됨 (간격: {actual_interval_seconds}초, 첫 실행: {first_run_delay}초 후)")

        # Update GUI to show running state
        schedule_gui_task(_update_button_state_main_app, start_bot_button_main_app, tk.DISABLED)
        schedule_gui_task(_update_button_state_main_app, stop_bot_button_main_app, tk.NORMAL)
        schedule_gui_task(_update_bot_status_label_main_app, True)
        #print("봇 폴링 시작...")

        # Start polling (blocking until stopped)
        TELEGRAM_BOT_APPLICATION.run_polling(allowed_updates=[Update.MESSAGE], stop_signals=None) # Use None for default signals + shutdown()

        #print("🛑 봇 폴링이 정상적으로 중지되었습니다.")

    except telegram.error.InvalidToken:
        msg = f"BOT_TOKEN '{current_thread_token[:10]}...'이(가) 유효하지 않습니다. 설정을 확인하세요."
        print(f"❌ 치명적 오류: {msg}")
        schedule_gui_task(_show_messagebox_error_main_thread, "봇 토큰 오류", msg)
    except telegram.error.NetworkError as e:
         msg = f"네트워크 오류로 봇 연결 실패: {e}\n인터넷 연결을 확인하고 다시 시도하세요."
         print(f"❌ {msg}")
         schedule_gui_task(_show_messagebox_error_main_thread, "네트워크 오류", msg)
    except Exception as e:
        # Catch potential JobQueue errors during setup as well
        err_msg = f"텔레그램 봇 실행 중 예외 발생: {e}"
        print(f"❌ {err_msg}")
        print(traceback.format_exc())
        schedule_gui_task(_show_messagebox_error_main_thread, "봇 실행 오류", err_msg)
    finally:
        #print("🧹 봇 스레드 정리 작업 시작...")
        # Clean up Application and event loop resources
        app = TELEGRAM_BOT_APPLICATION # Local ref for safety
        if app:
             if app.job_queue:
                 try:
                     print("   - JobQueue 중지 시도...")
                     app.job_queue.stop()
                     print("   - JobQueue 중지 완료.")
                 except Exception as e_jq:
                      print(f"⚠️ JobQueue 중지 중 오류: {e_jq}")

        TELEGRAM_BOT_APPLICATION = None # Clear global reference

        loop = BOT_EVENT_LOOP # Local ref for safety
        if loop:
            if loop.is_running():
                 print("⚠️ 이벤트 루프가 여전히 실행 중입니다. 강제 종료 시도.")
                 try: loop.stop() # Attempt to stop loop
                 except Exception as e_stop: print(f"❌ 이벤트 루프 중지 오류: {e_stop}")
            if not loop.is_closed():
                 try:
                      print("   - 이벤트 루프 종료 전 남은 작업 확인...")
                      pending = asyncio.all_tasks(loop=loop)
                      if pending:
                           print(f"   - 이벤트 루프 종료 전 {len(pending)}개 작업 대기 시도...")
                           loop.run_until_complete(asyncio.sleep(0.1, loop=loop))
                      else:
                           print("   - 남은 작업 없음.")
                      print("   - 이벤트 루프 닫는 중...")
                      loop.close()
                      print("✅ 이벤트 루프 닫힘.")
                 except Exception as e_close:
                      print(f"❌ 이벤트 루프 닫기 오류: {e_close}")
            else:
                 print("   - 이벤트 루프가 이미 닫혀있습니다.")

        BOT_EVENT_LOOP = None # Clear global reference
        #print("ℹ️ 봇 관련 리소스 정리 완료.")

        # Update GUI to reflect stopped state *reliably* in the finally block
        schedule_gui_task(_update_button_state_main_app, start_bot_button_main_app, tk.NORMAL)
        schedule_gui_task(_update_button_state_main_app, stop_bot_button_main_app, tk.DISABLED)
        schedule_gui_task(_update_bot_status_label_main_app, False)


async def async_gui_capture_and_send_main_app(bot_instance: Bot, target_chat_id: int):
    """GUI의 테스트 버튼 클릭 시 화면을 캡처하고 임시 봇 인스턴스로 전송"""
    global USE_SPECIFIC_AREA_CAPTURE, CAPTURE_COORDS # Use global settings

    print("테스트 캡처 및 전송 시작...")
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f'gui_screenshot_{timestamp}.png'
    bbox_to_use = None
    capture_mode = "전체 화면"

    if USE_SPECIFIC_AREA_CAPTURE:
        x1, y1 = CAPTURE_COORDS.get('x1', 0), CAPTURE_COORDS.get('y1', 0)
        x2, y2 = CAPTURE_COORDS.get('x2', 0), CAPTURE_COORDS.get('y2', 0)
        if x1 < x2 and y1 < y2:
            bbox_to_use = (x1, y1, x2, y2)
            capture_mode = f"특정 영역 {bbox_to_use}"
            print(f"ℹ️ GUI 테스트: {capture_mode} 캡처 시도.")
        else:
            print(f"⚠️ GUI 테스트: 저장된 특정 영역 좌표 유효하지 않음. 전체 화면 캡처.")

    screenshot_success = False
    error_message = None
    try:
        screenshot = ImageGrab.grab(bbox=bbox_to_use, all_screens=True)
        screenshot.save(filename)
        screenshot_success = True
        #print(f"✅ GUI 테스트: {capture_mode} 캡처 성공: '{filename}'")
    except Exception as e:
        error_message = f"GUI 테스트 캡처 오류 ({capture_mode}): {e}"
        print(f"❌ {error_message}")

        if bbox_to_use is not None:
             print(" 테스트: 특정 영역 실패, 전체 화면 재시도.")
             bbox_to_use = None; capture_mode = "전체 화면 (재시도)"
             try:
                  screenshot = ImageGrab.grab(bbox=bbox_to_use, all_screens=True); screenshot.save(filename); screenshot_success = True
                  print(f"테스트: {capture_mode} 캡처 성공")
             except Exception as e_fb: error_message = f"GUI 테스트 전체 화면 재캡처 오류: {e_fb}"; print(f"❌ {error_message}")

    # Send if successful
    if screenshot_success:
        try:
            caption = f"테스트 화면 캡처 ({capture_mode}) - {now.strftime('%Y-%m-%d %H:%M:%S')}"
            print(f"테스트: '{filename}' 채팅방({target_chat_id})으로 전송 중...")
            with open(filename, 'rb') as f:
                await bot_instance.send_photo(chat_id=target_chat_id, photo=f, caption=caption)
            print(f"테스트: 전송 완료!")
            _show_messagebox_showinfo_main_thread("전송 성공", "테스트 화면 캡처를 성공적으로 전송했습니다.")
        except telegram.error.TelegramError as e:
            error_message = f"GUI 테스트 전송 오류: {e}"
            print(f"❌ {error_message}")
        except Exception as e:
             error_message = f"GUI 테스트 전송 중 알 수 없는 오류: {e}"
             print(f"❌ {error_message}")

    # Show error in GUI if any occurred (using delayed helper)
    if error_message:
        _show_messagebox_error_main_thread("전송 오류", error_message)

    # Cleanup
    if os.path.exists(filename):
        try: os.remove(filename)
        except Exception as e_del: print(f"❌ 임시 파일 삭제 오류 (GUI 테스트): {e_del}")


def run_async_task_in_new_thread_main_app(coroutine_func, *args):
    """지정된 비동기 코루틴을 새 스레드의 이벤트 루프에서 실행"""
    async def coro_wrapper():
        return await coroutine_func(*args)

    def thread_target():
        # Each thread needs its own event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro_wrapper())
        except Exception as e:
            # Log error, potentially show in GUI if critical
            print(f"❌ 비동기 작업(새 스레드) '{getattr(coroutine_func, '__name__', 'coro')}' 실행 중 오류: {e}")
            if "send_photo" in str(e).lower(): # Rough check if it's likely a send error
                 _show_messagebox_error_main_thread("비동기 작업 오류", f"작업 '{getattr(coroutine_func, '__name__', 'coro')}' 중 오류:\n{e}")
        finally:
            print(f"   - 비동기 작업 스레드 '{getattr(coroutine_func, '__name__', 'coro')}' 루프 정리...")
            if not loop.is_closed():
                try:
                     # Give loop a chance to finish tasks before closing
                     loop.run_until_complete(loop.shutdown_asyncgens())
                     loop.close()
                     print(f"   - 이벤트 루프 '{getattr(coroutine_func, '__name__', 'coro')}' 종료 완료.")
                except Exception as e_close:
                     print(f"❌ 이벤트 루프 '{getattr(coroutine_func, '__name__', 'coro')}' 종료 중 오류: {e_close}")

    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()
    return thread


def on_send_screenshot_gui_main_app():
    """GUI의 '화면 캡처 테스트' 버튼 클릭 시 실행"""
    global token_entry_main_app, chat_id_entry_main_app, TELEGRAM_BOT_APPLICATION

    if not token_entry_main_app or not chat_id_entry_main_app: return
    gui_bot_token = token_entry_main_app.get().strip()
    gui_chat_id_str = chat_id_entry_main_app.get().strip()

    if not gui_bot_token:
        _show_messagebox_showwarning_main_thread("설정 필요", "유효한 BOT_TOKEN을 먼저 입력하고 저장해주세요.")
        return
    if not gui_chat_id_str:
        _show_messagebox_showwarning_main_thread("설정 필요", "CHAT_ID를 입력해주세요.")
        return
    try:
        target_chat_id = int(gui_chat_id_str)
    except ValueError:
        _show_messagebox_showwarning_main_thread("입력 오류", "CHAT_ID는 유효한 숫자여야 합니다.")
        return

    print("'화면 전송 테스트' 버튼 클릭됨. 전송 시도...")

    # Determine which bot instance to use
    bot_to_use: Bot | None = None
    try:
        # Prefer using the running application's bot instance if available
        if TELEGRAM_BOT_APPLICATION and TELEGRAM_BOT_APPLICATION.bot:
            #print("ℹ️ 실행 중인 봇의 연결(Application.bot)을 사용하여 테스트 전송합니다.")
            bot_to_use = TELEGRAM_BOT_APPLICATION.bot
        else:
            # Create a temporary Bot instance for the test
            #print("⚠️ 실행 중인 봇 없음. 임시 Bot 인스턴스 생성하여 테스트 전송 시도.")
            bot_to_use = Bot(token=gui_bot_token)
            #print("✅ 임시 Bot 인스턴스 생성 완료.")

    except telegram.error.InvalidToken:
         print(f"❌ 임시 봇 인스턴스 생성 실패: 토큰 '{gui_bot_token[:10]}...'이 유효하지 않습니다.")
         _show_messagebox_error_main_thread("토큰 오류", "입력된 BOT_TOKEN이 유효하지 않아 테스트 전송을 할 수 없습니다.")
         return
    except Exception as e:
        print(f"❌ Bot 인스턴스 준비 중 오류: {e}")
        _show_messagebox_error_main_thread("오류", f"Bot 준비 중 오류 발생:\n{e}")
        return

    # If we have a bot instance (running or temporary), run the async send task
    if bot_to_use:
        run_async_task_in_new_thread_main_app(async_gui_capture_and_send_main_app, bot_to_use, target_chat_id)
        #print("✅ GUI 캡처/전송 작업 스레드 시작 요청 완료.")


def start_bot_from_gui_main_app():
    global BOT_THREAD

    # Prevent starting multiple times
    if BOT_THREAD and BOT_THREAD.is_alive():
        print("ℹ️ 봇이 이미 실행 중입니다.")
        _show_messagebox_showinfo_main_thread("알림", "봇이 이미 실행 중입니다.")
        return

    # Perform quick checks before starting thread
    current_token = token_entry_main_app.get().strip() if token_entry_main_app else None
    current_chat_id_str = chat_id_entry_main_app.get().strip() if chat_id_entry_main_app else None

    if not current_token:
         _show_messagebox_showwarning_main_thread("시작 불가", "BOT_TOKEN을 입력하고 저장해주세요.")
         return
    if not current_chat_id_str:
         _show_messagebox_showwarning_main_thread("시작 불가", "CHAT_ID를 입력하고 저장해주세요.")
         return
    try:
        int(current_chat_id_str) # Just check if it's a valid int
    except ValueError:
         _show_messagebox_showwarning_main_thread("시작 불가", "CHAT_ID는 숫자여야 합니다.")
         return

    #print("▶️ GUI에서 Telegram Bot 스레드 시작 명령 수신...")
    # Update global vars just before starting (in case they weren't saved recently)
    global BOT_TOKEN, CHAT_ID
    BOT_TOKEN = current_token
    try: CHAT_ID = int(current_chat_id_str)
    except ValueError: # Should have been caught, but safety check
         _show_messagebox_error_main_thread("오류", "CHAT_ID 변환 중 오류 발생.")
         return

    _update_global_interval_from_gui() # Ensure interval is up-to-date
    _update_global_coords_from_gui() # Ensure coords are up-to-date

    # Check coord validity again if using specific area
    if USE_SPECIFIC_AREA_CAPTURE:
         if not (CAPTURE_COORDS['x1'] < CAPTURE_COORDS['x2'] and CAPTURE_COORDS['y1'] < CAPTURE_COORDS['y2']):
              _show_messagebox_showwarning_main_thread("시작 불가", "특정 영역 사용이 체크되었으나 좌표가 유효하지 않습니다.")
              return

    # Start the bot in a separate thread
    BOT_THREAD = threading.Thread(target=run_telegram_bot_polling_main_app, daemon=True)
    BOT_THREAD.start()
    # GUI updates (disabling start, enabling stop) are handled within run_telegram_bot_polling_main_app


async def _shutdown_application_coro_main_app():
    """Coroutine to gracefully shut down the Telegram Bot Application."""
    app = TELEGRAM_BOT_APPLICATION # Use local ref
    if app:
        print("Application 종료 코루틴 시작...")
        try:
            # Stop job queue first
            if app.job_queue:
                print("   - Job Queue 중지 시도...")
                await asyncio.to_thread(app.job_queue.stop) # Run sync stop in thread
                print("   - Job Queue 중지 완료.")

            # Shutdown application
            if app.running:
                 print("   - Application.shutdown() 호출...")
                 await app.shutdown()
                 print("   - Application.shutdown() 완료.")
            else:
                 print("   - Application이 실행 중이지 않아 shutdown() 생략.")

        except Exception as e:
            print(f"Application 종료 코루틴 중 오류: {e}")
        finally:
             print("Application 종료 코루틴 완료.")
    else:
        print("Application 인스턴스가 이미 None (종료 코루틴).")


def stop_bot_from_gui_main_app():
    global TELEGRAM_BOT_APPLICATION, BOT_THREAD, BOT_EVENT_LOOP
    global start_bot_button_main_app, stop_bot_button_main_app # GUI elements

    # Check if bot is actually running (check thread and application object)
    bot_is_likely_running = (BOT_THREAD and BOT_THREAD.is_alive()) or (TELEGRAM_BOT_APPLICATION is not None)

    if not bot_is_likely_running:
        print("봇이 실행 중이지 않거나 이미 중지되었습니다.")
        _show_messagebox_showinfo_main_thread("알림", "봇이 실행 중이지 않거나 이미 중지되었습니다.")
        # Ensure GUI state is consistent
        schedule_gui_task(_update_button_state_main_app, start_bot_button_main_app, tk.NORMAL)
        schedule_gui_task(_update_button_state_main_app, stop_bot_button_main_app, tk.DISABLED)
        schedule_gui_task(_update_bot_status_label_main_app, False)
        return

    #print("🛑 GUI에서 Telegram Bot 종료 명령 수신...")
    # Disable stop button immediately to prevent multiple clicks
    schedule_gui_task(_update_button_state_main_app, stop_bot_button_main_app, tk.DISABLED)
    schedule_gui_task(_update_bot_status_label_main_app, False) # Tentatively set status to stopped

    shutdown_successful = False
    if TELEGRAM_BOT_APPLICATION and BOT_EVENT_LOOP and BOT_EVENT_LOOP.is_running():
        print(f"실행 중인 봇의 이벤트 루프({BOT_EVENT_LOOP})에 종료 작업 제출...")
        future = asyncio.run_coroutine_threadsafe(_shutdown_application_coro_main_app(), BOT_EVENT_LOOP)
        try:
            future.result(timeout=10) # Wait up to 10 seconds
            print("종료 작업(coroutine) 결과 수신 완료.")
            shutdown_successful = True
        except asyncio.TimeoutError:
            print("종료 작업 결과 대기 중 타임아웃 (10초). 루프가 멈췄을 수 있습니다.")
            if BOT_EVENT_LOOP and BOT_EVENT_LOOP.is_running(): BOT_EVENT_LOOP.stop()
        except Exception as e_res:
            print(f"❌ 종료 작업 결과 수신 중 오류: {e_res}")
            if BOT_EVENT_LOOP and BOT_EVENT_LOOP.is_running(): BOT_EVENT_LOOP.stop()

    elif TELEGRAM_BOT_APPLICATION:
        print("⚠️ 봇 이벤트 루프 정보가 없거나 실행 중이지 않음. 새 스레드에서 종료 시도...")
        run_async_task_in_new_thread_main_app(_shutdown_application_coro_main_app)
        shutdown_successful = True # Assume initiated
    else:
        print("Application 객체가 없어 shutdown 호출 불가 (이미 종료됨).")
        shutdown_successful = True # Considered stopped

    # Wait briefly for the bot thread itself to exit after shutdown signal
    if BOT_THREAD and BOT_THREAD.is_alive():
         print("봇 스레드 종료 대기중...")
         BOT_THREAD.join(timeout=2.0)
         if BOT_THREAD.is_alive():
              print("봇 스레드가 종료되지 않았습니다.")
         else:
              print("봇 스레드 정상 종료 확인.")
              BOT_THREAD = None # Clear thread reference only if joined successfully

    print("봇 종료 요청 처리 완료.")
    # Final GUI state update handled by the bot thread's finally block.

#채팅방 id 얻는 함수
def chat_id_checker_window():
    def get_chat_id():
        bot_token = token_entry.get().strip()
        if not bot_token:
            messagebox.showwarning("입력 오류", "봇 토큰을 입력하세요.", parent=window)
            return

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        try:
            response = requests.get(url)
            data = response.json()

            if not data.get("ok"):
                messagebox.showerror("에러", "❌ 유효하지 않은 토큰이거나 서버 오류입니다.", parent=window)
                return

            results = data.get("result", [])
            if not results:
                messagebox.showinfo("정보", "📭 아직 메시지를 받은 채팅이 없습니다.\n\n그룹에 메시지를 보내거나, 봇 권한을 확인하세요.", parent=window)
                return

            output.delete("1.0", tk.END)
            chat_ids = set()
            for update in results:
                message = update.get("message") or update.get("channel_post")
                if message:
                    chat = message.get("chat", {})
                    chat_title = chat.get("title") or chat.get("username") or chat.get("first_name", "알 수 없음")
                    chat_id = chat.get("id")
                    if chat_id not in chat_ids:
                        chat_type = chat.get("type", "")
                        output.insert(tk.END, f"✅ [{chat_type}] {chat_title} | Chat ID: {chat_id}\n")
                        chat_ids.add(chat_id)

        except Exception as e:
            messagebox.showerror("오류", f"⚠️ 예외 발생: {e}", parent=window)
    # 새 창 생성
    window = tk.Toplevel(_main_app_root_ref)
    window.title("🔍 텔레그램 Chat ID 확인기")
    window.geometry("500x300")

    tk.Label(window, text="🤖 텔레그램 봇 토큰:").pack(pady=5)
    token_entry = tk.Entry(window, width=50)
    token_entry.pack(pady=5)

    tk.Button(window, text="Chat ID 가져오기", command=get_chat_id).pack(pady=10)

    output = tk.Text(window, height=10)
    output.pack(padx=10, pady=10)


# --- 메인 GUI 설정 ---
def setup_main_bot_controller_gui(app_root, days_left_info):
    global token_entry_main_app, chat_id_entry_main_app, start_bot_button_main_app, stop_bot_button_main_app, log_text_widget_main_app, bot_status_label_main_app, _main_app_root_ref
    global interval_minutes_entry_main_app, use_specific_area_var_main_app, specific_area_checkbox_main_app
    global coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app, coords_entry_widgets_main_app
    global select_area_button_main_app # Ensure this is global
    _main_app_root_ref = app_root

    # Basic window setup
    remaining_days_text = f"{days_left_info}일" if days_left_info is not None else "정보 없음"
    app_root.title(f"Screen ReQuest Controller (남은 기간: {remaining_days_text})")
    app_root.geometry("850x750") # Increased height slightly for button/spacing
    app_root.minsize(700, 600) # Set minimum size

    # --- Settings Frame (Token, Chat ID, Interval, Save Button) ---
    settings_frame = tk.Frame(app_root, padx=10, pady=10)
    settings_frame.pack(fill=tk.X, padx=10, pady=(10, 5)) # Add top padding

    # Labels using grid
    tk.Label(settings_frame, text="BOT_TOKEN:").grid(row=0, column=0, sticky='w', padx=5, pady=2)
    tk.Label(settings_frame, text="CHAT_ID:").grid(row=1, column=0, sticky='w', padx=5, pady=2)
    tk.Label(settings_frame, text="자동 전송 간격 (분):").grid(row=2, column=0, sticky='w', padx=5, pady=2)

    # Entries using grid
    token_entry_main_app = tk.Entry(settings_frame, width=60)
    token_entry_main_app.grid(row=0, column=1, padx=5, pady=2, sticky='we')
    chat_id_entry_main_app = tk.Entry(settings_frame, width=60)
    chat_id_entry_main_app.grid(row=1, column=1, padx=5, pady=2, sticky='we')
    interval_minutes_entry_main_app = tk.Entry(settings_frame, width=10)
    interval_minutes_entry_main_app.grid(row=2, column=1, sticky='w', padx=5, pady=2)
    # Validate interval on FocusOut
    interval_minutes_entry_main_app.bind("<FocusOut>", _update_global_interval_from_gui)
    # Integer validation for interval entry
    vcmd_interval = (app_root.register(lambda P: P.isdigit() or P == ""), '%P')
    interval_minutes_entry_main_app.config(validate="key", validatecommand=vcmd_interval)

    # Save button using grid
    save_button_main_app = tk.Button(settings_frame, text="설정 저장", command=on_save_settings_gui_main_app, width=12, height=2)
    save_button_main_app.grid(row=0, column=2, rowspan=3, sticky='ns', padx=(15, 5), pady=5)

    # 채팅id얻기 버튼
    chat_id_tool_button = tk.Button(settings_frame, text="채팅방 ID 얻기", command=chat_id_checker_window, width=12,                                 height=2)
    chat_id_tool_button.grid(row=0, column=3, rowspan=3, sticky='ns', padx=(5, 0), pady=5)


    # Configure column weights for responsiveness
    settings_frame.columnconfigure(1, weight=1) # Allow entry column to expand

    # --- Specific Area Frame ---
    specific_area_frame = tk.LabelFrame(app_root, text="특정 영역 캡처 설정", padx=10, pady=10)
    specific_area_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

    # Checkbox
    use_specific_area_var_main_app = tk.BooleanVar()
    specific_area_checkbox_main_app = tk.Checkbutton(specific_area_frame, text="특정영역 캡처 사용", variable=use_specific_area_var_main_app, command=on_specific_area_toggle_changed)
    specific_area_checkbox_main_app.grid(row=0, column=0, columnspan=9, sticky='w', padx=5, pady=(0, 5)) # Span all columns

    # Coordinate Labels and Entries in a sub-frame for better alignment
    coord_entry_frame = tk.Frame(specific_area_frame)
    coord_entry_frame.grid(row=1, column=0, columnspan=8, sticky='w', pady=(0,5))

    coords_labels_texts = ["X1:", "Y1:", "X2:", "Y2:"]
    coords_gui_elements = []
    # Create integer validation command (reusable)
    vcmd_int = (app_root.register(lambda P: P.isdigit() or P == ""), '%P')

    for i, label_text in enumerate(coords_labels_texts):
        tk.Label(coord_entry_frame, text=label_text).pack(side=tk.LEFT, padx=(5 if i==0 else 15, 0)) # Label
        entry = tk.Entry(coord_entry_frame, width=7, validate="key", validatecommand=vcmd_int) # Integer only
        entry.pack(side=tk.LEFT, padx=(2, 0)) # Entry
        entry.bind("<FocusOut>", _update_global_coords_from_gui) # Update global on focus out
        coords_gui_elements.append(entry)

    # Assign global references
    coord_x1_entry_main_app, coord_y1_entry_main_app, coord_x2_entry_main_app, coord_y2_entry_main_app = coords_gui_elements
    coords_entry_widgets_main_app = coords_gui_elements # Keep list reference

    # Select Area Button
    select_area_button_main_app = tk.Button(specific_area_frame, text="영역 선택 (드래그)", command=open_area_selector, width=18)
    # Place it next to the coordinate entry frame
    select_area_button_main_app.grid(row=1, column=8, sticky='e', padx=(20, 5), pady=(0,5))

    # --- Bot Control Frame (Start/Stop Bot, Status) ---
    bot_control_frame = tk.Frame(app_root, padx=10, pady=5)
    bot_control_frame.pack(fill=tk.X, padx=10)

    start_bot_button_main_app = tk.Button(bot_control_frame, text="텔레그램 봇 시작", command=start_bot_from_gui_main_app, width=18, height=2, bg="#D0F0C0") # Light green
    start_bot_button_main_app.pack(side=tk.LEFT, padx=5)

    stop_bot_button_main_app = tk.Button(bot_control_frame, text="텔레그램 봇 중지", command=stop_bot_from_gui_main_app, state=tk.DISABLED, width=18, height=2, bg="#F0D0D0") # Light red
    stop_bot_button_main_app.pack(side=tk.LEFT, padx=5)

    bot_status_label_main_app = tk.Label(bot_control_frame, text="🔴 봇 대기 중", fg="red", font=("Arial", 11, "bold"))
    bot_status_label_main_app.pack(side=tk.LEFT, padx=15, pady=5, anchor='w')

    # --- Action Frame (Test Screenshot) ---
    action_frame = tk.Frame(app_root, padx=10, pady=5)
    action_frame.pack(fill=tk.X, padx=10)

    send_manual_button_main_app = tk.Button(action_frame, text="화면 캡처 테스트 전송", command=on_send_screenshot_gui_main_app, width=40, height=2) # Combined width approx
    send_manual_button_main_app.pack(side=tk.LEFT, padx=5, pady=5)

    # --- Log Frame ---
    log_frame = tk.LabelFrame(app_root, text="로그", padx=10, pady=10)
    log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    log_text_widget_main_app = scrolledtext.ScrolledText(log_frame, state='disabled', height=15, width=100, font=("Courier New", 13)) # Monospaced font, increased height
    log_text_widget_main_app.pack(fill=tk.BOTH, expand=True, pady=5)

    # Configure tags for log colors (optional) - TextRedirector needs modification to use these
    log_text_widget_main_app.tag_config("ERROR", foreground="red")
    log_text_widget_main_app.tag_config("WARNING", foreground="orange")
    log_text_widget_main_app.tag_config("INFO", foreground="blue")
    log_text_widget_main_app.tag_config("SUCCESS", foreground="green")
    log_text_widget_main_app.tag_config("DEBUG", foreground="grey")

    # --- Redirect stdout/stderr ---
    sys.stdout = TextRedirector(log_text_widget_main_app)
    sys.stderr = TextRedirector(log_text_widget_main_app)

    # --- Load settings and set initial GUI state ---
    print("================== 애플리케이션 시작 ==================")
    print(f"'{SETTINGS_FILE}'에서 설정 로드 중...")
    load_settings_globally_main_app() # Loads settings and updates GUI elements
    #print("초기 설정 로드 및 GUI 업데이트 완료.")

    # Set window close protocol
    app_root.protocol("WM_DELETE_WINDOW", lambda: on_gui_close_main_app_handler(app_root))


def on_gui_close_main_app_handler(app_root_to_close):
    print("🚪 메인 앱 창 닫기 요청됨...")
    # Optional: Ask for confirmation
    # if messagebox.askyesno("종료 확인", "프로그램을 종료하시겠습니까?\n(실행 중인 봇도 함께 중지됩니다)", parent=app_root_to_close):
    print("⏳ 실행 중인 봇 종료 시도...")
    stop_bot_from_gui_main_app() # Request bot stop (handles cases where it's not running too)

    # Allow some time for bot thread to potentially finish cleanup after stop request
    if BOT_THREAD and BOT_THREAD.is_alive():
         print("   - 봇 스레드 최종 종료 대기 (최대 1초)...")
         BOT_THREAD.join(timeout=1.0)
         if BOT_THREAD.is_alive():
              print("   - ⚠️ 봇 스레드가 시간 내에 종료되지 않았습니다.")
         else: BOT_THREAD = None

    print("ℹ️ 메인 애플리케이션 GUI 창 닫는 중...")
    if app_root_to_close and app_root_to_close.winfo_exists():
        app_root_to_close.destroy()
    print("✅ 메인 애플리케이션 GUI가 닫혔습니다.")
    # else:
    #      print("ℹ️ 종료 취소됨.")


# --- 메인 실행 ---
if __name__ == "__main__":
    main_app_root = tk.Tk()
    _main_app_root_ref = main_app_root # Store global reference immediately
    main_app_root.withdraw() # Hide main window initially

    # Success callback for LoginRegisterWindow
    def handle_login_success(days_left):
        print(f"✅ 로그인 성공! 남은 기간: {days_left}일. 메인 앱을 시작합니다.")
        # Setup and show the main application window
        try:
            setup_main_bot_controller_gui(main_app_root, days_left)
            if main_app_root and main_app_root.winfo_exists():
                 main_app_root.deiconify() # Show the main window
                 main_app_root.attributes('-topmost', True) # Bring to front briefly
                 main_app_root.after(100, lambda: main_app_root.attributes('-topmost', False)) # Then allow other windows on top
        except Exception as e:
             print(f"❌ 메인 GUI 설정 중 치명적 오류: {e}")
             print(traceback.format_exc())
             messagebox.showerror("실행 오류", f"메인 화면 구성 중 오류가 발생했습니다:\n{e}")
             if main_app_root and main_app_root.winfo_exists(): main_app_root.destroy()
             sys.exit(1) # Exit if main GUI fails


    # --- Start Login Process ---
    try:
        print("🔒 로그인 창 표시...")
        login_window = LoginRegisterWindow(main_app_root, handle_login_success)
        login_window.focus_force() # Ensure login window gets focus

        # --- Start Tkinter Main Event Loop ---
        print("▶️ Tkinter mainloop 시작...")
        main_app_root.mainloop()
        print("⏹️ Tkinter mainloop 종료됨.")

    except KeyboardInterrupt:
        print("\n⌨️ Ctrl+C 감지. 프로그램 강제 종료 중...")
        if main_app_root and main_app_root.winfo_exists():
             # Attempt graceful shutdown on Ctrl+C as well
             on_gui_close_main_app_handler(main_app_root)
    except Exception as e_main:
         print(f"💥 메인 실행 루프에서 예상치 못한 오류 발생: {e_main}")
         print(traceback.format_exc())
         # Log to a file maybe?
         if main_app_root and main_app_root.winfo_exists():
              main_app_root.destroy() # Try to close window on unexpected error
    finally:
        # Restore standard output/error streams
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        print("================== 애플리케이션 종료 ==================")
        # Ensure process exits cleanly
        sys.exit(0)