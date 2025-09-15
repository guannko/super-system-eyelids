"""
CORTEX v3.0 - Emergency Cleanup Protocol ENHANCED
С критическими улучшениями от Mistral - резервное копирование, асинхронность, Prometheus
"""

import asyncio
import time
import psutil
import shutil
import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set, AsyncGenerator
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor
import aiofiles
import aiofiles.os
import subprocess

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

class EmergencyLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    CATASTROPHIC = 5

class CleanupAction(Enum):
    SELECTIVE = "selective"
    AGGRESSIVE = "aggressive"
    NUCLEAR = "nuclear"
    SMART = "smart"

class DataPriority(Enum):
    CRITICAL = 1      # Никогда не удаляем
    HIGH = 2          # Удаляем только при CATASTROPHIC
    MEDIUM = 3        # Удаляем при HIGH+
    LOW = 4           # Удаляем при MEDIUM+
    TEMP = 5          # Удаляем при LOW+
    TRASH = 6         # Удаляем всегда

@dataclass
class EmergencyTrigger:
    name: str
    condition: str
    threshold: float
    level: EmergencyLevel
    action: CleanupAction
    enabled: bool = True
    last_triggered: Optional[float] = None
    trigger_count: int = 0
    cooldown_seconds: int = 60

@dataclass
class CleanupTarget:
    path: str
    priority: DataPriority
    size_mb: float
    last_access: float
    file_type: str
    is_directory: bool = False
    protected: bool = False
    backup_exists: bool = False
    checksum: Optional[str] = None

@dataclass
class CleanupResult:
    success: bool
    files_removed: int
    directories_removed: int
    space_freed_mb: float
    duration_seconds: float
    errors: List[str]
    level: EmergencyLevel
    action: CleanupAction
    timestamp: float
    files_backed_up: int = 0
    backup_size_mb: float = 0

