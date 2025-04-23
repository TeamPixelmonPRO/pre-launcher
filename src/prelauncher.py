import sys
import os
import subprocess
import zipfile
import requests
import threading
import hashlib
import json
import ctypes
import dearpygui.dearpygui as dpg
import shutil
import logging
import tempfile
import atexit
from time import sleep
from logging.handlers import RotatingFileHandler

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, relative_path)

# Конфигурация
CONFIG = {
    "app_title": "Pixelmon.PRO",
    "java": {
        "url": "https://cdn.azul.com/zulu/bin/zulu8.86.0.25-ca-fx-jre8.0.452-win_x64.zip",
        "sha256": "7e1e1f3bf894963fee9d1b4d48a94a9d8999768fa36e803ed8e80c6afe12d3bd",
        "version": "1.8.0_452",
        "install_path": r"C:\Program Files\Java\zulu8.86.0.25-ca-fx-jre8.0.452"
    },
    "max_retries": 3,
    "locale": "en",
    "debug": False
}

LAUNCHER_JAR = "PixelmonPRO.jar"
CONFIG['java']['install_path'] = os.path.join(
    os.getenv('PROGRAMFILES'), 
    'Java', 
    'zulu8.86.0.25-ca-fx-jre8.0.452'
)

class Locale:
    def __init__(self, lang='en'):
        self.strings = self.load_locale(lang)

    def load_locale(self, lang):
        default_strings = {
            "en": {
                "preparing": "Preparing...",
                "download_attempt": "Attempting to download {attempt}",
                "extracting": "Extracting files...",
                "downloading_java": "Downloading Java...",
                "installing_java": "Installing Java...",
                "extracting_launcher": "Extracting launcher...",
                "launching_launcher": "Launching launcher...",
                "cancel": "Cancel",
                "downloaded_mb": "Downloaded {current:.2f} MB of {total:.2f} MB",
                "installing_java_progress": "Unpacking Java in {path}..."
            },
            "ru": {
                "preparing": "Подготовка...",
                "download_attempt": "Попытка загрузки {attempt}",
                "extracting": "Распаковка файлов...",
                "downloading_java": "Скачивание Java...",
                "installing_java": "Установка Java...",
                "extracting_launcher": "Извлечение лаунчера...",
                "launching_launcher": "Запуск лаунчера...",
                "cancel": "Отмена",
                "downloaded_mb": "Скачано {current:.2f} МБ из {total:.2f} МБ",
                "installing_java_progress": "Распаковка Java в {path}..."
            }
        }
        
        try:
            with open(resource_path(f'lang/{lang}.json'), 'r', encoding='utf-8') as f:
                return {**default_strings.get(lang, {}), **json.load(f)}
        except Exception:
            return default_strings.get(lang, default_strings['en'])

