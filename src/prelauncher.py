import sys
import os
import subprocess
import zipfile
import requests
import threading
import hashlib
import json
import ctypes
import shutil
import logging
import atexit
import math
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

import dearpygui.dearpygui as dpg
from logging.handlers import RotatingFileHandler

# --- КОНФИГУРАЦИЯ ---
CONFIG: Dict[str, Any] = {
    "app_title": "Pixelmon.PRO",
    "java": {
        "mirrors": [
            {
                "url": "https://client.pixelmon.pro/java/zulu-jre8.0.482-windows-amd64-full.zip",
                "sha256": "e72a6c9b53b6ee970a49dedd2b7c9223760f2acf0421b68515989c7c20946f53"
            },
            {
                "url": "https://cdn.azul.com/zulu/bin/zulu8.86.0.25-ca-fx-jre8.0.452-win_x64.zip",
                "sha256": "7e1e1f3bf894963fee9d1b4d48a94a9d8999768fa36e803ed8e80c6afe12d3bd"
            }
        ],
        "version": "1.8.0_", # Частичное совпадение для поддержки обеих версий: 482 и 452
    },
    "max_retries": 3,
    "debug": False
}

# Динамическое определение путей
PROGRAM_FILES = Path(os.getenv('PROGRAMFILES', 'C:/Program Files'))
CONFIG['java']['install_path'] = PROGRAM_FILES / 'Java' / 'PixelmonPRO_JRE8'
LAUNCHER_JAR = "PixelmonPRO.jar"


class SystemUtils:
    """Утилиты для работы с файловой системой и ОС Windows."""

    @staticmethod
    def resource_path(relative_path: str) -> Path:
        """Возвращает абсолютный путь к ресурсу, совместимо с PyInstaller."""
        try:
            base_path = Path(sys._MEIPASS)
        except AttributeError:
            base_path = Path(__file__).parent.parent  # Учитывая структуру из .spec
            
        return base_path / relative_path

    @staticmethod
    def is_admin() -> bool:
        """Проверяет, запущен ли скрипт с правами администратора."""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    @staticmethod
    def require_admin() -> None:
        """Перезапускает приложение с запросом прав UAC, если их нет."""
        if not SystemUtils.is_admin():
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1
            )
            sys.exit()

    @staticmethod
    def detect_language() -> str:
        """Определяет язык системы (fallback: 'en')."""
        try:
            import locale
            lang = locale.getdefaultlocale()[0][:2].lower()
            if lang == 'ru':
                return 'ru'
            elif lang == 'uk' or lang == 'ua':
                return 'uk'
            return 'en'
        except Exception:
            return 'en'