class EmergencyCleanupProtocolEnhanced:
    """Enhanced Emergency Cleanup Protocol с улучшениями от Mistral"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.cache_dirs = config.get('cache_directories', [])
        self.temp_dirs = config.get('temp_directories', [])
        self.protected_paths = set(config.get('protected_paths', []))
        self.backup_directory = config.get('backup_directory', './backup/emergency')
        self.max_workers = config.get('max_workers', 4)
        self.enable_backup = config.get('enable_backup', True)
        self.enable_prometheus = config.get('enable_prometheus', True)
        
        # Создаём директорию для резервных копий
        Path(self.backup_directory).mkdir(parents=True, exist_ok=True)
        
        # Триггеры экстренной очистки (можно загрузить из конфига)
        self.triggers = self._initialize_triggers()
        
        # Статистика
        self.stats = {
            'total_cleanups': 0,
            'total_space_freed_gb': 0,
            'last_cleanup_time': 0,
            'emergency_triggers': 0,
            'files_removed_total': 0,
            'files_backed_up_total': 0,
            'average_cleanup_time': 0,
            'filesystem_checks': 0,
            'filesystem_errors': 0
        }
        
        # Мониторинг
        self.monitoring_active = False
        self.monitoring_task = None
        
        # Логирование
        self.logger = self._setup_logging()
        
        # Prometheus метрики
        if PROMETHEUS_AVAILABLE and self.enable_prometheus:
            self._setup_prometheus_metrics()
        else:
            self.cleanup_counter = None
            self.space_freed_gauge = None
            self.cleanup_duration_histogram = None
            self.files_removed_counter = None
            self.backup_counter = None
    
    def _setup_prometheus_metrics(self):
        """Настройка Prometheus метрик"""
        self.cleanup_counter = Counter(
            "emergency_cleanup_total",
            "Total emergency cleanups",
            ["level", "action", "result"]
        )
        self.space_freed_gauge = Gauge(
            "emergency_cleanup_space_freed_gb",
            "Space freed by emergency cleanup (GB)"
        )
        self.cleanup_duration_histogram = Histogram(
            "emergency_cleanup_duration_seconds",
            "Duration of emergency cleanup operations",
            ["level", "action"]
        )
        self.files_removed_counter = Counter(
            "emergency_cleanup_files_removed",
            "Files removed by emergency cleanup",
            ["priority"]
        )
        self.backup_counter = Counter(
            "emergency_cleanup_backups_created",
            "Backup files created"
        )
        self.trigger_gauge = Gauge(
            "emergency_cleanup_trigger_count",
            "Number of trigger activations",
            ["trigger_name"]
        )
    
    def _initialize_triggers(self) -> List[EmergencyTrigger]:
        """Инициализация триггеров (можно загрузить из конфига)"""
        
        # Проверяем наличие файла конфигурации триггеров
        triggers_config_path = self.config.get('triggers_config_path', 'triggers.json')
        if Path(triggers_config_path).exists():
            return self._load_triggers_from_config(triggers_config_path)
        
        # Дефолтные триггеры
        return [
            EmergencyTrigger(
                name="disk_space_critical",
                condition="disk_usage > 95",
                threshold=95.0,
                level=EmergencyLevel.CATASTROPHIC,
                action=CleanupAction.NUCLEAR,
                cooldown_seconds=300
            ),
            EmergencyTrigger(
                name="disk_space_high",
                condition="disk_usage > 90",
                threshold=90.0,
                level=EmergencyLevel.CRITICAL,
                action=CleanupAction.AGGRESSIVE,
                cooldown_seconds=180
            ),
            EmergencyTrigger(
                name="disk_space_medium",
                condition="disk_usage > 85",
                threshold=85.0,
                level=EmergencyLevel.HIGH,
                action=CleanupAction.SMART,
                cooldown_seconds=120
            ),
            EmergencyTrigger(
                name="memory_critical",
                condition="memory_usage > 95",
                threshold=95.0,
                level=EmergencyLevel.CRITICAL,
                action=CleanupAction.AGGRESSIVE,
                cooldown_seconds=60
            ),
            EmergencyTrigger(
                name="cache_size_critical",
                condition="cache_size_gb > 50",
                threshold=50.0,
                level=EmergencyLevel.CRITICAL,
                action=CleanupAction.AGGRESSIVE,
                cooldown_seconds=300
            ),
            EmergencyTrigger(
                name="old_files_cleanup",
                condition="days_since_access > 30",
                threshold=30.0,
                level=EmergencyLevel.MEDIUM,
                action=CleanupAction.SELECTIVE,
                cooldown_seconds=3600
            )
        ]
    
    def _load_triggers_from_config(self, config_path: str) -> List[EmergencyTrigger]:
        """Загрузка триггеров из конфигурационного файла"""
        try:
            with open(config_path) as f:
                config = json.load(f)
            
            triggers = []
            for trigger_dict in config.get("triggers", []):
                trigger_dict["level"] = EmergencyLevel[trigger_dict["level"]]
                trigger_dict["action"] = CleanupAction[trigger_dict["action"]]
                triggers.append(EmergencyTrigger(**trigger_dict))
            
            self.logger.info(f"Loaded {len(triggers)} triggers from {config_path}")
            return triggers
            
        except Exception as e:
            self.logger.error(f"Failed to load triggers from config: {e}")
            return self._initialize_triggers()  # Возвращаем дефолтные
    
    def update_triggers_from_config(self, config_path: str) -> bool:
        """Динамическое обновление триггеров"""
        try:
            new_triggers = self._load_triggers_from_config(config_path)
            self.triggers = new_triggers
            self.logger.info("Triggers updated successfully")
            return True
        except Exception as e:
            self.logger.error(f"Failed to update triggers: {e}")
            return False
    
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования с ротацией"""
        from logging.handlers import RotatingFileHandler
        
        logger = logging.getLogger('EmergencyCleanup')
        logger.setLevel(logging.INFO)
        
        # Файловый хендлер с ротацией
        handler = RotatingFileHandler(
            'emergency_cleanup.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Debug лог для детальной информации
        if self.config.get('debug', False):
            debug_handler = RotatingFileHandler(
                'emergency_cleanup_debug.log',
                maxBytes=50*1024*1024,  # 50MB
                backupCount=3
            )
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(formatter)
            logger.addHandler(debug_handler)
            logger.setLevel(logging.DEBUG)
        
        return logger
    
    # ========== РЕЗЕРВНОЕ КОПИРОВАНИЕ ==========
    
    async def _backup_file(self, file_path: str) -> bool:
        """Асинхронное резервное копирование файла"""
        if not self.enable_backup:
            return True
        
        backup_subdir = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(self.backup_directory) / backup_subdir
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            file_name = Path(file_path).name
            # Добавляем хеш для уникальности
            file_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
            backup_path = backup_dir / f"{file_hash}_{file_name}"
            
            # Асинхронное копирование
            async with aiofiles.open(file_path, 'rb') as src:
                async with aiofiles.open(backup_path, 'wb') as dst:
                    await dst.write(await src.read())
            
            self.logger.debug(f"Backed up {file_path} to {backup_path}")
            
            if self.backup_counter:
                self.backup_counter.inc()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Backup failed for {file_path}: {e}")
            return False
    
    # ========== ПРОВЕРКА ФАЙЛОВОЙ СИСТЕМЫ ==========
    
    async def _check_filesystem_integrity(self) -> bool:
        """Асинхронная проверка целостности файловой системы"""
        if not self.config.get('check_filesystem', False):
            return True
        
        try:
            # Для Linux систем
            if os.name == 'posix':
                result = await asyncio.create_subprocess_exec(
                    'df', '-h',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await result.communicate()
                
                if result.returncode == 0:
                    self.stats['filesystem_checks'] += 1
                    return True
                else:
                    self.stats['filesystem_errors'] += 1
                    self.logger.error(f"Filesystem check failed: {stderr.decode()}")
                    return False
            
            return True  # Для других ОС пропускаем проверку
            
        except Exception as e:
            self.logger.error(f"Filesystem integrity check failed: {e}")
            self.stats['filesystem_errors'] += 1
            return False
    
    # ========== АСИНХРОННОЕ СКАНИРОВАНИЕ ==========
    
    async def _async_scan_directory(self, directory: str) -> AsyncGenerator[CleanupTarget, None]:
        """Асинхронное потоковое сканирование директории"""
        try:
            for root, dirs, files in os.walk(directory):
                # Проверяем защищенные пути
                if any(protected in root for protected in self.protected_paths):
                    continue
                
                # Обрабатываем файлы
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    try:
                        # Асинхронное получение статистики
                        stat = await asyncio.to_thread(os.stat, file_path)
                        size_mb = stat.st_size / (1024 * 1024)
                        last_access = stat.st_atime
                        
                        # Определяем приоритет
                        priority = self._determine_file_priority(file_path, stat)
                        
                        # Вычисляем чексумму для важных файлов
                        checksum = None
                        if priority.value <= DataPriority.HIGH.value:
                            checksum = await self._calculate_file_checksum(file_path)
                        
                        yield CleanupTarget(
                            path=file_path,
                            priority=priority,
                            size_mb=size_mb,
                            last_access=last_access,
                            file_type=self._get_file_type(file_path),
                            is_directory=False,
                            protected=self._is_protected(file_path),
                            checksum=checksum
                        )
                        
                    except Exception as e:
                        self.logger.debug(f"Failed to scan file {file_path}: {e}")
                
                # Обрабатываем пустые директории
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    
                    if await self._is_empty_directory_async(dir_path):
                        yield CleanupTarget(
                            path=dir_path,
                            priority=DataPriority.TEMP,
                            size_mb=0,
                            last_access=time.time(),
                            file_type="directory",
                            is_directory=True,
                            protected=self._is_protected(dir_path)
                        )
                        
        except Exception as e:
            self.logger.error(f"Error scanning {directory}: {e}")
    
    async def _calculate_file_checksum(self, file_path: str) -> str:
        """Асинхронное вычисление контрольной суммы файла"""
        try:
            hash_md5 = hashlib.md5()
            async with aiofiles.open(file_path, 'rb') as f:
                while chunk := await f.read(8192):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return ""
    
    async def _is_empty_directory_async(self, directory: str) -> bool:
        """Асинхронная проверка пустоты директории"""
        try:
            entries = await asyncio.to_thread(os.listdir, directory)
            return len(entries) == 0
        except Exception:
            return False
    
    # ========== МОНИТОРИНГ ==========
    
    async def start_monitoring(self):
        """Запуск асинхронного мониторинга"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        self.logger.info("Emergency monitoring started")
    
    async def _monitoring_loop(self):
        """Асинхронный цикл мониторинга"""
        while self.monitoring_active:
            try:
                # Проверяем все триггеры
                for trigger in self.triggers:
                    if trigger.enabled and await self._check_trigger_async(trigger):
                        await self._handle_emergency(trigger)
                
                await asyncio.sleep(10)  # Проверка каждые 10 секунд
                
            except Exception as e:
                self.logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(30)
    
    async def _check_trigger_async(self, trigger: EmergencyTrigger) -> bool:
        """Асинхронная проверка условия триггера"""
        try:
            current_time = time.time()
            
            # Проверяем cooldown
            if trigger.last_triggered:
                if current_time - trigger.last_triggered < trigger.cooldown_seconds:
                    return False
            
            # Получаем метрики системы асинхронно
            metrics = await self._get_system_metrics_async()
            
            # Проверяем условие
            if "disk_usage" in trigger.condition:
                return metrics['disk_usage'] > trigger.threshold
            elif "memory_usage" in trigger.condition:
                return metrics['memory_usage'] > trigger.threshold
            elif "cache_size_gb" in trigger.condition:
                return metrics['cache_size_gb'] > trigger.threshold
            elif "days_since_access" in trigger.condition:
                return metrics['days_since_access'] > trigger.threshold
            
            return False
            
        except Exception as e:
            self.logger.error(f"Trigger check error for {trigger.name}: {e}")
            return False
    
    async def _get_system_metrics_async(self) -> Dict:
        """Асинхронное получение метрик системы"""
        metrics = {}
        
        # Параллельное получение всех метрик
        tasks = [
            asyncio.to_thread(psutil.disk_usage, '/'),
            asyncio.to_thread(psutil.virtual_memory),
            self._calculate_cache_size_async(),
            self._count_cache_files_async(),
            self._get_oldest_file_age_async()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        metrics['disk_usage'] = results[0].percent if not isinstance(results[0], Exception) else 0
        metrics['memory_usage'] = results[1].percent if not isinstance(results[1], Exception) else 0
        metrics['cache_size_gb'] = results[2] / (1024**3) if not isinstance(results[2], Exception) else 0
        metrics['file_count'] = results[3] if not isinstance(results[3], Exception) else 0
        metrics['days_since_access'] = results[4] if not isinstance(results[4], Exception) else 0
        metrics['timestamp'] = time.time()
        
        return metrics
    
    async def _calculate_cache_size_async(self) -> int:
        """Асинхронное вычисление размера кэша"""
        total_size = 0
        
        for cache_dir in self.cache_dirs:
            if os.path.exists(cache_dir):
                for root, dirs, files in os.walk(cache_dir):
                    for file in files:
                        try:
                            file_path = os.path.join(root, file)
                            stat = await asyncio.to_thread(os.stat, file_path)
                            total_size += stat.st_size
                        except Exception:
                            continue
        
        return total_size
    
    async def _count_cache_files_async(self) -> int:
        """Асинхронный подсчёт файлов"""
        total_files = 0
        
        for cache_dir in self.cache_dirs:
            if os.path.exists(cache_dir):
                for root, dirs, files in os.walk(cache_dir):
                    total_files += len(files)
        
        return total_files
    
    async def _get_oldest_file_age_async(self) -> float:
        """Асинхронное получение возраста старейшего файла"""
        oldest_time = time.time()
        
        for cache_dir in self.cache_dirs:
            if os.path.exists(cache_dir):
                for root, dirs, files in os.walk(cache_dir):
                    for file in files[:10]:  # Проверяем только первые 10 файлов для скорости
                        try:
                            file_path = os.path.join(root, file)
                            stat = await asyncio.to_thread(os.stat, file_path)
                            oldest_time = min(oldest_time, stat.st_atime)
                        except Exception:
                            continue
        
        return (time.time() - oldest_time) / 86400
    
    # ========== ОБРАБОТКА ЭКСТРЕННЫХ СИТУАЦИЙ ==========
    
    async def _handle_emergency(self, trigger: EmergencyTrigger):
        """Обработка экстренной ситуации"""
        trigger.last_triggered = time.time()
        trigger.trigger_count += 1
        self.stats['emergency_triggers'] += 1
        
        if self.trigger_gauge:
            self.trigger_gauge.labels(trigger_name=trigger.name).inc()
        
        self.logger.warning(
            f"Emergency trigger activated: {trigger.name} "
            f"(Level: {trigger.level.name}, Action: {trigger.action.value})"
        )
        
        # Выполняем очистку
        result = await self.execute_cleanup(
            level=trigger.level,
            action=trigger.action,
            reason=f"Emergency trigger: {trigger.name}"
        )
        
        if result.success:
            self.logger.info(
                f"Emergency cleanup completed: "
                f"{result.space_freed_mb:.1f}MB freed, "
                f"{result.files_removed} files removed, "
                f"{result.files_backed_up} files backed up"
            )
        else:
            self.logger.error(f"Emergency cleanup failed: {result.errors}")
    
    async def execute_cleanup(self, level: EmergencyLevel, 
                             action: CleanupAction, 
                             reason: str = "") -> CleanupResult:
        """Выполнение очистки с резервным копированием"""
        start_time = time.time()
        
        self.logger.info(
            f"Starting cleanup: Level={level.name}, "
            f"Action={action.value}, Reason={reason}"
        )
        
        try:
            # Проверяем файловую систему перед очисткой
            if not await self._check_filesystem_integrity():
                self.logger.warning("Filesystem integrity check failed, proceeding with caution")
            
            # Асинхронное сканирование целей
            targets = []
            async for target in self._scan_cleanup_targets_async(level, action):
                targets.append(target)
            
            # Фильтруем по приоритетам
            filtered_targets = self._filter_targets_by_priority(targets, level)
            
            # Выполняем очистку с резервным копированием
            result = await self._perform_cleanup_async(filtered_targets, action, level)
            
            # Проверяем файловую систему после очистки
            if not await self._check_filesystem_integrity():
                result.errors.append("Post-cleanup filesystem check failed")
            
            # Обновляем статистику
            self._update_stats(result)
            
            result.level = level
            result.action = action
            result.timestamp = start_time
            result.duration_seconds = time.time() - start_time
            
            # Prometheus метрики
            if self.cleanup_duration_histogram:
                self.cleanup_duration_histogram.labels(
                    level=level.name,
                    action=action.value
                ).observe(result.duration_seconds)
            
            return result
            
        except Exception as e:
            error_msg = f"Cleanup execution failed: {str(e)}"
            self.logger.error(error_msg)
            
            return CleanupResult(
                success=False,
                files_removed=0,
                directories_removed=0,
                space_freed_mb=0,
                duration_seconds=time.time() - start_time,
                errors=[error_msg],
                level=level,
                action=action,
                timestamp=start_time
            )
    
    async def _scan_cleanup_targets_async(self, level: EmergencyLevel, 
                                         action: CleanupAction) -> AsyncGenerator[CleanupTarget, None]:
        """Асинхронное потоковое сканирование целей"""
        scan_dirs = self.cache_dirs.copy()
        
        if action in [CleanupAction.AGGRESSIVE, CleanupAction.NUCLEAR]:
            scan_dirs.extend(self.temp_dirs)
        
        for directory in scan_dirs:
            if os.path.exists(directory):
                async for target in self._async_scan_directory(directory):
                    yield target
    
    async def _perform_cleanup_async(self, targets: List[CleanupTarget], 
                                    action: CleanupAction,
                                    level: EmergencyLevel) -> CleanupResult:
        """Асинхронное выполнение очистки с резервным копированием"""
        files_removed = 0
        directories_removed = 0
        space_freed_mb = 0
        files_backed_up = 0
        backup_size_mb = 0
        errors = []
        
        # Ограничиваем количество файлов
        max_files = self._get_max_files_for_action(action)
        targets = targets[:max_files]
        
        # Создаём задачи для параллельной обработки
        tasks = []
        for target in targets:
            # Резервное копирование важных файлов
            if target.priority.value <= DataPriority.HIGH.value and not target.is_directory:
                task = self._backup_and_remove(target)
            else:
                task = self._remove_target_async(target)
            tasks.append(task)
        
        # Выполняем задачи пачками для контроля нагрузки
        batch_size = self.max_workers
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i:i+batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    errors.append(str(result))
                elif isinstance(result, dict):
                    if result['success']:
                        if result['is_directory']:
                            directories_removed += 1
                        else:
                            files_removed += 1
                        space_freed_mb += result['size_mb']
                        
                        if result.get('backed_up'):
                            files_backed_up += 1
                            backup_size_mb += result['size_mb']
                    else:
                        errors.append(result['error'])
        
        success = len(errors) < len(targets) * 0.1  # Успех если <10% ошибок
        
        return CleanupResult(
            success=success,
            files_removed=files_removed,
            directories_removed=directories_removed,
            space_freed_mb=space_freed_mb,
            duration_seconds=0,
            errors=errors[:10],
            level=level,
            action=action,
            timestamp=time.time(),
            files_backed_up=files_backed_up,
            backup_size_mb=backup_size_mb
        )
    
    async def _backup_and_remove(self, target: CleanupTarget) -> Dict:
        """Резервное копирование и удаление файла"""
        try:
            # Сначала делаем резервную копию
            backed_up = await self._backup_file(target.path)
            
            if not backed_up and target.priority == DataPriority.HIGH:
                # Не удаляем важные файлы без резервной копии
                return {
                    'success': False,
                    'error': f"Failed to backup critical file {target.path}",
                    'is_directory': False,
                    'size_mb': 0
                }
            
            # Удаляем файл
            await aiofiles.os.remove(target.path)
            
            self.logger.debug(f"Removed {target.path} (backed up: {backed_up})")
            
            if self.files_removed_counter:
                self.files_removed_counter.labels(priority=target.priority.name).inc()
            
            return {
                'success': True,
                'is_directory': False,
                'size_mb': target.size_mb,
                'backed_up': backed_up
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to remove {target.path}: {str(e)}",
                'is_directory': False,
                'size_mb': 0
            }
    
    async def _remove_target_async(self, target: CleanupTarget) -> Dict:
        """Асинхронное удаление цели"""
        try:
            if target.is_directory:
                await asyncio.to_thread(shutil.rmtree, target.path)
                return {
                    'success': True,
                    'is_directory': True,
                    'size_mb': 0
                }
            else:
                await aiofiles.os.remove(target.path)
                
                if self.files_removed_counter:
                    self.files_removed_counter.labels(priority=target.priority.name).inc()
                
                return {
                    'success': True,
                    'is_directory': False,
                    'size_mb': target.size_mb
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to remove {target.path}: {str(e)}",
                'is_directory': target.is_directory,
                'size_mb': 0
            }
    
    # Остальные методы остаются без изменений...
    
    def _determine_file_priority(self, file_path: str, stat) -> DataPriority:
        """Определение приоритета файла"""
        file_name = Path(file_path).name.lower()
        file_ext = Path(file_path).suffix.lower()
        
        # Критически важные файлы
        if any(critical in file_name for critical in ['config', 'settings', 'database', 'credentials']):
            return DataPriority.CRITICAL
        
        # Системные файлы
        if file_ext in ['.sys', '.dll', '.exe', '.so']:
            return DataPriority.HIGH
        
        # Логи и временные файлы
        if file_ext in ['.log', '.tmp', '.temp', '.cache']:
            return DataPriority.TEMP
        
        # Старые файлы
        days_old = (time.time() - stat.st_atime) / 86400
        if days_old > 30:
            return DataPriority.LOW
        elif days_old > 7:
            return DataPriority.MEDIUM
        
        return DataPriority.MEDIUM
    
    def _get_file_type(self, file_path: str) -> str:
        """Определение типа файла"""
        ext = Path(file_path).suffix.lower()
        
        type_mapping = {
            '.log': 'log',
            '.tmp': 'temp',
            '.cache': 'cache',
            '.json': 'data',
            '.py': 'code',
            '.js': 'code',
            '.jpg': 'image',
            '.png': 'image',
            '.zip': 'archive'
        }
        
        return type_mapping.get(ext, 'unknown')
    
    def _is_protected(self, path: str) -> bool:
        """Проверка защищенности пути"""
        return any(protected in path for protected in self.protected_paths)
    
    def _filter_targets_by_priority(self, targets: List[CleanupTarget], 
                                   level: EmergencyLevel) -> List[CleanupTarget]:
        """Фильтрация целей по приоритету"""
        filtered = []
        
        for target in targets:
            if target.protected:
                continue
            
            if target.priority == DataPriority.CRITICAL:
                continue
            
            # Фильтрация по уровню
            if level == EmergencyLevel.LOW and target.priority in [DataPriority.TEMP, DataPriority.TRASH]:
                filtered.append(target)
            elif level == EmergencyLevel.MEDIUM and target.priority.value >= DataPriority.LOW.value:
                filtered.append(target)
            elif level == EmergencyLevel.HIGH and target.priority.value >= DataPriority.MEDIUM.value:
                filtered.append(target)
            elif level == EmergencyLevel.CRITICAL and target.priority != DataPriority.CRITICAL:
                filtered.append(target)
            elif level == EmergencyLevel.CATASTROPHIC:
                filtered.append(target)
        
        # Сортируем: сначала менее важные
        filtered.sort(key=lambda x: (x.priority.value, -x.size_mb))
        
        return filtered
    
    def _get_max_files_for_action(self, action: CleanupAction) -> int:
        """Максимальное количество файлов для действия"""
        mapping = {
            CleanupAction.SELECTIVE: 1000,
            CleanupAction.SMART: 5000,
            CleanupAction.AGGRESSIVE: 20000,
            CleanupAction.NUCLEAR: 100000
        }
        return mapping.get(action, 1000)
    
    def _update_stats(self, result: CleanupResult):
        """Обновление статистики с Prometheus метриками"""
        self.stats['total_cleanups'] += 1
        self.stats['total_space_freed_gb'] += result.space_freed_mb / 1024
        self.stats['last_cleanup_time'] = time.time()
        self.stats['files_removed_total'] += result.files_removed
        self.stats['files_backed_up_total'] += result.files_backed_up
        
        # Среднее время
        total_time = self.stats['average_cleanup_time'] * (self.stats['total_cleanups'] - 1)
        self.stats['average_cleanup_time'] = (total_time + result.duration_seconds) / self.stats['total_cleanups']
        
        # Prometheus метрики
        if self.cleanup_counter:
            self.cleanup_counter.labels(
                level=result.level.name,
                action=result.action.value,
                result="success" if result.success else "failure"
            ).inc()
        
        if self.space_freed_gauge:
            self.space_freed_gauge.inc(result.space_freed_mb / 1024)
    
    def get_stats(self) -> Dict:
        """Получение статистики"""
        return {
            **self.stats,
            'monitoring_active': self.monitoring_active,
            'triggers_count': len(self.triggers),
            'enabled_triggers': len([t for t in self.triggers if t.enabled]),
            'protected_paths_count': len(self.protected_paths),
            'backup_directory': self.backup_directory
        }
    
    async def stop_monitoring(self):
        """Остановка мониторинга"""
        self.monitoring_active = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Emergency monitoring stopped")


# Пример использования остаётся без изменений
