import sys
from datetime import datetime
from pathlib import Path

class Logger:
    DEBUG_LEVEL = 0
    _log_handle = None

    @classmethod
    def configure_file_logging(cls, script_path=None, log_dir=None):
        script_name = Path(script_path or sys.argv[0]).stem
        project_dir = Path(__file__).resolve().parent.parent
        target_dir = Path(log_dir) if log_dir else project_dir / "logs"
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = target_dir / f"{script_name}_{datetime.now().strftime('%Y%m%d-%H%M')}.log"

        if cls._log_handle:
            current_path = Path(cls._log_handle.name)
            if current_path == log_path:
                return log_path
            cls._log_handle.close()

        cls._log_handle = log_path.open("a", encoding="utf-8")
        return log_path

    @classmethod
    def set_debug_enabled(cls, enabled=True, level=1):
        if not enabled:
            cls.DEBUG_LEVEL = 0
        else:
            try:
                cls.DEBUG_LEVEL = int(level)
            except (TypeError, ValueError):
                cls.DEBUG_LEVEL = 1
        if cls.DEBUG_LEVEL < 0: cls.DEBUG_LEVEL = 0
        if cls.DEBUG_LEVEL > 2: cls.DEBUG_LEVEL = 2

    @classmethod
    def debug_log(cls, message, level="INFO"):
        normalized_level = str(level).upper()
        if cls.DEBUG_LEVEL == 0 and normalized_level not in ["ALWAYS", "ERROR", "WARNING", "ESSENTIAL"]:
            return
        if cls.DEBUG_LEVEL == 1 and normalized_level not in ["ALWAYS", "ERROR", "WARNING", "ESSENTIAL", "INFO"]:
            return
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
        line = f"[{timestamp}][{normalized_level}] {message}\n"
        sys.stdout.write(line)
        sys.stdout.flush()
        if cls._log_handle:
            cls._log_handle.write(line)
            cls._log_handle.flush()