class Locale:
    """Менеджер локализации (чтение строк из JSON)."""

    def __init__(self, lang: str = 'en'):
        self.strings = self._load_locale(lang)

    def _load_locale(self, lang: str) -> Dict[str, str]:
        # Встроенные дефолтные строки на случай, если файлы *.json отсутствуют
        default_strings = {
            "en": {
                "preparing": "Preparing...",
                "download_attempt": "Download attempt {attempt}",
                "extracting": "Extracting files...",
                "downloading_java": "Downloading Java...",
                "installing_java": "Installing Java...",
                "extracting_launcher": "Extracting launcher...",
                "launching_launcher": "Launching launcher...",
                "cancel": "Cancel",
                "cancelled": "Installation cancelled by user.",
                "download_failed": "Download failed!",
                "install_failed": "Installation failed!",
                "complete": "Installation complete!",
                "launcher_not_found": "Launcher not found!",
                "admin_required": "Administrator rights required",
                "java_install_failed": "Java installation failed!",
                "java_download_failed": "Java download failed!",
                "downloaded_mb": "Downloaded {current:.2f} MB of {total:.2f} MB",
                "installing_java_progress": "Unpacking Java in {path}...",
                "multiple_java_found": "Multiple Java 8 FX installations found. Please select one:",
                "confirm": "Confirm",
                "using_java": "Using Java: {path}",
                "remember_choice": "Remember my choice",
                "download_recommended": "Download recommended version",
                "rule_warning_title": "⚠️ Attention: Project Rules",
                "rule_warning_text": "The official language of the project is Russian. Other languages can be used, but Russian is the priority for communication.\n\nNote: The administration reserves the right to issue punishments or warnings at its discretion for violating this rule.",
                "understand_btn": "I understand and agree",
                "dont_show_again": "Don't show this again"
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
                "cancelled": "Установка отменена пользователем.",
                "download_failed": "Ошибка загрузки!",
                "install_failed": "Ошибка установки!",
                "complete": "Установка завершена!",
                "launcher_not_found": "Лаунчер не найден!",
                "admin_required": "Требуются права администратора",
                "java_install_failed": "Ошибка установки Java!",
                "java_download_failed": "Ошибка загрузки Java!",
                "downloaded_mb": "Скачано {current:.2f} МБ из {total:.2f} МБ",
                "installing_java_progress": "Распаковка Java в {path}...",
                "multiple_java_found": "Найдено несколько версий Java 8 FX. Выберите нужную:",
                "confirm": "Подтвердить",
                "using_java": "Используется Java: {path}",
                "remember_choice": "Запомнить выбор",
                "download_recommended": "Скачать рекомендуемую версию",
                "rule_warning_title": "⚠️ Внимание: Правила проекта",
                "rule_warning_text": "Официальный язык проекта - Русский язык. На проекте также можно прибегать к использованию других языков, но в приоритете общения на проекте - Русский язык.\n\nДополнение: Администрация вправе выдать наказание / предупреждение на своё усмотрение за нарушение этого правила.",
                "understand_btn": "Я понимаю и согласен",
                "dont_show_again": "Больше не показывать"
            },
            "uk": {
                "preparing": "Підготовка...",
                "download_attempt": "Спроба завантаження {attempt}",
                "extracting": "Розпакування файлів...",
                "downloading_java": "Завантаження Java...",
                "installing_java": "Встановлення Java...",
                "extracting_launcher": "Витягування лаунчера...",
                "launching_launcher": "Запуск лаунчера...",
                "cancel": "Скасувати",
                "cancelled": "Встановлення скасовано користувачем.",
                "download_failed": "Помилка завантаження!",
                "install_failed": "Помилка встановлення!",
                "complete": "Встановлення завершено!",
                "launcher_not_found": "Лаунчер не знайдено!",
                "admin_required": "Потрібні права адміністратора",
                "java_install_failed": "Помилка встановлення Java!",
                "java_download_failed": "Помилка завантаження Java!",
                "downloaded_mb": "Завантажено {current:.2f} МБ із {total:.2f} МБ",
                "installing_java_progress": "Розпакування Java в {path}...",
                "multiple_java_found": "Знайдено декілька версій Java 8 FX. Оберіть потрібну:",
                "confirm": "Підтвердити",
                "using_java": "Використовується Java: {path}",
                "remember_choice": "Запам'ятати вибір",
                "download_recommended": "Завантажити рекомендовану версію",
                "rule_warning_title": "⚠️ Увага: Правила проєкту",
                "rule_warning_text": "Офіційна мова проєкту - російська. На проєкті також можна використовувати інші мови, але пріоритетом спілкування є російська.\n\nДоповнення: Адміністрація має право видати покарання / попередження на свій розсуд за порушення цього правила.",
                "understand_btn": "Я розумію та погоджуюсь",
                "dont_show_again": "Більше не показувати"
            }
        }
        
        lang_file = SystemUtils.resource_path(f'lang/{lang}.json')
        try:
            if lang_file.exists():
                with open(lang_file, 'r', encoding='utf-8') as f:
                    file_strings = json.load(f)
                    return {**default_strings.get(lang, default_strings['en']), **file_strings}
        except Exception as e:
            logging.error(f"Failed to load locale {lang}: {e}")
            
        return default_strings.get(lang, default_strings['en'])

    def get(self, key: str, **kwargs) -> str:
        """Возвращает локализованную строку с подставленными переменными."""
        text = self.strings.get(key, f"Missing locale: {key}")
        return text.format(**kwargs) if kwargs else text