class Installer:
    TEMP_DIR = os.path.join(os.getenv('APPDATA'), 'PixelmonPRO', 'tmp')
    os.makedirs(TEMP_DIR, exist_ok=True)
    atexit.register(lambda: 
        shutil.rmtree(TEMP_DIR, ignore_errors=True) if os.path.exists(TEMP_DIR) else None
    )

    def __init__(self):
        self.check_admin()
        self.locale = Locale(self.detect_language())
        self.cancelled = False
        self.progress = 0
        self.log_text = ""
        dpg.create_context()
        self.setup_logging()
        self.setup_ui()
        self.last_logged_progress = -1

    def check_admin(self):
        if not self.is_admin():
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            sys.exit()

    @staticmethod
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def setup_logging(self):
        self.logger = logging.getLogger("Installer")
        self.logger.setLevel(logging.DEBUG if CONFIG['debug'] else logging.INFO)
        
        # Создаем папку для логов только в debug режиме
        if CONFIG['debug']:
            log_dir = "logs"
            os.makedirs(log_dir, exist_ok=True)
            
            handler = RotatingFileHandler(
                os.path.join(log_dir, "installer.log"),
                maxBytes=1024*1024,
                backupCount=5,
                encoding='utf-8'
            )
            
            formatter = logging.Formatter(
                '%(asctime)s [%(levelname)-8s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        # Всегда добавляем вывод в консоль
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(console_handler)
        
        sys.excepthook = lambda t, v, tb: self.logger.error("Uncaught exception", exc_info=(t, v, tb))

    def installation_thread(self):
        try:
            self.update_status("downloading_java")
            if not self.download_java():
                self.logger.error("Java download failed")
                self.update_status("java_install_failed", level='error')
                return
            
            self.update_status("installing_java")
            if not self.install_java():
                self.logger.error("Java install failed")
                self.update_status("java_install_failed", level='error')
                return
            
            self.update_status("extracting_launcher")
            self.extract_launcher_files()
            
            self.update_status("launching_launcher")
            self.launch()
        except Exception as e:
            self.logger.error(f"Installation failed: {e}")
            self.update_status("install_failed", level='error')
                
    def update_status(self, message_key, **kwargs):
        def update():
            try:
                message = self.locale.strings.get(message_key, f"Missing locale: {message_key}").format(**kwargs)
                if dpg.does_item_exist("status_text"):
                    try:
                        dpg.set_value("status_text", message)
                    except Exception as e:
                        self.logger.error(f"UI update failed: {e}")
                self.log_message(message)
            except Exception as e:
                self.logger.error(f"Status update error: {e}")
        try:
            dpg.split_frame()
            update()
        except Exception as e:
            self.logger.error(f"split_frame error: {e}")

    def run(self):
        self.logger.info("=== Starting installer ===")
        if java_path := self.find_java():
            self.extract_launcher_files()
            self.launch(java_path)
            dpg.stop_dearpygui()
            return
        self.install_thread = threading.Thread(target=self.installation_thread, daemon=True)
        self.install_thread.start()
        while dpg.is_dearpygui_running():
            dpg.render_dearpygui_frame()
        if self.install_thread.is_alive():
            self.logger.warning("Waiting for installation thread to finish")
            self.install_thread.join(timeout=5)
        self.logger.info("=== Installer finished ===")
        dpg.destroy_context()

    def setup_ui(self):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u"Pixelmon.PRO.Installer")
        viewport_params = {
            'title': CONFIG['app_title'],
            'width': 800,
            'height': 600,
            'resizable': False
        }
        font_path = resource_path(os.path.join("fonts", "Roboto-Regular.ttf"))
        self.logger.info(f"Attempting to load font from: {font_path}")

        with dpg.font_registry():
            try:
                if os.path.exists(font_path):
                    with dpg.font(font_path, 18, tag="main_font") as default_font:
                        dpg.add_font_range(0x0400, 0x04FF)
                    self.logger.info("Custom font loaded with Cyrillic range")
                else:
                    with dpg.font(":system:bold", 18) as default_font:
                        dpg.add_font_range(0x0400, 0x04FF)
                    self.logger.warning("Using system font with Cyrillic range")
                dpg.bind_font(default_font)
            except Exception as e:
                self.logger.error(f"Font error: {str(e)}")
                with dpg.font(":system:bold", 18) as default_font:
                    dpg.bind_font(default_font)
                    
        favicon_path = resource_path("images/favicon.ico")
        if os.path.exists(favicon_path):
            self.logger.info(f"Found favicon at: {os.path.abspath(favicon_path)}")
            viewport_params['small_icon'] = favicon_path
            viewport_params['large_icon'] = favicon_path
        else:
            self.logger.warning("Favicon not found! Using default icon")
        
        dpg.create_viewport(**viewport_params)
        
        with dpg.texture_registry(show=False):
            logo_path = resource_path("images/logo.png")
            favicon_path = resource_path("images/favicon.png")

            self.logger.info(f"Checking logo path: {os.path.abspath(logo_path)}")
            self.logger.info(f"Checking favicon path: {os.path.abspath(favicon_path)}")

            texture_loaded = False
            if os.path.exists(logo_path):
                try:
                    width, height, channels, data = dpg.load_image(logo_path)
                    self.texture_id = dpg.add_static_texture(width, height, data)
                    texture_loaded = True
                except Exception as e:
                    self.logger.error(f"Error loading logo.png: {e}", exc_info=True)
            if not texture_loaded and os.path.exists(favicon_path):
                try:
                    width, height, channels, data = dpg.load_image(favicon_path)
                    self.texture_id = dpg.add_static_texture(width, height, data)
                    texture_loaded = True
                except Exception as e:
                    self.logger.error(f"Error loading favicon.png: {e}", exc_info=True)
            if not texture_loaded:
                self.texture_id = dpg.add_static_texture(1, 1, [255]*4)
                self.logger.warning("Using fallback texture")
                    
        with dpg.window(label=CONFIG['app_title'], tag="main_window", 
                no_title_bar=True, width=790, height=590):
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=200)
                dpg.add_image(self.texture_id, width=400, height=400)
                dpg.add_spacer(width=200)
            with dpg.group(width=-1):
                dpg.add_progress_bar(
                    tag="progress_bar",
                    default_value=0,
                    overlay="0%",
                    width=-1,
                    height=30
                )
            dpg.add_separator()
            dpg.add_text(self.locale.strings["preparing"], tag="status_text")
            dpg.add_separator()
            with dpg.child_window(tag="log_container", width=-1, height=-50):
                dpg.add_text("", tag="log_output", wrap=0)
                dpg.bind_item_theme("log_output", "log_theme")
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=-1)
                dpg.add_button(
                    label=self.locale.strings["cancel"],
                    callback=self.cancel_callback,
                    tag="cancel_btn",
                    width=100
                )
            with dpg.theme(tag="log_theme"):
                with dpg.theme_component():
                    dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (30, 30, 30, 200))
        dpg.setup_dearpygui()
        dpg.show_viewport()

    def update_progress(self, progress):
        if not dpg.is_dearpygui_running():
            return
        try:
            dpg.set_value("progress_bar", progress/100)
            dpg.configure_item("progress_bar", overlay=f"{progress:.0f}%")
        except Exception as e:
            self.logger.error(f"Progress update error: {e}")

    def log_message(self, message, level='info'):
        try:
            level_map = {
                'debug': self.logger.debug,
                'info': self.logger.info,
                'warning': self.logger.warning,
                'error': self.logger.error
            }
            level_map.get(level.lower(), self.logger.info)(message)
            self.log_text += f"[{level.upper()}] {message}\n"
            if dpg.does_item_exist("log_output"):
                try:
                    dpg.set_value("log_output", self.log_text)
                    dpg.set_y_scroll("log_container", -1)
                except Exception as e:
                    self.logger.error(f"Log UI update error: {e}")
        except Exception as e:
            self.logger.error(f"Logging error: {e}")

    def find_java(self):
        java_path = os.path.join(CONFIG['java']['install_path'], 'bin', 'javaw.exe')
        if os.path.exists(java_path):
            try:
                result = subprocess.run(
                    [java_path, "-version"],
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if CONFIG['java']['version'] in result.stderr:
                    return java_path
            except Exception:
                pass
        try:
            result = subprocess.run(
                ["java", "-version"],
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if CONFIG['java']['version'] in result.stderr:
                return "java"
        except Exception:
            pass

        paths = [
            os.path.join(CONFIG['java']['install_path'], "bin", "javaw.exe"),
            r"C:\Program Files\Java\1.8.0_452\bin\javaw.exe",
            r"C:\Program Files (x86)\Java\1.8.0_452\bin\javaw.exe"
        ]
        
        for path in paths:
            if os.path.exists(path):
                try:
                    result = subprocess.run(
                        [path, "-version"],
                        stderr=subprocess.PIPE,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if CONFIG['java']['version'] in result.stderr:
                        return path
                except Exception:
                    continue
        return None

    def download_java(self):
        temp_zip = os.path.join(self.TEMP_DIR, "java.zip")
        for attempt in range(CONFIG['max_retries']):
            try:
                if os.path.exists(temp_zip) and self.verify_checksum(temp_zip):
                    return True
                
                self.update_status("download_attempt", attempt=attempt+1)
                
                with requests.get(CONFIG['java']['url'], stream=True) as r:
                    r.raise_for_status()
                    total_length = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    with open(temp_zip, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                progress = (downloaded / total_length) * 100 if total_length else 0
                                dpg.split_frame()
                                self.update_progress(progress)
                
                if self.verify_checksum(temp_zip):
                    return True
                else:
                    os.remove(temp_zip)
            except Exception as e:
                self.logger.error(f"Download error: {e}")
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
        return False

    def verify_checksum(self, filename):
        if not os.path.exists(filename):
            self.logger.error(f"File not found: {os.path.abspath(filename)}")
            return False
            
        sha = hashlib.sha256()
        try:
            with open(filename, "rb") as f:
                while chunk := f.read(1024*1024):
                    sha.update(chunk)
            return sha.hexdigest().lower() == CONFIG['java']['sha256'].lower()
        except Exception as e:
            self.logger.error(f"Checksum error: {e}")
            return False

    def handle_download_error(self, error, attempt):
        self.logger.error(f"Download error: {error}")
        temp_zip = os.path.join(self.TEMP_DIR, "java.zip")
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
            
        if attempt == CONFIG['max_retries'] - 1:
            self.log_message(self.locale.strings["download_failed"], 'error')

    def install_java(self):
        temp_zip = os.path.join(self.TEMP_DIR, "java.zip")
        java_install_dir = CONFIG['java']['install_path']
        try:
            self.update_status("installing_java_progress", path=java_install_dir)
            
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(java_install_dir)
            
            subdirs = [d for d in os.listdir(java_install_dir) if os.path.isdir(os.path.join(java_install_dir, d))]
            if len(subdirs) == 1 and subdirs[0].startswith("zulu"):
                nested_dir = os.path.join(java_install_dir, subdirs[0])
                for item in os.listdir(nested_dir):
                    shutil.move(os.path.join(nested_dir, item), java_install_dir)
                os.rmdir(nested_dir)
            
            java_exe = os.path.join(java_install_dir, 'bin', 'javaw.exe')
            if not os.path.exists(java_exe):
                raise Exception("javaw.exe not found after extraction")
            return True
        except Exception as e:
            self.logger.error(f"Java install error: {e}")
            return False

    def cleanup_temp_files(self):
        try:
            temp_zip = os.path.join(self.TEMP_DIR, "java.zip")
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
        except Exception as e:
            self.logger.warning(f"Cleanup error: {e}")

    def extract_launcher_files(self):
        if getattr(sys, 'frozen', False):
            try:
                temp_jar_path = os.path.join(self.TEMP_DIR, LAUNCHER_JAR)
                if os.path.exists(temp_jar_path):
                    os.remove(temp_jar_path)
                shutil.copy2(
                    resource_path(LAUNCHER_JAR),
                    temp_jar_path
                )
                self.logger.info(f"JAR extracted to: {temp_jar_path}")
            except Exception as e:
                self.logger.error(f"Extract error: {e}")
                raise
        else:
            self.logger.warning("Running in development mode")

    def launch(self, java_path=None):
        try:
            dpg.stop_dearpygui()
            dpg.destroy_context()
            
            temp_jar_path = os.path.join(self.TEMP_DIR, LAUNCHER_JAR)
            if not os.path.exists(temp_jar_path):
                self.logger.error(f"JAR not found: {temp_jar_path}")
                os._exit(1)
            
            java_exe = os.path.join(CONFIG['java']['install_path'], 'bin', 'javaw.exe')
            if not os.path.exists(java_exe):
                for root, dirs, files in os.walk(CONFIG['java']['install_path']):
                    if 'javaw.exe' in files:
                        java_exe = os.path.join(root, 'javaw.exe')
                        break
            
            if not os.path.exists(java_exe):
                self.logger.error(f"Java not found: {java_exe}")
                os._exit(1)
            
            subprocess.Popen([
                java_exe,
                '-jar',
                temp_jar_path
            ], creationflags=subprocess.CREATE_NEW_CONSOLE)
            
        except Exception as e:
            self.logger.error(f"Launch error: {e}")
            os._exit(1)

    def cancel_callback(self):
        self.cancelled = True
        dpg.configure_item("cancel_btn", enabled=False)
        self.log_message("Installation cancelled by user", 'warning')

    def detect_language(self):
        try:
            import locale
            lang = locale.getdefaultlocale()[0][0:2].lower()
            if lang == 'ru':
                return 'ru'
            return 'en'
        except:
            return 'en'

if __name__ == "__main__":
    Installer().run()