"""
CORTEX v3.0 - Autosave Protocol ENHANCED
С критическими улучшениями от Mistral - шифрование, параллельная обработка, Prometheus
"""

import asyncio
import time
import json
import hashlib
import gzip
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set, AsyncGenerator
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor
import aiofiles
import aiohttp
from collections import defaultdict, deque
from cryptography.fernet import Fernet
import base64

# Prometheus метрики (опционально)
try:
    from prometheus_client import Counter, Gauge, Histogram, Summary
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class SnapshotType(Enum):
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"
    FULL = "full"
    EMERGENCY = "emergency"

class CompressionLevel(Enum):
    NONE = 0
    LOW = 1
    MEDIUM = 6
    HIGH = 9

class SnapshotStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    UPLOADED = "uploaded"
    ARCHIVED = "archived"

@dataclass
class SnapshotConfig:
    interval_minutes: int = 5
    max_snapshots_local: int = 100
    max_snapshots_memory: int = 50
    compression_level: CompressionLevel = CompressionLevel.MEDIUM
    auto_upload: bool = True
    cortex_memory_url: str = "http://localhost:8080/cortex-memory"
    cortex_memory_token: Optional[str] = None
    backup_directory: str = "./snapshots"
    max_snapshot_size_mb: int = 500
    enable_encryption: bool = False
    encryption_key: Optional[str] = None
    enable_prometheus: bool = True
    parallel_workers: int = 4
    verify_integrity: bool = True
    secondary_backup_url: Optional[str] = None
    
    # Динамические интервалы
    incremental_interval: int = 5
    differential_interval: int = 60
    full_interval: int = 360

@dataclass
class DataChange:
    path: str
    operation: str
    old_hash: Optional[str]
    new_hash: Optional[str]
    timestamp: float
    size_bytes: int
    data_type: str

@dataclass
class Snapshot:
    id: str
    timestamp: float
    snapshot_type: SnapshotType
    status: SnapshotStatus
    file_path: str
    size_bytes: int
    compressed_size_bytes: int
    changes_count: int
    data_hash: str
    parent_snapshot_id: Optional[str] = None
    upload_url: Optional[str] = None
    metadata: Dict = None
    encrypted: bool = False
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class AutosaveStats:
    total_snapshots: int = 0
    successful_snapshots: int = 0
    failed_snapshots: int = 0
    total_data_saved_gb: float = 0
    total_upload_time: float = 0
    average_snapshot_time: float = 0
    last_snapshot_time: float = 0
    last_upload_time: float = 0
    compression_ratio: float = 0
    encrypted_snapshots: int = 0
    integrity_checks_passed: int = 0
    integrity_checks_failed: int = 0