class JavaManager:
    """Отвечает за скачивание, проверку и установку Java (JRE)."""

    def __init__(self, logger: logging.Logger, temp_dir: Path):
        self.logger = logger
        self.temp_dir = temp_dir

    def verify_checksum(self, filepath: Path, expected_hash: str) -> bool:
        """Проверяет SHA-256 файла."""
        if not filepath.exists():
            return False
        
        sha = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(1024 * 1024):  # Читаем по 1 МБ
                    sha.update(chunk)
            return sha.hexdigest().lower() == expected_hash.lower()
        except Exception as e:
            self.logger.error(f"Checksum verification failed: {e}")
            return False

    def download_java(self, 
                      progress_callback: Callable[[float], None], 
                      cancel_event: threading.Event) -> bool:
        """Скачивает архив Java частями, перебирая зеркала. Поддерживает прерывание через cancel_event."""
        temp_zip = self.temp_dir / "java.zip"
        
        for mirror_idx, mirror in enumerate(CONFIG['java']['mirrors']):
            url = mirror['url']
            expected_sha = mirror['sha256']
            
            self.logger.info(f"Trying mirror {mirror_idx + 1}: {url}")
            
            for attempt in range(CONFIG['max_retries']):
                if cancel_event.is_set():
                    return False

                if temp_zip.exists() and self.verify_checksum(temp_zip, expected_sha):
                    self.logger.info("Valid Java archive already exists.")
                    return True
                    
                self.logger.info(f"Downloading Java (Attempt {attempt + 1}/{CONFIG['max_retries']} from mirror {mirror_idx + 1})")
                
                try:
                    with requests.get(url, stream=True, timeout=10) as r:
                        r.raise_for_status()
                        total_length = int(r.headers.get('content-length', 0))
                        downloaded = 0
                        
                        with open(temp_zip, "wb") as f:
                            for chunk in r.iter_content(chunk_size=1024 * 512): # Чанки по 512КБ
                                if cancel_event.is_set():
                                    self.logger.warning("Download cancelled by user.")
                                    return False
                                    
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total_length:
                                        progress = (downloaded / total_length) * 100
                                        progress_callback(progress)
                                        
                    if self.verify_checksum(temp_zip, expected_sha):
                        return True
                    else:
                        self.logger.error("Checksum mismatch, removing corrupted archive.")
                        temp_zip.unlink(missing_ok=True)
                        
                except requests.RequestException as e:
                    self.logger.error(f"Network error during download: {e}")
                    temp_zip.unlink(missing_ok=True)
                    
        # Если все зеркала и попытки исчерпаны
        return False

    def install_java(self, cancel_event: threading.Event) -> bool:
        """Распаковывает скачанную Java в целевую директорию."""
        temp_zip = self.temp_dir / "java.zip"
        install_path: Path = CONFIG['java']['install_path']
        
        try:
            install_path.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                if cancel_event.is_set(): return False
                zip_ref.extractall(install_path)
            
            # Обработка вложенной папки (динамический поиск папки, содержащей bin)
            subdirs = [d for d in install_path.iterdir() if d.is_dir()]
            if len(subdirs) == 1 and (subdirs[0] / 'bin').exists():
                nested_dir = subdirs[0]
                for item in nested_dir.iterdir():
                    shutil.move(str(item), str(install_path))
                nested_dir.rmdir()
            
            java_exe = install_path / 'bin' / 'javaw.exe'
            if not java_exe.exists():
                raise FileNotFoundError("javaw.exe not found after extraction")
                
            return True
            
        except Exception as e:
            self.logger.error(f"Java installation failed: {e}")
            return False

    def find_existing_javas(self) -> List[Path]:
        """Ищет ВСЕ установленные версии Java с проверкой наличия JavaFX (jfxrt.jar)."""
        search_paths = []
        
        # 1. Динамическое сканирование стандартных папок Java
        base_dirs = [
            PROGRAM_FILES / "Java",
            Path(os.getenv('ProgramFiles(x86)', 'C:/Program Files (x86)')) / "Java",
            PROGRAM_FILES / "Zulu", # Популярная папка для Azul Zulu
            CONFIG['java']['install_path'].parent # Папка установки нашего лаунчера
        ]
        
        for base_dir in base_dirs:
            if base_dir.exists():
                for sub in base_dir.iterdir():
                    if sub.is_dir():
                        potential_javaw = sub / "bin" / "javaw.exe"
                        if potential_javaw.exists():
                            search_paths.append(potential_javaw)

        # 2. Добавляем системную Java из переменной PATH (если есть)
        system_javaw = shutil.which("javaw")
        if system_javaw:
            try:
                # Извлекаем реальный путь, чтобы избежать ярлыков (symlinks)
                real_path = Path(os.path.realpath(system_javaw))
                search_paths.append(real_path)
            except Exception:
                search_paths.append(Path(system_javaw))

        valid_javas = []
        resolved_paths = set()

        for path in search_paths:
            if not path.exists():
                continue
                
            # Убираем дубликаты путей (например, если PATH указывает на ту же папку)
            try:
                res_path = path.resolve()
            except Exception:
                res_path = path
                
            if res_path in resolved_paths:
                continue
            resolved_paths.add(res_path)
                
            # КРИТИЧЕСКАЯ ПРОВЕРКА: Ищем файл JavaFX (jfxrt.jar)
            # Учитываем, что это может быть JRE (папка lib) или JDK (папка jre/lib)
            jfx_jre = res_path.parent.parent / "lib" / "ext" / "jfxrt.jar"
            jfx_jdk = res_path.parent.parent / "jre" / "lib" / "ext" / "jfxrt.jar"
            
            if not (jfx_jre.exists() or jfx_jdk.exists()):
                self.logger.debug(f"Skipping {res_path}: JavaFX (jfxrt.jar) not found.")
                continue

            # Если FX есть, проверяем версию Java
            try:
                result = subprocess.run(
                    [str(res_path), "-version"],
                    stderr=subprocess.PIPE, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if CONFIG['java']['version'] in result.stderr:
                    self.logger.info(f"Found valid Java WITH JavaFX: {res_path}")
                    valid_javas.append(res_path)
            except Exception as e:
                self.logger.debug(f"Failed to check java version for {res_path}: {e}")
                continue

        return valid_javas


class PrelauncherApp:
    """Главный класс приложения, управляющий UI и рабочим потоком."""

    def __init__(self):
        SystemUtils.require_admin()
        
        # Разделяем основную папку лаунчера и временную папку загрузок
        self.app_dir = Path(os.getenv('APPDATA', 'C:/')) / 'PixelmonPRO'
        self.app_dir.mkdir(parents=True, exist_ok=True)
        
        self.temp_dir = self.app_dir / 'tmp'
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_file = self.app_dir / 'launcher_config.json'
        
        atexit.register(self.cleanup)

        self.locale = Locale(SystemUtils.detect_language())
        self.cancel_event = threading.Event()
        self.java_selected_event = threading.Event() # Событие выбора Java из списка
        self.force_download_event = threading.Event() # Событие принудительной загрузки Java
        self.lang_warning_event = threading.Event() # Событие принятия правил
        self.selected_java: Optional[Path] = None
        self.log_text = ""
        
        self.setup_logging()
        self.java_manager = JavaManager(self.logger, self.temp_dir)
        
        dpg.create_context()
        self.setup_ui()

    def setup_logging(self):
        self.logger = logging.getLogger("Prelauncher")
        self.logger.setLevel(logging.DEBUG if CONFIG['debug'] else logging.INFO)
        
        if CONFIG['debug']:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            handler = RotatingFileHandler(
                log_dir / "installer.log", maxBytes=1024*1024, backupCount=5, encoding='utf-8'
            )
            handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s'))
            self.logger.addHandler(handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(console_handler)

    def cleanup(self):
        """Очищает временные файлы (tmp) при закрытии."""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception as e:
            self.logger.warning(f"Cleanup failed: {e}")

    # --- Универсальные методы работы с конфигом ---
    def get_config_value(self, key: str, default: Any = None) -> Any:
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get(key, default)
            except Exception:
                pass
        return default

    def set_config_value(self, key: str, value: Any):
        try:
            data = {}
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    try: data = json.load(f)
                    except json.JSONDecodeError: data = {}
            
            data[key] = value
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.warning(f"Failed to save config: {e}")

    def log_to_ui(self, message: str, level: str = 'INFO'):
        """Потокобезопасный вывод логов в UI."""
        self.logger.log(logging.getLevelName(level.upper()), message)
        self.log_text += f"[{level.upper()}] {message}\n"
        
        if dpg.is_dearpygui_running() and dpg.does_item_exist("log_output"):
            dpg.set_value("log_output", self.log_text)
            dpg.set_y_scroll("log_container", -1)

    def update_status(self, lang_key: str, **kwargs):
        """Потокобезопасное обновление текста статуса."""
        text = self.locale.get(lang_key, **kwargs)
        self.log_to_ui(text)
        if dpg.is_dearpygui_running() and dpg.does_item_exist("status_text"):
            dpg.set_value("status_text", text)

    def set_progress(self, percentage: float):
        """Обновление прогресс-бара из рабочего потока."""
        if dpg.is_dearpygui_running() and dpg.does_item_exist("progress_bar"):
            dpg.set_value("progress_bar", percentage / 100.0)
            dpg.configure_item("progress_bar", overlay=f"{percentage:.0f}%")

    def installation_worker(self):
        """Фоновый поток для выполнения тяжелых задач (скачивание/установка)."""
        try:
            available_javas = self.java_manager.find_existing_javas()
            java_path = None
            force_download = False
            
            if available_javas:
                # Проверяем, был ли сохранен выбор ранее
                saved_java_str = self.get_config_value("saved_java_path")
                saved_java = Path(saved_java_str) if saved_java_str else None
                
                if saved_java and saved_java in available_javas:
                    java_path = saved_java
                elif len(available_javas) == 1:
                    # Если найдена ровно одна - используем её молча
                    java_path = available_javas[0]
                else:
                    # Если найдено несколько - просим пользователя выбрать
                    self.log_to_ui(f"Multiple Java installations found. Waiting for selection...", "WARNING")
                    combo_items = [str(p) for p in available_javas]
                    
                    if dpg.is_dearpygui_running():
                        dpg.configure_item("java_combo", items=combo_items, default_value=combo_items[0])
                        dpg.configure_item("java_selection_modal", show=True)
                        
                    # Ждем, пока пользователь не выберет Java (или не нажмет отмену/скачивание)
                    while not self.java_selected_event.is_set() and not self.cancel_event.is_set():
                        time.sleep(0.1)
                        
                    if self.cancel_event.is_set():
                        self.update_status("cancelled")
                        return
                    
                    if self.force_download_event.is_set():
                        force_download = True
                    else:
                        java_path = self.selected_java

            # Запускаем загрузку, если Java не найдена или пользователь запросил это явно
            if not available_javas or force_download:
                self.update_status("downloading_java")
                success = self.java_manager.download_java(self.set_progress, self.cancel_event)
                
                if self.cancel_event.is_set():
                    self.update_status("cancelled")
                    return
                if not success:
                    self.update_status("download_failed")
                    self.log_to_ui("Failed to download Java.", "ERROR")
                    return
                
                self.update_status("installing_java")
                self.set_progress(100) # Индикатор для пользователя
                
                if not self.java_manager.install_java(self.cancel_event):
                    self.log_to_ui("Failed to install Java.", "ERROR")
                    return
                    
                java_path = CONFIG['java']['install_path'] / 'bin' / 'javaw.exe'

            # Логируем итоговый путь к Java в UI консоль
            if java_path:
                self.log_to_ui(self.locale.get("using_java", path=str(java_path)), "INFO")

            # 4. Распаковка и запуск Launcher
            if not self.cancel_event.is_set() and java_path:
                self.update_status("extracting_launcher")
                launcher_target = self.extract_launcher()
                
                # --- ПРОВЕРКА ПРАВИЛ ПРОЕКТА О ЯЗЫКЕ (Для не-RU пользователей) ---
                if SystemUtils.detect_language() != 'ru':
                    rule_acknowledged = self.get_config_value("rule_acknowledged", False)
                    if not rule_acknowledged:
                        if dpg.is_dearpygui_running():
                            dpg.configure_item("language_warning_modal", show=True)
                        
                        self.log_to_ui("Waiting for rule acknowledgement...", "WARNING")
                        while not self.lang_warning_event.is_set() and not self.cancel_event.is_set():
                            time.sleep(0.1)
                            
                        if self.cancel_event.is_set():
                            self.update_status("cancelled")
                            return

                self.update_status("launching_launcher")
                self.launch_game(java_path, launcher_target)

        except Exception as e:
            self.log_to_ui(f"Critical installation error: {e}", "ERROR")

    def extract_launcher(self) -> Path:
        """Извлекает JAR лаунчера из ресурсов PyInstaller в ОСНОВНУЮ папку."""
        source_jar = SystemUtils.resource_path(LAUNCHER_JAR)
        
        # Распаковываем не в tmp, а в основную папку (%APPDATA%\PixelmonPRO)
        target_jar = self.app_dir / LAUNCHER_JAR 
        
        if getattr(sys, 'frozen', False):
            if target_jar.exists():
                try:
                    target_jar.unlink()
                except PermissionError:
                    self.logger.warning("Could not delete old JAR, it might be running.")
            
            shutil.copy2(source_jar, target_jar)
            self.logger.info(f"Launcher extracted to: {target_jar}")
            return target_jar
        else:
            self.logger.warning("Running in DEV mode. Using local JAR.")
            return Path(LAUNCHER_JAR)

    def launch_game(self, java_exe: Path, launcher_jar: Path):
        """Запускает основной лаунчер и закрывает прелаунчер."""
        if not launcher_jar.exists():
            self.log_to_ui(f"JAR not found: {launcher_jar}", "ERROR")
            return

        try:
            # Запускаем Java с указанием cwd (рабочей папки), чтобы лаунчер видел свои конфиги
            subprocess.Popen(
                [str(java_exe), '-jar', str(launcher_jar)],
                cwd=str(launcher_jar.parent), 
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            # Отложенное закрытие для плавности UI
            threading.Timer(1.0, dpg.stop_dearpygui).start()
        except Exception as e:
            self.log_to_ui(f"Launch error: {e}", "ERROR")

    def on_cancel_clicked(self):
        """Обработчик кнопки Отмена (в главном окне)."""
        self.cancel_event.set()
        dpg.configure_item("cancel_btn", enabled=False, label="Cancelling...")
        if dpg.does_item_exist("java_selection_modal"):
            dpg.configure_item("java_selection_modal", show=False)
        if dpg.does_item_exist("language_warning_modal"):
            dpg.configure_item("language_warning_modal", show=False)
        self.log_to_ui("Cancellation requested, waiting for threads...", "WARNING")

    def on_java_confirmed(self):
        """Обработчик кнопки подтверждения в модальном окне выбора Java."""
        selected = dpg.get_value("java_combo")
        if selected:
            self.selected_java = Path(selected)
            if dpg.get_value("remember_java_cb"):
                self.set_config_value("saved_java_path", str(self.selected_java))
            dpg.configure_item("java_selection_modal", show=False)
            self.java_selected_event.set() # Разблокируем фоновый поток

    def on_java_cancelled(self):
        """Обработчик кнопки отмены внутри модального окна."""
        dpg.configure_item("java_selection_modal", show=False)
        self.on_cancel_clicked()

    def on_download_recommended(self):
        """Обработчик кнопки принудительного скачивания рекомендуемой версии."""
        dpg.configure_item("java_selection_modal", show=False)
        self.force_download_event.set()
        self.java_selected_event.set() # Разблокируем цикл ожидания

    def on_language_warning_acknowledged(self):
        """Обработчик согласия с правилом о языке."""
        if dpg.get_value("remember_rule_cb"):
            self.set_config_value("rule_acknowledged", True)
        dpg.configure_item("language_warning_modal", show=False)
        self.lang_warning_event.set()

    def setup_ui(self):
        """Инициализация и верстка интерфейса DearPyGui."""
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u"Pixelmon.PRO.Installer")
        
        # --- Глобальная тема для скруглений (Анимации и современный вид) ---
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 6)
        dpg.bind_theme(global_theme)

        font_path = SystemUtils.resource_path(Path("fonts") / "Roboto-Regular.ttf")
        
        with dpg.font_registry():
            default_font = None
            try:
                if font_path.exists():
                    with dpg.font(str(font_path), 18) as font:
                        dpg.add_font_range(0x0400, 0x04FF) # Cyrillic
                        dpg.add_font_range(0x0400, 0x052F) # Ukrainian extended cyrillic (Ґ, Є, І, Ї)
                    default_font = font
                else:
                    self.logger.warning(f"Font not found at {font_path}. Using Windows fallback.")
                    # Безопасный фоллбэк на системные шрифты Windows с кириллицей
                    for fallback in ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]:
                        if Path(fallback).exists():
                            with dpg.font(fallback, 18) as font:
                                dpg.add_font_range(0x0400, 0x04FF)
                                dpg.add_font_range(0x0400, 0x052F)
                            default_font = font
                            break
            except Exception as e:
                self.logger.error(f"Font loading error: {e}")

            if default_font:
                dpg.bind_font(default_font)

        # Текстуры
        logo_path = SystemUtils.resource_path(Path("images") / "logo.png")
        texture_id = None
        
        with dpg.texture_registry(show=False):
            if logo_path.exists():
                try:
                    width, height, channels, data = dpg.load_image(str(logo_path))
                    texture_id = dpg.add_static_texture(width, height, data)
                except Exception as e:
                    self.logger.error(f"Logo load error: {e}")

            if not texture_id:
                # Fallback текстура 1x1 белый пиксель
                texture_id = dpg.add_static_texture(1, 1, [255, 255, 255, 255])

        # Тема прогресс-бара для кастомной анимации цвета
        with dpg.theme() as progress_theme:
            with dpg.theme_component(dpg.mvProgressBar):
                dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram, (70, 130, 180, 255), tag="progress_color")
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (40, 40, 40, 255))

        # Настраиваем параметры окна и Favicon
        viewport_kwargs = {
            "title": CONFIG['app_title'],
            "width": 800,
            "height": 600,
            "resizable": False
        }
        
        favicon_path = SystemUtils.resource_path(Path("images") / "favicon.ico")
        if favicon_path.exists():
            viewport_kwargs["small_icon"] = str(favicon_path)
            viewport_kwargs["large_icon"] = str(favicon_path)
        else:
            self.logger.warning(f"Favicon not found at {favicon_path}")

        # Главное окно
        with dpg.window(tag="main_window", no_title_bar=True):
            with dpg.group(horizontal=True):
                # Логотип теперь 250x250 (был 400x400). 
                # Чтобы выровнять по центру окна (ширина ~784 без padding), нужен spacer ~267
                dpg.add_spacer(width=267)
                dpg.add_image(texture_id, width=250, height=250)
                
            with dpg.group(width=-1):
                dpg.add_progress_bar(tag="progress_bar", default_value=0.0, overlay="0%", width=-1, height=30)
                dpg.bind_item_theme("progress_bar", progress_theme)
                
            dpg.add_separator()
            dpg.add_text(self.locale.get("preparing"), tag="status_text")
            dpg.add_separator()
            
            # Поскольку логотип стал меньше на 150px, это окно теперь займет намного больше места!
            with dpg.child_window(tag="log_container", width=-1, height=-50):
                dpg.add_text("", tag="log_output", wrap=0)
                with dpg.theme() as log_theme:
                    with dpg.theme_component():
                        dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 200, 200, 255))
                        dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (25, 25, 25, 255))
                dpg.bind_item_theme("log_output", log_theme)
                
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=-1) # Прижать вправо
                dpg.add_button(
                    label=self.locale.get("cancel"), 
                    callback=self.on_cancel_clicked, 
                    tag="cancel_btn", 
                    width=120, height=30
                )

        # Модальное окно для выбора Java (по умолчанию скрыто)
        with dpg.window(tag="java_selection_modal", modal=True, show=False, no_title_bar=True, no_resize=True, pos=[150, 180], width=500):
            with dpg.group():
                dpg.add_spacer(height=10)
                dpg.add_text(self.locale.get("multiple_java_found"))
                dpg.add_spacer(height=10)
                dpg.add_combo([], tag="java_combo", width=-1)
                dpg.add_spacer(height=5)
                dpg.add_checkbox(label=self.locale.get("remember_choice"), tag="remember_java_cb")
                dpg.add_spacer(height=15)
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=100) # Центрируем кнопки
                    dpg.add_button(label=self.locale.get("confirm"), width=130, callback=self.on_java_confirmed)
                    dpg.add_button(label=self.locale.get("cancel"), width=130, callback=self.on_java_cancelled)
                dpg.add_spacer(height=5)
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=100)
                    # Ширина 130+130+8 (отступ) = 268 пикселей
                    dpg.add_button(label=self.locale.get("download_recommended"), width=268, callback=self.on_download_recommended)
                dpg.add_spacer(height=10)

        # Новое модальное окно: Предупреждение о языке сервера
        with dpg.window(tag="language_warning_modal", modal=True, show=False, no_title_bar=True, no_resize=True, pos=[100, 150], width=600):
            with dpg.group():
                dpg.add_spacer(height=10)
                # Красный цвет для привлечения внимания
                dpg.add_text(self.locale.get("rule_warning_title"), color=(255, 80, 80, 255))
                dpg.add_spacer(height=10)
                dpg.add_text(self.locale.get("rule_warning_text"), wrap=560)
                dpg.add_spacer(height=15)
                dpg.add_checkbox(label=self.locale.get("dont_show_again"), tag="remember_rule_cb")
                dpg.add_spacer(height=20)
                with dpg.group(horizontal=True):
                    dpg.add_spacer(width=175) # Центрируем кнопку (ширина окна 600)
                    dpg.add_button(label=self.locale.get("understand_btn"), width=250, height=35, callback=self.on_language_warning_acknowledged)
                dpg.add_spacer(height=10)

        dpg.create_viewport(**viewport_kwargs)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        
        # Привязываем наше окно к размерам viewport, делая его неподвижным фундаментом
        dpg.set_primary_window("main_window", True)

    def run(self):
        """Запуск главного цикла событий (Event Loop) с кастомными анимациями."""
        self.logger.info("=== Starting Prelauncher ===")
        
        # Запускаем логику в отдельном потоке
        worker_thread = threading.Thread(target=self.installation_worker, daemon=True)
        worker_thread.start()
        
        # Заменяем стандартный dpg.start_dearpygui() на кастомный Event Loop 
        # для создания плавной анимации пульсации прогресс-бара.
        while dpg.is_dearpygui_running():
            # Вычисляем синусоиду для плавной анимации (breathing effect)
            pulse = (math.sin(time.time() * 4) + 1) / 2  # Нормализуем значение от 0.0 до 1.0
            
            r = int(60 + 40 * pulse)   # от 60 до 100
            g = int(130 + 50 * pulse)  # от 130 до 180
            b = int(180 + 40 * pulse)  # от 180 до 220
            
            if dpg.does_item_exist("progress_color"):
                dpg.set_value("progress_color", [r, g, b, 255])
                
            dpg.render_dearpygui_frame()
        
        # Завершение
        if worker_thread.is_alive():
            self.cancel_event.set()
            if dpg.does_item_exist("java_selection_modal"):
                dpg.configure_item("java_selection_modal", show=False)
            if dpg.does_item_exist("language_warning_modal"):
                dpg.configure_item("language_warning_modal", show=False)
            self.java_selected_event.set() # Освобождаем фоновый поток, если он ждет выбора
            self.lang_warning_event.set()
            worker_thread.join(timeout=2.0)
            
        dpg.destroy_context()
        self.logger.info("=== Prelauncher Finished ===")


if __name__ == "__main__":
    app = PrelauncherApp()
    app.run()