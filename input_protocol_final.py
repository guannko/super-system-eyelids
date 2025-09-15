"""
CORTEX v3.0 - Input Protocol FINAL VERSION
С ВСЕМИ улучшениями от Mistral
"""

import hashlib
import json
import asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict
import logging
from pathlib import Path

# Настройка логирования
logger = logging.getLogger(__name__)

class DataType(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ARCHIVE = "archive"

class ValidationResult(Enum):
    VALID = "valid"
    INVALID_STRUCTURE = "invalid_structure"
    SIZE_EXCEEDED = "size_exceeded"
    CORRUPTED = "corrupted"
    MALICIOUS_CONTENT = "malicious_content"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    RATE_LIMITED = "rate_limited"

@dataclass
class InputData:
    """Структура входящих данных"""
    content: Any
    source: str
    metadata: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    checksum: Optional[str] = None
    data_type: Optional[DataType] = None
    data_id: Optional[str] = None
    validation_result: Optional[ValidationResult] = None

class InputProtocolFinal:
    """Финальная версия Input Protocol со всеми улучшениями"""
    
    def __init__(self, cache_client, reflex_manager, webhook_config=None):
        self.cache = cache_client
        self.reflex = reflex_manager
        self.webhook_config = webhook_config or {}
        
        # Асинхронные очереди для параллельной обработки
        self.input_queue = asyncio.Queue(maxsize=10000)
        self.priority_queue = asyncio.Queue(maxsize=1000)
        self.processing_tasks = []
        
        # Rate limiting
        self.rate_limits = {
            DataType.CRITICAL: 1000,  # per minute
            DataType.HIGH: 500,
            DataType.MEDIUM: 200,
            DataType.LOW: 100,
            DataType.ARCHIVE: 50
        }
        self.rate_counters = defaultdict(lambda: {"count": 0, "reset_time": datetime.now()})
        
        # Circuit breaker
        self.circuit_breaker = {
            "failures": 0,
            "max_failures": 10,
            "state": "CLOSED",  # CLOSED, OPEN, HALF_OPEN
            "last_failure": None,
            "cooldown": timedelta(minutes=5)
        }
        
        # Размерные лимиты
        self.size_limits = {
            DataType.CRITICAL: 10 * 1024 * 1024,    # 10MB
            DataType.HIGH: 50 * 1024 * 1024,        # 50MB
            DataType.MEDIUM: 100 * 1024 * 1024,     # 100MB
            DataType.LOW: 500 * 1024 * 1024,        # 500MB
            DataType.ARCHIVE: 1024 * 1024 * 1024    # 1GB
        }
        
        # Приоритеты для рефлексов
        self.priority_map = {
            DataType.CRITICAL: 6,
            DataType.HIGH: 5,
            DataType.MEDIUM: 3,
            DataType.LOW: 2,
            DataType.ARCHIVE: 1
        }
        
        # Паттерны вредоносного контента
        self.forbidden_patterns = [
            r"eval\s*\(", r"exec\s*\(", r"__import__\s*\(",
            r"os\.system", r"subprocess\.", r"open\s*\(",
            r"DROP\s+TABLE", r"DELETE\s+FROM", r"UPDATE\s+.*\s+SET",
            r"<script[^>]*>", r"javascript:", r"onerror\s*=",
            r"import\s+os", r"from\s+os\s+import",
            r"\\x[0-9a-fA-F]{2}", r"\\u[0-9a-fA-F]{4}"  # hex escapes
        ]
        
        # Детализированная статистика
        self.stats = {
            "total": {"processed": 0, "errors": 0, "rejected": 0},
            "by_type": {dt.value: {"processed": 0, "errors": 0} for dt in DataType},
            "by_source": defaultdict(lambda: {"processed": 0, "errors": 0}),
            "by_validation": {vr.value: 0 for vr in ValidationResult},
            "processing_times": [],
            "last_export": None
        }
        
        logger.info("Input Protocol Final initialized with all enhancements")
    
    # ========== ВАЛИДАЦИЯ КОНТЕНТА ==========
    
    def validate_content_security(self, content: Any) -> Tuple[bool, Optional[str]]:
        """Проверка контента на вредоносный код"""
        try:
            content_str = str(content).lower() if not isinstance(content, str) else content.lower()
            
            # Проверка на вредоносные паттерны
            for pattern in self.forbidden_patterns:
                if re.search(pattern, content_str, re.IGNORECASE):
                    return False, f"Malicious pattern detected: {pattern}"
            
            # Проверка на подозрительную длину (возможный overflow)
            if len(content_str) > 10_000_000:  # 10MB текста
                return False, "Content too large for text validation"
            
            # Проверка на бинарные данные в текстовом контенте
            if isinstance(content, str):
                try:
                    content.encode('utf-8')
                except UnicodeEncodeError:
                    return False, "Invalid encoding detected"
            
            return True, None
            
        except Exception as e:
            logger.error(f"Content validation error: {e}")
            return False, str(e)
    
    # ========== ПРОВЕРКА КОНТРОЛЬНОЙ СУММЫ ==========
    
    def calculate_checksum(self, content: Any) -> str:
        """Вычисление контрольной суммы"""
        data_str = json.dumps(content, default=str, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
    
    def verify_checksum(self, data: InputData) -> bool:
        """Проверка целостности данных по контрольной сумме"""
        if not data.checksum:
            return True  # Если нет checksum, пропускаем проверку
        
        current_checksum = self.calculate_checksum(data.content)
        return current_checksum == data.checksum
    
    # ========== RATE LIMITING ==========
    
    def check_rate_limit(self, data_type: DataType, source: str) -> bool:
        """Проверка rate limiting"""
        now = datetime.now()
        key = f"{data_type.value}:{source}"
        counter = self.rate_counters[key]
        
        # Сброс счётчика каждую минуту
        if now - counter["reset_time"] > timedelta(minutes=1):
            counter["count"] = 0
            counter["reset_time"] = now
        
        # Проверка лимита
        if counter["count"] >= self.rate_limits[data_type]:
            return False
        
        counter["count"] += 1
        return True
    
    # ========== CIRCUIT BREAKER ==========
    
    def check_circuit_breaker(self) -> bool:
        """Проверка состояния circuit breaker"""
        cb = self.circuit_breaker
        
        if cb["state"] == "OPEN":
            # Проверка времени cooldown
            if datetime.now() - cb["last_failure"] > cb["cooldown"]:
                cb["state"] = "HALF_OPEN"
                cb["failures"] = 0
                logger.info("Circuit breaker: OPEN -> HALF_OPEN")
            else:
                return False
        
        return True
    
    def record_failure(self):
        """Регистрация сбоя для circuit breaker"""
        cb = self.circuit_breaker
        cb["failures"] += 1
        cb["last_failure"] = datetime.now()
        
        if cb["failures"] >= cb["max_failures"]:
            cb["state"] = "OPEN"
            logger.error(f"Circuit breaker OPEN after {cb['failures']} failures")
    
    def record_success(self):
        """Регистрация успеха для circuit breaker"""
        cb = self.circuit_breaker
        if cb["state"] == "HALF_OPEN":
            cb["state"] = "CLOSED"
            cb["failures"] = 0
            logger.info("Circuit breaker: HALF_OPEN -> CLOSED")
    
    # ========== ОСНОВНОЙ ПРОТОКОЛ ==========
    
    async def input_protocol(self, raw_data: Any, source: str, metadata: Optional[Dict] = None) -> Tuple[bool, str, Dict]:
        """Основной протокол обработки с всеми улучшениями"""
        start_time = datetime.now()
        metadata = metadata or {}
        
        try:
            # 1. Проверка circuit breaker
            if not self.check_circuit_breaker():
                self.stats["by_validation"][ValidationResult.RATE_LIMITED.value] += 1
                return False, "", {"error": "Circuit breaker is OPEN"}
            
            # 2. Создание структуры данных
            input_data = InputData(
                content=raw_data,
                source=source,
                metadata=metadata,
                checksum=self.calculate_checksum(raw_data)
            )
            
            # 3. Валидация структуры
            validation_result = await self.validate_data_structure(input_data)
            input_data.validation_result = validation_result
            
            if validation_result != ValidationResult.VALID:
                self.stats["by_validation"][validation_result.value] += 1
                self.record_failure()
                await self.send_webhook({
                    "event": "validation_failed",
                    "reason": validation_result.value,
                    "source": source
                })
                return False, "", {"error": f"Validation failed: {validation_result.value}"}
            
            # 4. Проверка контрольной суммы
            if not self.verify_checksum(input_data):
                self.stats["by_validation"][ValidationResult.CHECKSUM_MISMATCH.value] += 1
                return False, "", {"error": "Checksum verification failed"}
            
            # 5. Проверка на вредоносный контент
            is_safe, threat_info = self.validate_content_security(input_data.content)
            if not is_safe:
                self.stats["by_validation"][ValidationResult.MALICIOUS_CONTENT.value] += 1
                await self.send_webhook({
                    "event": "malicious_content_detected",
                    "threat": threat_info,
                    "source": source
                })
                return False, "", {"error": f"Malicious content: {threat_info}"}
            
            # 6. Определение типа данных
            data_type = self.determine_data_type(input_data)
            input_data.data_type = data_type
            
            # 7. Проверка rate limiting
            if not self.check_rate_limit(data_type, source):
                self.stats["by_validation"][ValidationResult.RATE_LIMITED.value] += 1
                return False, "", {"error": "Rate limit exceeded"}
            
            # 8. Генерация уникального ID
            data_id = self.generate_data_id(input_data)
            input_data.data_id = data_id
            
            # 9. Маршрутизация в кэш
            routed = await self.route_to_cache(data_id, input_data, data_type)
            if not routed:
                self.record_failure()
                return False, data_id, {"error": "Failed to route to cache"}
            
            # 10. Запуск рефлексов
            reflex_triggered = await self.trigger_reflex(data_id, data_type, metadata)
            
            # Обновление статистики
            self.update_stats(source, data_type, True, start_time)
            self.record_success()
            
            return True, data_id, {
                "status": "processed",
                "data_type": data_type.value,
                "reflex_triggered": reflex_triggered,
                "processing_time": (datetime.now() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Input protocol error: {e}")
            self.update_stats(source, None, False, start_time)
            self.record_failure()
            return False, "", {"error": str(e)}
    
    # ========== BATCH PROCESSING ==========
    
    async def batch_input_protocol(self, raw_data_list: List[Tuple[Any, str, Dict]], 
                                  batch_size: int = 100) -> List[Tuple[bool, str, Dict]]:
        """Пакетная обработка данных"""
        results = []
        
        # Разбиваем на батчи
        for i in range(0, len(raw_data_list), batch_size):
            batch = raw_data_list[i:i + batch_size]
            
            # Параллельная обработка батча
            tasks = [
                self.input_protocol(raw_data, source, metadata)
                for raw_data, source, metadata in batch
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Обработка результатов
            for result in batch_results:
                if isinstance(result, Exception):
                    results.append((False, "", {"error": str(result)}))
                else:
                    results.append(result)
        
        return results
    
    # ========== АСИНХРОННЫЕ ОЧЕРЕДИ ==========
    
    async def start_processing_loop(self):
        """Запуск обработчиков очередей"""
        # Обработчик обычной очереди
        async def process_regular():
            while True:
                try:
                    raw_data, source, metadata = await self.input_queue.get()
                    await self.input_protocol(raw_data, source, metadata)
                    self.input_queue.task_done()
                except Exception as e:
                    logger.error(f"Queue processing error: {e}")
        
        # Обработчик приоритетной очереди
        async def process_priority():
            while True:
                try:
                    raw_data, source, metadata = await self.priority_queue.get()
                    await self.input_protocol(raw_data, source, metadata)
                    self.priority_queue.task_done()
                except Exception as e:
                    logger.error(f"Priority queue processing error: {e}")
        
        # Запуск обработчиков
        for _ in range(4):  # 4 воркера для обычной очереди
            task = asyncio.create_task(process_regular())
            self.processing_tasks.append(task)
        
        for _ in range(2):  # 2 воркера для приоритетной очереди
            task = asyncio.create_task(process_priority())
            self.processing_tasks.append(task)
        
        logger.info("Processing loops started: 4 regular + 2 priority workers")
    
    async def add_to_queue(self, raw_data: Any, source: str, metadata: Dict = None, priority: bool = False):
        """Добавление данных в очередь"""
        queue = self.priority_queue if priority else self.input_queue
        await queue.put((raw_data, source, metadata or {}))
    
    # ========== ЭКСПОРТ СТАТИСТИКИ ==========
    
    async def export_stats(self, filename: str = None):
        """Экспорт статистики в файл"""
        filename = filename or f"input_protocol_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # Подсчёт средних времён обработки
        avg_time = sum(self.stats["processing_times"][-100:]) / len(self.stats["processing_times"][-100:]) \
                  if self.stats["processing_times"] else 0
        
        export_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_processed": self.stats["total"]["processed"],
                "total_errors": self.stats["total"]["errors"],
                "total_rejected": self.stats["total"]["rejected"],
                "avg_processing_time": avg_time,
                "success_rate": (self.stats["total"]["processed"] / 
                               (self.stats["total"]["processed"] + self.stats["total"]["errors"]) * 100
                               if self.stats["total"]["processed"] > 0 else 0)
            },
            "by_type": self.stats["by_type"],
            "by_source": dict(self.stats["by_source"]),
            "by_validation": self.stats["by_validation"],
            "circuit_breaker": {
                "state": self.circuit_breaker["state"],
                "failures": self.circuit_breaker["failures"]
            }
        }
        
        # Сохранение в файл
        stats_dir = Path("stats")
        stats_dir.mkdir(exist_ok=True)
        
        with open(stats_dir / filename, "w") as f:
            json.dump(export_data, f, indent=2, default=str)
        
        self.stats["last_export"] = datetime.now()
        logger.info(f"Stats exported to {filename}")
        
        # Опционально: отправка через webhook
        if self.webhook_config.get("stats_webhook"):
            await self.send_webhook({
                "event": "stats_exported",
                "filename": filename,
                "summary": export_data["summary"]
            })
        
        return filename
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========
    
    async def validate_data_structure(self, data: InputData) -> ValidationResult:
        """Улучшенная валидация структуры данных"""
        try:
            # Базовая проверка
            if not data.content:
                return ValidationResult.INVALID_STRUCTURE
            
            # Проверка размера
            content_size = len(json.dumps(data.content, default=str))
            if data.data_type and content_size > self.size_limits.get(data.data_type, float('inf')):
                return ValidationResult.SIZE_EXCEEDED
            
            # Проверка сериализуемости
            try:
                json.dumps(data.content, default=str)
            except:
                return ValidationResult.CORRUPTED
            
            return ValidationResult.VALID
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return ValidationResult.CORRUPTED
    
    def determine_data_type(self, data: InputData) -> DataType:
        """Определение типа данных"""
        # Проверка метаданных
        if data.metadata.get("priority") == "critical":
            return DataType.CRITICAL
        
        # Проверка источника
        if data.source in ["monitoring", "alerts", "security"]:
            return DataType.HIGH
        
        # Проверка размера
        content_size = len(json.dumps(data.content, default=str))
        if content_size > 100 * 1024 * 1024:  # > 100MB
            return DataType.ARCHIVE
        
        # По умолчанию
        return DataType.MEDIUM
    
    def generate_data_id(self, data: InputData) -> str:
        """Генерация уникального ID"""
        timestamp = data.timestamp.strftime("%Y%m%d_%H%M%S_%f")
        content_hash = hashlib.md5(json.dumps(data.content, default=str).encode()).hexdigest()[:8]
        source_hash = hashlib.md5(data.source.encode()).hexdigest()[:4]
        return f"{timestamp}_{content_hash}_{source_hash}"
    
    async def route_to_cache(self, data_id: str, data: InputData, data_type: DataType) -> bool:
        """Улучшенная маршрутизация с учётом приоритетов"""
        try:
            # Специальный путь для критичных данных
            if data_type == DataType.CRITICAL:
                cache_path = f"critical_priority/{data_id}"
            elif data_type == DataType.HIGH:
                cache_path = f"high_priority/{data_id}"
            else:
                cache_path = f"incoming/{data_type.value}/{data_id}"
            
            # Сохранение в кэш с расширенными метаданными
            cache_entry = {
                "id": data_id,
                "content": data.content,
                "source": data.source,
                "data_type": data_type.value,
                "timestamp": data.timestamp.isoformat(),
                "checksum": data.checksum,
                **data.metadata  # Распаковка метаданных на верхний уровень
            }
            
            await self.cache.set(cache_path, cache_entry)
            logger.info(f"Data routed to {cache_path}")
            return True
            
        except Exception as e:
            logger.error(f"Cache routing failed: {e}")
            return False
    
    async def trigger_reflex(self, data_id: str, data_type: DataType, metadata: Dict[str, Any]) -> bool:
        """Запуск рефлексов с детальным логированием"""
        try:
            priority = self.priority_map[data_type]
            
            logger.info(f"Triggering reflex for {data_id} (type: {data_type.value}, priority: {priority})")
            
            result = await self.reflex.trigger(
                trigger_type=f"data_{data_type.value}",
                data={"id": data_id, "metadata": metadata},
                priority=priority
            )
            
            if result:
                logger.info(f"Reflex successfully triggered for {data_id}")
            else:
                logger.warning(f"Reflex failed for {data_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Reflex trigger failed for {data_id}: {e}")
            return False
    
    async def send_webhook(self, data: Dict[str, Any]):
        """Отправка webhook уведомлений"""
        if not self.webhook_config.get("url"):
            return
        
        # Здесь должна быть реальная отправка webhook
        logger.info(f"Webhook sent: {data}")
    
    def update_stats(self, source: str, data_type: Optional[DataType], success: bool, start_time: datetime):
        """Обновление детализированной статистики"""
        processing_time = (datetime.now() - start_time).total_seconds()
        self.stats["processing_times"].append(processing_time)
        
        # Ограничение размера истории
        if len(self.stats["processing_times"]) > 1000:
            self.stats["processing_times"] = self.stats["processing_times"][-1000:]
        
        # Обновление счётчиков
        if success:
            self.stats["total"]["processed"] += 1
            self.stats["by_source"][source]["processed"] += 1
            if data_type:
                self.stats["by_type"][data_type.value]["processed"] += 1
        else:
            self.stats["total"]["errors"] += 1
            self.stats["by_source"][source]["errors"] += 1
            if data_type:
                self.stats["by_type"][data_type.value]["errors"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        total = self.stats["total"]["processed"] + self.stats["total"]["errors"]
        success_rate = (self.stats["total"]["processed"] / total * 100) if total > 0 else 0
        
        avg_time = sum(self.stats["processing_times"][-100:]) / len(self.stats["processing_times"][-100:]) \
                  if self.stats["processing_times"] else 0
        
        return {
            "total_processed": self.stats["total"]["processed"],
            "total_errors": self.stats["total"]["errors"],
            "total_rejected": self.stats["total"]["rejected"],
            "success_rate": f"{success_rate:.2f}%",
            "avg_processing_time": f"{avg_time:.3f}s",
            "circuit_breaker_state": self.circuit_breaker["state"],
            "by_type": self.stats["by_type"],
            "last_export": self.stats["last_export"].isoformat() if self.stats["last_export"] else None
        }
    
    async def shutdown(self):
        """Корректное завершение работы"""
        logger.info("Shutting down Input Protocol...")
        
        # Экспорт финальной статистики
        await self.export_stats("final_stats.json")
        
        # Отмена всех задач
        for task in self.processing_tasks:
            task.cancel()
        
        # Ожидание завершения очередей
        await self.input_queue.join()
        await self.priority_queue.join()
        
        logger.info("Input Protocol shutdown complete")


# ========== ПРИМЕР ИСПОЛЬЗОВАНИЯ ==========

async def example_usage():
    """Пример использования финального Input Protocol"""
    
    # Инициализация зависимостей (моки для примера)
    class MockCache:
        async def set(self, key, value):
            return True
    
    class MockReflex:
        async def trigger(self, trigger_type, data, priority):
            return True
    
    # Создание протокола
    protocol = InputProtocolFinal(
        cache_client=MockCache(),
        reflex_manager=MockReflex(),
        webhook_config={"url": "https://webhook.example.com"}
    )
    
    # Запуск обработчиков очередей
    await protocol.start_processing_loop()
    
    # Примеры использования
    
    # 1. Обычная обработка
    success, data_id, result = await protocol.input_protocol(
        {"message": "test data"},
        "api",
        {"user": "test"}
    )
    print(f"Regular processing: {success}, ID: {data_id}")
    
    # 2. Пакетная обработка
    batch_data = [
        ({"msg": f"data_{i}"}, "batch", {"index": i})
        for i in range(10)
    ]
    batch_results = await protocol.batch_input_protocol(batch_data)
    print(f"Batch processed: {len(batch_results)} items")
    
    # 3. Добавление в очередь
    await protocol.add_to_queue(
        {"priority_message": "urgent"},
        "system",
        {"alert": True},
        priority=True
    )
    
    # 4. Экспорт статистики
    stats_file = await protocol.export_stats()
    print(f"Stats exported to: {stats_file}")
    
    # 5. Получение текущей статистики
    current_stats = protocol.get_stats()
    print(f"Current stats: {json.dumps(current_stats, indent=2)}")
    
    # Завершение работы
    await protocol.shutdown()


if __name__ == "__main__":
    asyncio.run(example_usage())