class AutosaveProtocolEnhanced:
    """Enhanced Autosave Protocol с улучшениями от Mistral"""
    
    def __init__(self, config: SnapshotConfig):
        self.config = config
        self.snapshots: List[Snapshot] = []
        self.data_registry: Dict[str, str] = {}
        self.change_queue: deque = deque(maxlen=10000)
        self.stats = AutosaveStats()
        self.custom_rules: List[Dict] = []
        
        # Шифрование
        if config.enable_encryption:
            if not config.encryption_key:
                # Генерируем ключ если не задан
                config.encryption_key = Fernet.generate_key().decode()
            self.cipher = Fernet(config.encryption_key.encode() if isinstance(config.encryption_key, str) else config.encryption_key)
        else:
            self.cipher = None
        
        # Состояние
        self.is_running = False
        self.last_full_snapshot_time = 0
        self.last_differential_time = 0
        
        # Задачи
        self.autosave_task = None
        self.upload_task = None
        self.cleanup_task = None
        
        # Очереди
        self.snapshot_queue: asyncio.Queue = None
        self.upload_queue: asyncio.Queue = None
        
        # Сессия для HTTP
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Пул потоков для параллельной обработки
        self.executor = ThreadPoolExecutor(max_workers=config.parallel_workers)
        
        # Логирование
        self.logger = self._setup_logging()
        
        # Prometheus метрики
        if PROMETHEUS_AVAILABLE and config.enable_prometheus:
            self._setup_prometheus_metrics()
        else:
            self.snapshot_counter = None
            self.compression_gauge = None
            self.snapshot_duration = None
            self.upload_duration = None
            self.file_changes_counter = None
        
        # Создаем директорию для снапшотов
        Path(config.backup_directory).mkdir(parents=True, exist_ok=True)
    
    def _setup_prometheus_metrics(self):
        """Настройка Prometheus метрик"""
        self.snapshot_counter = Counter(
            "autosave_snapshots_total",
            "Total snapshots created",
            ["type", "status"]
        )
        self.compression_gauge = Gauge(
            "autosave_compression_ratio",
            "Compression ratio of snapshots"
        )
        self.snapshot_duration = Histogram(
            "autosave_snapshot_duration_seconds",
            "Duration of snapshot creation",
            ["type"]
        )
        self.upload_duration = Histogram(
            "autosave_upload_duration_seconds",
            "Duration of snapshot upload"
        )
        self.file_changes_counter = Counter(
            "autosave_file_changes_total",
            "Total file changes detected",
            ["operation", "data_type"]
        )
        self.snapshot_size_gauge = Gauge(
            "autosave_snapshot_size_bytes",
            "Size of snapshots in bytes",
            ["type"]
        )
    
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования с ротацией"""
        from logging.handlers import RotatingFileHandler
        
        logger = logging.getLogger('AutosaveProtocol')
        logger.setLevel(logging.INFO)
        
        # Основной лог
        handler = RotatingFileHandler(
            'autosave.log',
            maxBytes=10*1024*1024,
            backupCount=5
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Debug лог
        if self.config.backup_directory:
            debug_handler = RotatingFileHandler(
                'autosave_debug.log',
                maxBytes=50*1024*1024,
                backupCount=3
            )
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(formatter)
            logger.addHandler(debug_handler)
        
        return logger
    
    # ========== ШИФРОВАНИЕ ==========
    
    def _encrypt_data(self, data: bytes) -> bytes:
        """Шифрование данных"""
        if not self.cipher:
            return data
        
        try:
            encrypted = self.cipher.encrypt(data)
            self.logger.debug(f"Data encrypted: {len(data)} -> {len(encrypted)} bytes")
            return encrypted
        except Exception as e:
            self.logger.error(f"Encryption failed: {e}")
            return data
    
    def _decrypt_data(self, encrypted_data: bytes) -> bytes:
        """Расшифровка данных"""
        if not self.cipher:
            return encrypted_data
        
        try:
            decrypted = self.cipher.decrypt(encrypted_data)
            return decrypted
        except Exception as e:
            self.logger.error(f"Decryption failed: {e}")
            return encrypted_data
    
    # ========== ИНИЦИАЛИЗАЦИЯ ==========
    
    async def initialize(self):
        """Инициализация протокола"""
        # Создаем очереди
        self.snapshot_queue = asyncio.Queue(maxsize=100)
        self.upload_queue = asyncio.Queue(maxsize=50)
        
        # Создаем HTTP сессию
        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=300)
        
        headers = {}
        if self.config.cortex_memory_token:
            headers['Authorization'] = f'Bearer {self.config.cortex_memory_token}'
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers
        )
        
        # Загружаем существующие снапшоты
        await self._load_existing_snapshots()
        
        # Загружаем динамические интервалы
        await self._load_dynamic_intervals()
        
        self.logger.info("Autosave Protocol initialized")
    
    async def _load_dynamic_intervals(self):
        """Загрузка динамических интервалов из конфига"""
        config_path = Path(self.config.backup_directory) / "intervals.json"
        
        if config_path.exists():
            try:
                with open(config_path) as f:
                    intervals = json.load(f)
                
                self.config.incremental_interval = intervals.get("incremental", 5)
                self.config.differential_interval = intervals.get("differential", 60)
                self.config.full_interval = intervals.get("full", 360)
                
                self.logger.info(f"Loaded dynamic intervals: {intervals}")
            except Exception as e:
                self.logger.error(f"Failed to load intervals: {e}")
    
    # ========== ОСНОВНЫЕ ЦИКЛЫ ==========
    
    async def start(self):
        """Запуск автосейва"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Запускаем фоновые задачи
        self.autosave_task = asyncio.create_task(self._autosave_loop())
        self.upload_task = asyncio.create_task(self._upload_loop())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        self.logger.info("Autosave started with 5-minute intervals")
    
    async def _autosave_loop(self):
        """Основной цикл автосейва с динамическими интервалами"""
        while self.is_running:
            try:
                start_time = time.time()
                
                # Определяем тип снапшота
                snapshot_type = self._determine_snapshot_type()
                
                # Создаем снапшот
                snapshot = await self._create_snapshot(snapshot_type)
                
                if snapshot:
                    self.snapshots.append(snapshot)
                    
                    # Добавляем в очередь загрузки
                    if self.config.auto_upload:
                        await self.upload_queue.put(snapshot)
                    
                    # Обновляем статистику
                    duration = time.time() - start_time
                    self._update_stats(snapshot, duration)
                    
                    # Prometheus метрики
                    if self.snapshot_duration:
                        self.snapshot_duration.labels(type=snapshot_type.value).observe(duration)
                    
                    self.logger.info(
                        f"Snapshot created: {snapshot.id} "
                        f"({snapshot.snapshot_type.value}, "
                        f"{snapshot.compressed_size_bytes / 1024 / 1024:.1f}MB, "
                        f"encrypted={snapshot.encrypted})"
                    )
                
                # Определяем интервал до следующего снапшота
                next_interval = self._get_next_interval(snapshot_type)
                await asyncio.sleep(next_interval * 60)
                
            except Exception as e:
                self.logger.error(f"Autosave loop error: {e}")
                await asyncio.sleep(60)
    
    def _get_next_interval(self, last_type: SnapshotType) -> int:
        """Получение интервала до следующего снапшота"""
        # Применяем кастомные правила
        for rule in self.custom_rules:
            if rule["type"] == last_type:
                return rule["interval"]
        
        # Дефолтные интервалы
        return self.config.incremental_interval
    
    def _determine_snapshot_type(self) -> SnapshotType:
        """Определение типа снапшота с учётом динамических интервалов"""
        current_time = time.time()
        
        # Полный снапшот
        if (not self.snapshots or 
            current_time - self.last_full_snapshot_time > self.config.full_interval * 60):
            return SnapshotType.FULL
        
        # Дифференциальный
        if current_time - self.last_differential_time > self.config.differential_interval * 60:
            return SnapshotType.DIFFERENTIAL
        
        # Инкрементальный
        return SnapshotType.INCREMENTAL
    
    # ========== ПАРАЛЛЕЛЬНОЕ СКАНИРОВАНИЕ ==========
    
    async def _scan_data_changes_parallel(self, snapshot_type: SnapshotType) -> List[DataChange]:
        """Параллельное сканирование изменений"""
        scan_dirs = [
            './cache/incoming',
            './cache/processing',
            './cache/outgoing',
            './core/data',
            './core/models'
        ]
        
        # Создаём задачи для параллельного сканирования
        tasks = []
        for scan_dir in scan_dirs:
            if os.path.exists(scan_dir):
                task = self._scan_directory_async(scan_dir, snapshot_type)
                tasks.append(task)
        
        # Ждём завершения всех задач
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Объединяем результаты
        all_changes = []
        for result in results:
            if isinstance(result, list):
                all_changes.extend(result)
            elif isinstance(result, Exception):
                self.logger.error(f"Scan error: {result}")
        
        return all_changes
    
    async def _scan_directory_async(self, directory: str, snapshot_type: SnapshotType) -> List[DataChange]:
        """Асинхронное сканирование директории"""
        changes = []
        
        try:
            # Получаем список файлов
            files_to_process = []
            for root, dirs, files in os.walk(directory):
                for file in files:
                    file_path = os.path.join(root, file)
                    files_to_process.append(file_path)
            
            # Обрабатываем файлы параллельно пачками
            batch_size = 10
            for i in range(0, len(files_to_process), batch_size):
                batch = files_to_process[i:i+batch_size]
                
                tasks = [
                    self._process_single_file(file_path, snapshot_type)
                    for file_path in batch
                ]
                
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in batch_results:
                    if isinstance(result, DataChange):
                        changes.append(result)
                        
                        # Prometheus метрика
                        if self.file_changes_counter:
                            self.file_changes_counter.labels(
                                operation=result.operation,
                                data_type=result.data_type
                            ).inc()
        
        except Exception as e:
            self.logger.error(f"Error scanning directory {directory}: {e}")
        
        return changes
    
    async def _process_single_file(self, file_path: str, snapshot_type: SnapshotType) -> Optional[DataChange]:
        """Обработка одного файла"""
        try:
            # Вычисляем хеш
            file_hash = await self._calculate_file_hash(file_path)
            old_hash = self.data_registry.get(file_path)
            
            # Определяем операцию
            if old_hash is None:
                operation = "create"
            elif old_hash != file_hash:
                operation = "update"
            else:
                if snapshot_type == SnapshotType.INCREMENTAL:
                    return None
                operation = "unchanged"
            
            # Получаем метаданные
            stat = await asyncio.to_thread(os.stat, file_path)
            
            change = DataChange(
                path=file_path,
                operation=operation,
                old_hash=old_hash,
                new_hash=file_hash,
                timestamp=time.time(),
                size_bytes=stat.st_size,
                data_type=self._determine_data_type(file_path)
            )
            
            # Обновляем реестр
            self.data_registry[file_path] = file_hash
            
            return change
            
        except Exception as e:
            self.logger.debug(f"Cannot process file {file_path}: {e}")
            return None
    
    # ========== СОЗДАНИЕ СНАПШОТА ==========
    
    async def _create_snapshot(self, snapshot_type: SnapshotType) -> Optional[Snapshot]:
        """Создание снапшота с шифрованием"""
        snapshot_id = self._generate_snapshot_id()
        timestamp = time.time()
        
        try:
            self.logger.debug(f"Creating {snapshot_type.value} snapshot")
            
            # Параллельное сканирование изменений
            changes = await self._scan_data_changes_parallel(snapshot_type)
            
            if not changes and snapshot_type == SnapshotType.INCREMENTAL:
                self.logger.info("No changes detected, skipping incremental snapshot")
                return None
            
            # Подготовка данных
            snapshot_data = await self._prepare_snapshot_data(changes, snapshot_type)
            
            # Сжатие
            compressed_data = await self._compress_data(snapshot_data)
            
            # Шифрование
            if self.config.enable_encryption:
                final_data = self._encrypt_data(compressed_data)
                encrypted = True
            else:
                final_data = compressed_data
                encrypted = False
            
            # Сохранение в файл
            file_path = Path(self.config.backup_directory) / f"{snapshot_id}.snapshot"
            
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(final_data)
            
            # Вычисляем хеш
            data_hash = hashlib.sha256(final_data).hexdigest()
            
            # Определяем родительский снапшот
            parent_id = None
            if snapshot_type in [SnapshotType.INCREMENTAL, SnapshotType.DIFFERENTIAL]:
                parent_id = self.snapshots[-1].id if self.snapshots else None
            
            # Создаем объект снапшота
            snapshot = Snapshot(
                id=snapshot_id,
                timestamp=timestamp,
                snapshot_type=snapshot_type,
                status=SnapshotStatus.COMPLETED,
                file_path=str(file_path),
                size_bytes=len(snapshot_data),
                compressed_size_bytes=len(compressed_data),
                changes_count=len(changes),
                data_hash=data_hash,
                parent_snapshot_id=parent_id,
                encrypted=encrypted,
                metadata={
                    'compression_level': self.config.compression_level.value,
                    'changes_summary': self._summarize_changes(changes),
                    'creation_time': datetime.fromtimestamp(timestamp).isoformat(),
                    'encrypted': encrypted
                }
            )
            
            # Обновляем времена
            if snapshot_type == SnapshotType.FULL:
                self.last_full_snapshot_time = timestamp
            elif snapshot_type == SnapshotType.DIFFERENTIAL:
                self.last_differential_time = timestamp
            
            # Prometheus метрики
            if self.snapshot_counter:
                self.snapshot_counter.labels(type=snapshot_type.value, status="success").inc()
            
            if self.snapshot_size_gauge:
                self.snapshot_size_gauge.labels(type=snapshot_type.value).set(len(final_data))
            
            return snapshot
            
        except Exception as e:
            self.logger.error(f"Failed to create snapshot: {e}")
            
            if self.snapshot_counter:
                self.snapshot_counter.labels(type=snapshot_type.value, status="failed").inc()
            
            return None
    
    # ========== ЗАГРУЗКА В CORTEX-MEMORY ==========
    
    async def _upload_loop(self):
        """Цикл загрузки с поддержкой множественных хранилищ"""
        while self.is_running:
            try:
                snapshot = await self.upload_queue.get()
                
                # Основная загрузка
                primary_success = await self._upload_snapshot(snapshot)
                
                # Вторичная загрузка (если настроена)
                secondary_success = True
                if self.config.secondary_backup_url:
                    secondary_success = await self._upload_to_secondary(snapshot)
                
                if primary_success and secondary_success:
                    snapshot.status = SnapshotStatus.UPLOADED
                    self.logger.info(f"Snapshot uploaded: {snapshot.id}")
                else:
                    self.logger.error(f"Upload failed: {snapshot.id}")
                
                self.upload_queue.task_done()
                
            except Exception as e:
                self.logger.error(f"Upload loop error: {e}")
                await asyncio.sleep(30)
    
    async def _upload_to_secondary(self, snapshot: Snapshot) -> bool:
        """Загрузка во вторичное хранилище"""
        if not self.config.secondary_backup_url:
            return True
        
        try:
            async with aiofiles.open(snapshot.file_path, 'rb') as f:
                data = await f.read()
            
            # Простая загрузка через POST
            async with self.session.post(
                self.config.secondary_backup_url,
                data=data,
                headers={'Content-Type': 'application/octet-stream'}
            ) as response:
                return response.status == 200
                
        except Exception as e:
            self.logger.error(f"Secondary upload failed: {e}")
            return False
    
    # ========== ВОССТАНОВЛЕНИЕ С ПРОВЕРКОЙ ==========
    
    async def restore_from_snapshot(self, snapshot_id: str, target_directory: str = "./restored") -> bool:
        """Восстановление с проверкой целостности"""
        try:
            snapshot = next((s for s in self.snapshots if s.id == snapshot_id), None)
            
            if not snapshot:
                self.logger.error(f"Snapshot not found: {snapshot_id}")
                return False
            
            # Создаем директорию
            Path(target_directory).mkdir(parents=True, exist_ok=True)
            
            # Читаем снапшот
            async with aiofiles.open(snapshot.file_path, 'rb') as f:
                data = await f.read()
            
            # Расшифровываем
            if snapshot.encrypted:
                data = self._decrypt_data(data)
            
            # Распаковываем
            try:
                data = gzip.decompress(data)
            except:
                pass  # Не сжато
            
            # Парсим JSON
            snapshot_data = json.loads(data.decode('utf-8'))
            
            # Восстанавливаем файлы
            restored_count = 0
            integrity_failed = []
            
            for change in snapshot_data['changes']:
                if 'content' in change and change['operation'] in ['create', 'update']:
                    try:
                        file_path = Path(target_directory) / Path(change['path']).relative_to('.')
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Восстанавливаем файл
                        file_content = bytes.fromhex(change['content'])
                        
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(file_content)
                        
                        # Проверяем целостность
                        if self.config.verify_integrity:
                            actual_hash = await self._calculate_file_hash(str(file_path))
                            if actual_hash != change['new_hash']:
                                integrity_failed.append(str(file_path))
                                self.stats.integrity_checks_failed += 1
                            else:
                                self.stats.integrity_checks_passed += 1
                        
                        restored_count += 1
                        
                    except Exception as e:
                        self.logger.error(f"Failed to restore {change['path']}: {e}")
            
            if integrity_failed:
                self.logger.warning(f"Integrity check failed for {len(integrity_failed)} files")
            
            self.logger.info(f"Restored {restored_count} files from snapshot {snapshot_id}")
            return len(integrity_failed) == 0
            
        except Exception as e:
            self.logger.error(f"Restore failed: {e}")
            return False
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========
    
    async def _calculate_file_hash(self, file_path: str) -> str:
        """Асинхронное вычисление хеша файла"""
        hash_obj = hashlib.sha256()
        
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                while chunk := await f.read(8192):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception:
            return ""
    
    def _determine_data_type(self, file_path: str) -> str:
        """Определение типа данных"""
        ext = Path(file_path).suffix.lower()
        
        type_mapping = {
            '.json': 'json_data',
            '.pkl': 'pickle_data',
            '.csv': 'csv_data',
            '.txt': 'text_data',
            '.log': 'log_data',
            '.cache': 'cache_data',
            '.model': 'model_data',
            '.weights': 'weights_data'
        }
        
        return type_mapping.get(ext, 'unknown_data')
    
    async def _compress_data(self, data: bytes) -> bytes:
        """Асинхронное сжатие данных"""
        if self.config.compression_level == CompressionLevel.NONE:
            return data
        
        try:
            # Сжимаем в отдельном потоке
            compressed = await asyncio.to_thread(
                gzip.compress,
                data,
                compresslevel=self.config.compression_level.value
            )
            
            # Проверяем эффективность
            compression_ratio = len(compressed) / len(data)
            
            if self.compression_gauge:
                self.compression_gauge.set(compression_ratio)
            
            if compression_ratio > 0.9:
                self.logger.debug(f"Poor compression: {compression_ratio:.2f}")
                return data
            
            return compressed
            
        except Exception as e:
            self.logger.error(f"Compression failed: {e}")
            return data
    
    def _summarize_changes(self, changes: List[DataChange]) -> Dict:
        """Сводка изменений"""
        summary = {
            'total_changes': len(changes),
            'operations': defaultdict(int),
            'data_types': defaultdict(int),
            'total_size_bytes': 0
        }
        
        for change in changes:
            summary['operations'][change.operation] += 1
            summary['data_types'][change.data_type] += 1
            summary['total_size_bytes'] += change.size_bytes
        
        return dict(summary)
    
    async def _prepare_snapshot_data(self, changes: List[DataChange], snapshot_type: SnapshotType) -> bytes:
        """Подготовка данных снапшота"""
        snapshot_data = {
            'version': '1.0',
            'timestamp': time.time(),
            'snapshot_type': snapshot_type.value,
            'changes': [],
            'metadata': {
                'total_changes': len(changes),
                'data_registry_size': len(self.data_registry)
            }
        }
        
        # Добавляем изменения
        for change in changes:
            change_data = asdict(change)
            
            # Для создания и обновления добавляем содержимое
            if change.operation in ['create', 'update'] and change.size_bytes < 10 * 1024 * 1024:
                try:
                    async with aiofiles.open(change.path, 'rb') as f:
                        content = await f.read()
                        change_data['content'] = content.hex()
                except Exception:
                    pass
            
            snapshot_data['changes'].append(change_data)
        
        # Для полного снапшота добавляем реестр
        if snapshot_type == SnapshotType.FULL:
            snapshot_data['data_registry'] = self.data_registry.copy()
        
        return json.dumps(snapshot_data).encode('utf-8')
    
    def _generate_snapshot_id(self) -> str:
        """Генерация ID снапшота"""
        timestamp = int(time.time() * 1000)
        random_part = hashlib.md5(str(timestamp).encode()).hexdigest()[:8]
        return f"snapshot_{timestamp}_{random_part}"
    
    def _update_stats(self, snapshot: Snapshot, duration: float):
        """Обновление статистики"""
        self.stats.total_snapshots += 1
        self.stats.last_snapshot_time = time.time()
        
        if snapshot.status == SnapshotStatus.COMPLETED:
            self.stats.successful_snapshots += 1
            self.stats.total_data_saved_gb += snapshot.compressed_size_bytes / (1024**3)
            
            if snapshot.encrypted:
                self.stats.encrypted_snapshots += 1
            
            # Среднее время
            total_time = self.stats.average_snapshot_time * (self.stats.successful_snapshots - 1)
            self.stats.average_snapshot_time = (total_time + duration) / self.stats.successful_snapshots
            
            # Коэффициент сжатия
            if snapshot.size_bytes > 0:
                compression_ratio = snapshot.compressed_size_bytes / snapshot.size_bytes
                total_ratio = self.stats.compression_ratio * (self.stats.successful_snapshots - 1)
                self.stats.compression_ratio = (total_ratio + compression_ratio) / self.stats.successful_snapshots
        else:
            self.stats.failed_snapshots += 1
    
    # Остальные методы без изменений...
    
    async def _upload_snapshot(self, snapshot: Snapshot) -> bool:
        """Загрузка снапшота в cortex-memory"""
        if not self.session:
            return False
        
        try:
            upload_start = time.time()
            
            async with aiofiles.open(snapshot.file_path, 'rb') as f:
                snapshot_data = await f.read()
            
            metadata = {
                'snapshot_id': snapshot.id,
                'timestamp': snapshot.timestamp,
                'snapshot_type': snapshot.snapshot_type.value,
                'size_bytes': snapshot.size_bytes,
                'compressed_size_bytes': snapshot.compressed_size_bytes,
                'changes_count': snapshot.changes_count,
                'data_hash': snapshot.data_hash,
                'parent_snapshot_id': snapshot.parent_snapshot_id,
                'encrypted': snapshot.encrypted,
                'metadata': snapshot.metadata
            }
            
            data = aiohttp.FormData()
            data.add_field('metadata', json.dumps(metadata), content_type='application/json')
            data.add_field('snapshot', snapshot_data, 
                         filename=f"{snapshot.id}.snapshot",
                         content_type='application/octet-stream')
            
            url = f"{self.config.cortex_memory_url}/snapshots/upload"
            
            async with self.session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    snapshot.upload_url = result.get('url')
                    
                    upload_time = time.time() - upload_start
                    self.stats.total_upload_time += upload_time
                    
                    if self.upload_duration:
                        self.upload_duration.observe(upload_time)
                    
                    return True
                    
        except Exception as e:
            self.logger.error(f"Upload error: {e}")
            
        return False
    
    async def _cleanup_loop(self):
        """Цикл очистки старых снапшотов"""
        while self.is_running:
            try:
                await self._cleanup_old_snapshots()
                await asyncio.sleep(3600)
            except Exception as e:
                self.logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(1800)
    
    async def _cleanup_old_snapshots(self):
        """Очистка старых снапшотов"""
        self.snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        
        if len(self.snapshots) > self.config.max_snapshots_local:
            to_remove = self.snapshots[self.config.max_snapshots_local:]
            
            for snapshot in to_remove:
                try:
                    if os.path.exists(snapshot.file_path):
                        os.remove(snapshot.file_path)
                    snapshot.status = SnapshotStatus.ARCHIVED
                except Exception:
                    pass
            
            self.snapshots = self.snapshots[:self.config.max_snapshots_local]
    
    async def _load_existing_snapshots(self):
        """Загрузка существующих снапшотов"""
        try:
            if os.path.exists(self.config.backup_directory):
                for file in os.listdir(self.config.backup_directory):
                    if file.endswith('.snapshot'):
                        file_path = os.path.join(self.config.backup_directory, file)
                        snapshot_id = file.replace('.snapshot', '')
                        
                        stat = os.stat(file_path)
                        
                        snapshot = Snapshot(
                            id=snapshot_id,
                            timestamp=stat.st_mtime,
                            snapshot_type=SnapshotType.FULL,
                            status=SnapshotStatus.COMPLETED,
                            file_path=file_path,
                            size_bytes=0,
                            compressed_size_bytes=stat.st_size,
                            changes_count=0,
                            data_hash="",
                            metadata={}
                        )
                        
                        self.snapshots.append(snapshot)
            
            self.logger.info(f"Loaded {len(self.snapshots)} existing snapshots")
            
        except Exception as e:
            self.logger.error(f"Failed to load snapshots: {e}")
    
    def register_custom_rule(self, pattern: str, snapshot_type: SnapshotType, interval: int):
        """Регистрация кастомного правила"""
        self.custom_rules.append({
            "pattern": pattern,
            "type": snapshot_type,
            "interval": interval
        })
        
        self.logger.info(f"Registered custom rule: {pattern} -> {snapshot_type.value} every {interval} min")
    
    async def create_emergency_snapshot(self, reason: str = "") -> Optional[Snapshot]:
        """Создание экстренного снапшота"""
        self.logger.warning(f"Creating emergency snapshot: {reason}")
        
        snapshot = await self._create_snapshot(SnapshotType.EMERGENCY)
        
        if snapshot:
            snapshot.metadata['emergency_reason'] = reason
            snapshot.metadata['priority'] = 'high'
            
            if self.config.auto_upload:
                success = await self._upload_snapshot(snapshot)
                if success:
                    snapshot.status = SnapshotStatus.UPLOADED
            
            self.snapshots.append(snapshot)
            
        return snapshot
    
    def get_stats(self) -> Dict:
        """Получение статистики"""
        return {
            **asdict(self.stats),
            'is_running': self.is_running,
            'snapshots_count': len(self.snapshots),
            'latest_snapshot': self.snapshots[-1].id if self.snapshots else None,
            'data_registry_size': len(self.data_registry),
            'custom_rules_count': len(self.custom_rules),
            'encryption_enabled': self.config.enable_encryption
        }
    
    async def stop(self):
        """Остановка автосейва"""
        self.is_running = False
        
        if self.upload_queue:
            await self.upload_queue.join()
        
        if self.session:
            await self.session.close()
        
        self.executor.shutdown(wait=True)
        
        self.logger.info("Autosave stopped")


# Пример использования остаётся без изменений
