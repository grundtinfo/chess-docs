import sys
from datetime import datetime

class Logger:
    DEBUG_LEVEL = 0

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
        sys.stdout.write(f"[{timestamp}][{normalized_level}] {message}\n")
        sys.stdout.flush()
