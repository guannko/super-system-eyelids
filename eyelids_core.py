#!/usr/bin/env python3
"""
Super System Eyelids - Входной репозиторий CORTEX v3.0
Архитектура: 7% core + 2% floating cache
Enhanced with Mistral's improvements
"""

import os
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class DataType(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ARCHIVE = "archive"

class CacheState(Enum):
    INCOMING = "incoming"
    PROCESSING = "processing"
    OUTGOING = "outgoing"
    COMPLETED = "completed"

@dataclass
class DataItem:
    id: str
    content: Any
    data_type: DataType
    timestamp: datetime
    size_bytes: int
    priority: int
    cache_state: CacheState
    target_repo: Optional[str] = None
    processing_time: Optional[float] = None
    is_processed_by_reflex: bool = False  # Mistral's improvement

class EyelidsCore:
    """
    Основной класс управления super-system-eyelids
    Управляет core (7%) и floating cache (2%)
    """
    
    def __init__(self, base_path: str = "./super-system-eyelids"):
        self.base_path = Path(base_path)
        self.core_path = self.base_path / "core"
        self.cache_path = self.base_path / "cache"
        
        # Лимиты из environment variables (Mistral's improvement)
        self.CORE_LIMIT_PERCENT = float(os.getenv("CORE_LIMIT_PERCENT", 7))
        self.CACHE_LIMIT_PERCENT = float(os.getenv("CACHE_LIMIT_PERCENT", 2))
        self.TOTAL_LIMIT_PERCENT = float(os.getenv("TOTAL_LIMIT_PERCENT", 9))
        
        # Пороговые значения для триггеров
        self.CACHE_WARNING_PERCENT = float(os.getenv("CACHE_WARNING_PERCENT", 1.5))
        self.CACHE_CRITICAL_PERCENT = float(os.getenv("CACHE_CRITICAL_PERCENT", 2.0))
        self.CORE_CRITICAL_PERCENT = float(os.getenv("CORE_CRITICAL_PERCENT", 7.0))
        
        # Временные лимиты (в секундах)
        self.PROCESSING_TIMEOUT = int(os.getenv("PROCESSING_TIMEOUT", 10))
        self.AUTOSAVE_INTERVAL = int(os.getenv("AUTOSAVE_INTERVAL", 300))  # 5 минут
        
        # Размеры файлов
        self.MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 10))
        
        self.setup_directories()
        self.setup_logging()
        
        # Статистика и мониторинг
        self.stats = {
            'processed_items': 0,
            'cache_hits': 0,
            'overflow_events': 0,
            'emergency_cleanups': 0,
            'average_processing_time': 0.0,
            'reflex_processed': 0,  # New metric
            'double_processing_prevented': 0  # New metric
        }
        
    def setup_directories(self):
        """Создание структуры директорий"""
        directories = [
            # Core directories (7%)
            self.core_path / "userPreferences",
            self.core_path / "routing-rules",
            self.core_path / "reflex-protocols",
            self.core_path / "system-config",
            
            # Cache directories (2% floating)
            self.cache_path / "incoming",
            self.cache_path / "processing",
            self.cache_path / "outgoing"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            
    def setup_logging(self):
        """Настройка логирования с ротацией"""
        log_path = self.base_path / "logs"
        log_path.mkdir(exist_ok=True)
        
        from logging.handlers import RotatingFileHandler
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                RotatingFileHandler(
                    log_path / "eyelids.log",
                    maxBytes=10*1024*1024,  # 10MB
                    backupCount=5
                ),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("EyelidsCore")
        
    def get_directory_size(self, path: Path) -> int:
        """Получение размера директории в байтах"""
        total_size = 0
        for file_path in path.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        return total_size
        
    def get_size_percentages(self) -> Dict[str, float]:
        """Получение текущих размеров в процентах"""
        # Примерный базовый размер системы (можно настроить)
        base_system_size = 1024 * 1024 * 1024  # 1GB
        
        core_size = self.get_directory_size(self.core_path)
        cache_size = self.get_directory_size(self.cache_path)
        total_size = core_size + cache_size
        
        return {
            'core_percent': (core_size / base_system_size) * 100,
            'cache_percent': (cache_size / base_system_size) * 100,
            'total_percent': (total_size / base_system_size) * 100,
            'core_bytes': core_size,
            'cache_bytes': cache_size,
            'total_bytes': total_size
        }
    
    def check_file_size_limit(self, size_bytes: int) -> bool:
        """Проверка лимита размера файла"""
        max_size = self.MAX_FILE_SIZE_MB * 1024 * 1024
        if size_bytes > max_size:
            self.logger.warning(f"File size {size_bytes} exceeds limit {max_size}")
            return False
        return True