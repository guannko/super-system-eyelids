#!/usr/bin/env python3
"""
Рефлекторные протоколы для super-system-eyelids
Мгновенная реакция на критичные данные и приоритизация
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from eyelids_core import EyelidsCore, DataItem, DataType, CacheState

class ReflexType(Enum):
    INSTANT = "instant"          # < 100ms
    RAPID = "rapid"              # < 500ms
    FAST = "fast"                # < 1s
    NORMAL = "normal"            # < 5s
    BACKGROUND = "background"    # > 5s

class Priority(Enum):
    EMERGENCY = 0    # Системные критичные события
    CRITICAL = 1     # Пользовательские критичные данные
    HIGH = 2         # Важные операции
    MEDIUM = 3       # Обычные операции
    LOW = 4          # Фоновые задачи
    ARCHIVE = 5      # Архивные данные

@dataclass
class ReflexRule:
    """Правило рефлекторной реакции"""
    name: str
    condition: Callable[[DataItem], bool]
    action: Callable[[DataItem], Any]
    reflex_type: ReflexType
    priority: Priority
    max_execution_time: float
    enabled: bool = True
    execution_count: int = 0
    last_execution: Optional[datetime] = None
    average_execution_time: float = 0.0

class ReflexProtocolSystem:
    """
    Система рефлекторных протоколов для мгновенной реакции
    """
    
    def __init__(self, eyelids_core: EyelidsCore):
        self.core = eyelids_core
        self.logger = eyelids_core.logger
        
        # Рефлекторные правила по типам
        self.reflex_rules: Dict[ReflexType, List[ReflexRule]] = {
            ReflexType.INSTANT: [],
            ReflexType.RAPID: [],
            ReflexType.FAST: [],
            ReflexType.NORMAL: [],
            ReflexType.BACKGROUND: []
        }
        
        # Очереди приоритетов
        self.priority_queues: Dict[Priority, List[DataItem]] = {
            Priority.EMERGENCY: [],
            Priority.CRITICAL: [],
            Priority.HIGH: [],
            Priority.MEDIUM: [],
            Priority.LOW: [],
            Priority.ARCHIVE: []
        }
        
        # Статистика рефлексов
        self.reflex_stats = {
            'total_reflexes': 0,
            'instant_reflexes': 0,
            'failed_reflexes': 0,
            'average_response_time': 0.0,
            'last_reflex_time': None
        }
        
        # Автосейв
        self.autosave_interval = 300  # 5 минут
        self.last_autosave = datetime.now()
        
        # Инициализация базовых рефлексов
        self.setup_default_reflexes()
        
        # Запуск фоновых процессов
        self.running = True
        asyncio.create_task(self.reflex_monitor())
        asyncio.create_task(self.priority_processor())
        asyncio.create_task(self.autosave_worker())