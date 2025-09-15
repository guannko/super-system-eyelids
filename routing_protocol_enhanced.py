"""
CORTEX v3.0 - Routing Protocol ENHANCED
С улучшениями от Mistral
"""

import re
import asyncio
import json
import yaml
import hashlib
import zlib
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import fnmatch
from functools import lru_cache
from collections import defaultdict

class RoutingAction(Enum):
    DIRECT_ROUTE = "direct_route"
    COMPRESS_FIRST = "compress_first"
    SPLIT_AND_COMPRESS = "split_and_compress"
    IMMEDIATE_ROUTE = "immediate_route"
    FAST_ROUTE = "fast_route"
    NORMAL_ROUTE = "normal_route"
    BACKGROUND_ROUTE = "background_route"
    ARCHIVE_ROUTE = "archive_route"

class RepositoryTarget(Enum):
    CORTEX_MEMORY = "cortex-memory"
    PROJECT_REPOS = "project-repos"
    EYELIDS_CORE = "eyelids/core"
    CORTEX_ARCHIVE = "cortex-archive"
    TEMP_STORAGE = "temp-storage"
    DISTRIBUTED_CACHE = "distributed-cache"

@dataclass
class RoutingRule:
    pattern: str
    target: RepositoryTarget
    action: RoutingAction
    priority: int
    conditions: Dict[str, Any]
    metadata_requirements: List[str]

@dataclass
class RoutingResult:
    target_repository: RepositoryTarget
    action: RoutingAction
    processing_path: str
    estimated_time_ms: int
    compression_ratio: Optional[float]
    split_parts: Optional[int]
    routing_metadata: Dict[str, Any]

class RoutingProtocolEnhanced:
    """Enhanced Routing Protocol с улучшениями от Mistral"""
    
    def __init__(self, github_api, cache_manager, webhook_manager, config_path: str = None):
        self.github_api = github_api
        self.cache_manager = cache_manager
        self.webhook_manager = webhook_manager
        
        # Асинхронные очереди для параллельной обработки
        self.routing_queue = asyncio.Queue(maxsize=10000)
        self.priority_routing_queue = asyncio.Queue(maxsize=1000)
        self.worker_tasks = []
        
        # Загрузка правил из конфига или инициализация дефолтных
        if config_path and Path(config_path).exists():
            self.load_rules_from_config(config_path)
        else:
            self.pattern_rules = self._initialize_pattern_rules()
            self.size_rules = self._initialize_size_rules()
            self.priority_rules = self._initialize_priority_rules()
        
        # Паттерны безопасности
        self.forbidden_patterns = [
            r"eval\s*\(", r"exec\s*\(", r"__import__\s*\(",
            r"os\.system", r"subprocess\.", r"open\s*\(",
            r"DROP\s+TABLE", r"DELETE\s+FROM", r"UPDATE\s+.*\s+SET",
            r"<script[^>]*>", r"javascript:", r"onerror\s*=",
        ]
        
        # Детализированная статистика
        self.routing_stats = {
            'total_routed': 0,
            'by_pattern': defaultdict(int),
            'by_size': defaultdict(int),
            'by_priority': defaultdict(int),
            'by_target': defaultdict(int),
            'compression_saved_bytes': 0,
            'split_operations': 0,
            'errors': 0,
            'last_export': None
        }
        
        # Кэш маршрутов
        self.route_cache = {}
        
    def load_rules_from_config(self, config_path: str):
        """Динамическая загрузка правил из конфига"""
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        # Конвертация правил из конфига
        self.pattern_rules = []
        for rule_dict in config.get("pattern_rules", []):
            self.pattern_rules.append(RoutingRule(
                pattern=rule_dict["pattern"],
                target=RepositoryTarget[rule_dict["target"]],
                action=RoutingAction[rule_dict["action"]],
                priority=rule_dict["priority"],
                conditions=rule_dict.get("conditions", {}),
                metadata_requirements=rule_dict.get("metadata_requirements", [])
            ))
        
        self.size_rules = config.get("size_rules", self._initialize_size_rules())
        self.priority_rules = config.get("priority_rules", self._initialize_priority_rules())
        
        print(f"Loaded {len(self.pattern_rules)} pattern rules from {config_path}")
    
    def _initialize_pattern_rules(self) -> List[RoutingRule]:
        """Дефолтные правила маршрутизации"""
        return [
            # Автосейвы - высший приоритет
            RoutingRule(
                pattern="autosave_*.md",
                target=RepositoryTarget.CORTEX_MEMORY,
                action=RoutingAction.FAST_ROUTE,
                priority=10,
                conditions={'max_age_hours': 24},
                metadata_requirements=['timestamp', 'source']
            ),
            
            # Код проектов
            RoutingRule(
                pattern="*.py",
                target=RepositoryTarget.PROJECT_REPOS,
                action=RoutingAction.DIRECT_ROUTE,
                priority=9,
                conditions={'validate_syntax': True},
                metadata_requirements=['project_name']
            ),
            
            # Конфиги
            RoutingRule(
                pattern="config_*.json",
                target=RepositoryTarget.EYELIDS_CORE,
                action=RoutingAction.IMMEDIATE_ROUTE,
                priority=10,
                conditions={'validate_json': True},
                metadata_requirements=['config_type']
            ),
            
            # Архивы
            RoutingRule(
                pattern="backup_*",
                target=RepositoryTarget.CORTEX_ARCHIVE,
                action=RoutingAction.COMPRESS_FIRST,
                priority=3,
                conditions={'compress_ratio': 0.7},
                metadata_requirements=['backup_date']
            ),
            
            # Медиа
            RoutingRule(
                pattern="*.png",
                target=RepositoryTarget.DISTRIBUTED_CACHE,
                action=RoutingAction.COMPRESS_FIRST,
                priority=5,
                conditions={'max_size_mb': 50},
                metadata_requirements=[]
            ),
            
            # Временные
            RoutingRule(
                pattern="temp_*",
                target=RepositoryTarget.TEMP_STORAGE,
                action=RoutingAction.BACKGROUND_ROUTE,
                priority=1,
                conditions={'ttl_hours': 1},
                metadata_requirements=[]
            )
        ]
    
    def _initialize_size_rules(self) -> Dict[str, Dict[str, Any]]:
        """Правила по размеру"""
        return {
            'large': {
                'condition': lambda size: size > 100 * 1024 * 1024,  # > 100MB
                'action': RoutingAction.SPLIT_AND_COMPRESS,
                'target': RepositoryTarget.DISTRIBUTED_CACHE,
                'split_size_mb': 50,
                'compression_level': 9
            },
            'medium': {
                'condition': lambda size: 50 * 1024 * 1024 < size <= 100 * 1024 * 1024,
                'action': RoutingAction.COMPRESS_FIRST,
                'target': None,
                'compression_level': 6
            },
            'small': {
                'condition': lambda size: size <= 50 * 1024 * 1024,
                'action': RoutingAction.DIRECT_ROUTE,
                'target': None
            }
        }
    
    def _initialize_priority_rules(self) -> Dict[str, Dict[str, Any]]:
        """Правила приоритета"""
        return {
            'CRITICAL': {
                'action': RoutingAction.IMMEDIATE_ROUTE,
                'max_processing_time_ms': 100,
                'bypass_queue': True,
                'webhook_notify': True
            },
            'HIGH': {
                'action': RoutingAction.FAST_ROUTE,
                'max_processing_time_ms': 500,
                'bypass_queue': False,
                'webhook_notify': True
            },
            'MEDIUM': {
                'action': RoutingAction.NORMAL_ROUTE,
                'max_processing_time_ms': 2000,
                'bypass_queue': False,
                'webhook_notify': False
            },
            'LOW': {
                'action': RoutingAction.BACKGROUND_ROUTE,
                'max_processing_time_ms': 10000,
                'bypass_queue': False,
                'webhook_notify': False
            }
        }
    
    # ========== ВАЛИДАЦИЯ БЕЗОПАСНОСТИ ==========
    
    def validate_content_safety(self, content: str) -> bool:
        """Проверка контента на безопасность"""
        content_lower = content.lower()
        return not any(re.search(pattern, content_lower) for pattern in self.forbidden_patterns)
    
    def verify_data_integrity(self, data: Dict[str, Any]) -> bool:
        """Проверка целостности данных"""
        if "checksum" not in data:
            return True
        
        content = str(data.get("content", ""))
        current_checksum = hashlib.sha256(content.encode()).hexdigest()
        return current_checksum == data["checksum"]
    
    # ========== PATTERN MATCHING С КЭШЕМ ==========
    
    @lru_cache(maxsize=1024)
    def match_pattern_cached(self, filename: str, content_type: str = "") -> Optional[str]:
        """Кэшированный поиск правила (возвращает pattern для поиска в rules)"""
        sorted_rules = sorted(self.pattern_rules, key=lambda r: r.priority, reverse=True)
        
        for rule in sorted_rules:
            if fnmatch.fnmatch(filename, rule.pattern):
                return rule.pattern
            if content_type and fnmatch.fnmatch(content_type, rule.pattern):
                return rule.pattern
        
        return None
    
    def match_pattern(self, filename: str, content_type: str = "") -> Optional[RoutingRule]:
        """Поиск правила по паттерну"""
        pattern = self.match_pattern_cached(filename, content_type)
        if pattern:
            for rule in self.pattern_rules:
                if rule.pattern == pattern:
                    return rule
        return None
    
    # ========== АСИНХРОННОЕ СЖАТИЕ ==========
    
    async def compress_data_async(self, data: Dict[str, Any], level: int = 6) -> bytes:
        """Асинхронное сжатие данных"""
        content = str(data.get("content", "")).encode()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: zlib.compress(content, level=level))
    
    # ========== ОСНОВНОЙ ПРОТОКОЛ ==========
    
    async def routing_protocol(self, data_id: str, data: Dict[str, Any], metadata: Dict[str, Any]) -> RoutingResult:
        """Главный протокол маршрутизации с улучшениями"""
        start_time = datetime.now()
        
        try:
            # 1. Проверка безопасности контента
            if "content" in data:
                if not self.validate_content_safety(str(data["content"])):
                    self.routing_stats["errors"] += 1
                    raise ValueError("Unsafe content detected")
            
            # 2. Проверка целостности
            if not self.verify_data_integrity(data):
                self.routing_stats["errors"] += 1
                raise ValueError("Data integrity check failed")
            
            filename = metadata.get('filename', data_id)
            content_type = metadata.get('content_type', '')
            size_bytes = data.get('size_bytes', 0)
            priority = metadata.get('priority', 'MEDIUM').upper()
            
            # 3. Проверка кэша маршрутов
            cache_key = f"{filename}:{content_type}:{size_bytes}:{priority}"
            if cache_key in self.route_cache:
                cached_result = self.route_cache[cache_key]
                self.routing_stats['total_routed'] += 1
                return cached_result
            
            # 4. Поиск правила по паттерну
            pattern_rule = self.match_pattern(filename, content_type)
            
            # 5. Определение действия по размеру
            size_action = None
            size_metadata = {}
            for size_category, rule in self.size_rules.items():
                if rule['condition'](size_bytes):
                    size_action = rule['action']
                    size_metadata = {
                        'size_category': size_category,
                        'compression_level': rule.get('compression_level'),
                        'split_size_mb': rule.get('split_size_mb'),
                        'target_override': rule.get('target')
                    }
                    break
            
            # 6. Применение правил приоритета
            priority_rules = self.priority_rules.get(priority, self.priority_rules['MEDIUM'])
            
            # 7. Определение финального действия и цели
            if pattern_rule:
                target = pattern_rule.target
                action = pattern_rule.action
                
                if size_metadata.get('target_override'):
                    target = size_metadata['target_override']
                
                if size_action in [RoutingAction.SPLIT_AND_COMPRESS, RoutingAction.COMPRESS_FIRST]:
                    action = size_action
            else:
                target = size_metadata.get('target_override', RepositoryTarget.DISTRIBUTED_CACHE)
                action = size_action or RoutingAction.NORMAL_ROUTE
            
            # Переопределение для критичных
            if priority in ['CRITICAL', 'HIGH']:
                action = priority_rules['action']
            
            # 8. Расчёт параметров
            compression_ratio = None
            split_parts = None
            
            if action in [RoutingAction.COMPRESS_FIRST, RoutingAction.SPLIT_AND_COMPRESS]:
                compression_level = size_metadata.get('compression_level', 6)
                # Асинхронное сжатие для оценки
                compressed = await self.compress_data_async(data, compression_level)
                compression_ratio = len(compressed) / size_bytes if size_bytes > 0 else 1.0
            
            if action == RoutingAction.SPLIT_AND_COMPRESS:
                split_size_mb = size_metadata.get('split_size_mb', 50)
                split_size_bytes = split_size_mb * 1024 * 1024
                split_parts = max(1, (size_bytes + split_size_bytes - 1) // split_size_bytes)
            
            # 9. Оценка времени
            base_times = {
                RoutingAction.IMMEDIATE_ROUTE: 50,
                RoutingAction.FAST_ROUTE: 200,
                RoutingAction.DIRECT_ROUTE: 500,
                RoutingAction.NORMAL_ROUTE: 1000,
                RoutingAction.COMPRESS_FIRST: 2000,
                RoutingAction.SPLIT_AND_COMPRESS: 5000,
                RoutingAction.BACKGROUND_ROUTE: 10000,
                RoutingAction.ARCHIVE_ROUTE: 15000
            }
            
            estimated_time = base_times.get(action, 1000)
            size_factor = min(5.0, size_bytes / (10 * 1024 * 1024))
            estimated_time = int(estimated_time * (1 + size_factor * 0.5))
            
            # 10. Формирование результата
            processing_path = f"{target.value}/{action.value}/{priority.lower()}/{data_id}"
            
            result = RoutingResult(
                target_repository=target,
                action=action,
                processing_path=processing_path,
                estimated_time_ms=estimated_time,
                compression_ratio=compression_ratio,
                split_parts=split_parts,
                routing_metadata={
                    'pattern_matched': pattern_rule.pattern if pattern_rule else None,
                    'size_category': size_metadata.get('size_category'),
                    'priority': priority,
                    'bypass_queue': priority_rules.get('bypass_queue', False),
                    'webhook_notify': priority_rules.get('webhook_notify', False),
                    'processing_time_ms': (datetime.now() - start_time).total_seconds() * 1000
                }
            )
            
            # 11. Кэширование результата
            self.route_cache[cache_key] = result
            
            # 12. Обновление статистики
            await self._update_routing_stats(result, size_bytes)
            
            # 13. Webhook уведомления
            if result.routing_metadata['webhook_notify']:
                await self.webhook_manager.send_webhook(
                    'data_routed',
                    {
                        'data_id': data_id,
                        'target': target.value,
                        'action': action.value,
                        'priority': priority
                    },
                    'info' if priority != 'CRITICAL' else 'critical'
                )
            
            return result
            
        except Exception as e:
            self.routing_stats["errors"] += 1
            
            # Безопасный маршрут по умолчанию
            return RoutingResult(
                target_repository=RepositoryTarget.TEMP_STORAGE,
                action=RoutingAction.BACKGROUND_ROUTE,
                processing_path=f"temp-storage/error/{data_id}",
                estimated_time_ms=5000,
                compression_ratio=None,
                split_parts=None,
                routing_metadata={
                    'error': str(e),
                    'fallback_route': True
                }
            )
    
    # ========== ВОРКЕРЫ ДЛЯ ПАРАЛЛЕЛЬНОЙ ОБРАБОТКИ ==========
    
    async def start_routing_workers(self, num_workers: int = 4, num_priority_workers: int = 2):
        """Запуск воркеров для обработки очередей"""
        
        async def routing_worker(queue, worker_id, is_priority=False):
            """Воркер для обработки очереди маршрутизации"""
            worker_type = "priority" if is_priority else "regular"
            print(f"Starting {worker_type} routing worker {worker_id}")
            
            while True:
                try:
                    data_id, data, metadata = await queue.get()
                    result = await self.routing_protocol(data_id, data, metadata)
                    
                    # Здесь можно добавить дальнейшую обработку результата
                    print(f"Worker {worker_id} routed {data_id} to {result.target_repository.value}")
                    
                    queue.task_done()
                    
                except Exception as e:
                    print(f"Worker {worker_id} error: {e}")
        
        # Запуск обычных воркеров
        for i in range(num_workers):
            task = asyncio.create_task(routing_worker(self.routing_queue, i))
            self.worker_tasks.append(task)
        
        # Запуск приоритетных воркеров
        for i in range(num_priority_workers):
            task = asyncio.create_task(routing_worker(self.priority_routing_queue, i, True))
            self.worker_tasks.append(task)
        
        print(f"Started {num_workers} regular + {num_priority_workers} priority routing workers")
    
    async def add_to_routing_queue(self, data_id: str, data: Dict[str, Any], metadata: Dict[str, Any], priority: bool = False):
        """Добавление в очередь маршрутизации"""
        queue = self.priority_routing_queue if priority else self.routing_queue
        await queue.put((data_id, data, metadata))
    
    # ========== GITHUB СИНХРОНИЗАЦИЯ ==========
    
    async def sync_with_github(self, repo: str, branch: str, file_pattern: str = "**/*"):
        """Синхронизация файлов с GitHub репозиторием"""
        try:
            files = await self.github_api.list_files(repo, branch, file_pattern)
            
            for file in files:
                # Получение контента файла
                data = await self.github_api.get_file_content(repo, branch, file["path"])
                
                # Добавление в очередь маршрутизации
                await self.add_to_routing_queue(
                    file["sha"],
                    {"content": data, "size_bytes": file["size"]},
                    {
                        "filename": file["name"],
                        "source": "github",
                        "repo": repo,
                        "branch": branch,
                        "priority": "MEDIUM"
                    }
                )
            
            print(f"Synced {len(files)} files from {repo}/{branch}")
            
        except Exception as e:
            print(f"GitHub sync error: {e}")
    
    # ========== СТАТИСТИКА ==========
    
    async def _update_routing_stats(self, result: RoutingResult, size_bytes: int):
        """Обновление статистики"""
        self.routing_stats['total_routed'] += 1
        
        # По паттернам
        pattern = result.routing_metadata.get('pattern_matched')
        if pattern:
            self.routing_stats['by_pattern'][pattern] += 1
        
        # По размерам
        size_category = result.routing_metadata.get('size_category')
        if size_category:
            self.routing_stats['by_size'][size_category] += 1
        
        # По приоритетам
        priority = result.routing_metadata.get('priority')
        if priority:
            self.routing_stats['by_priority'][priority] += 1
        
        # По целям
        target = result.target_repository.value
        self.routing_stats['by_target'][target] += 1
        
        # Статистика сжатия
        if result.compression_ratio:
            saved_bytes = int(size_bytes * (1 - result.compression_ratio))
            self.routing_stats['compression_saved_bytes'] += saved_bytes
        
        # Статистика разделения
        if result.split_parts and result.split_parts > 1:
            self.routing_stats['split_operations'] += 1
    
    async def export_stats(self, filename: str = None):
        """Экспорт статистики в файл"""
        filename = filename or f"routing_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        stats_dir = Path("stats")
        stats_dir.mkdir(exist_ok=True)
        
        export_data = {
            "timestamp": datetime.now().isoformat(),
            "stats": dict(self.routing_stats),
            "cache_size": len(self.route_cache),
            "queue_sizes": {
                "regular": self.routing_queue.qsize(),
                "priority": self.priority_routing_queue.qsize()
            }
        }
        
        with open(stats_dir / filename, "w") as f:
            json.dump(export_data, f, indent=2, default=str)
        
        self.routing_stats['last_export'] = datetime.now()
        print(f"Stats exported to {filename}")
        
        return filename
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        total = self.routing_stats['total_routed']
        
        return {
            **dict(self.routing_stats),
            'efficiency_metrics': {
                'avg_compression_savings': self.routing_stats['compression_saved_bytes'] / max(1, total),
                'split_percentage': (self.routing_stats['split_operations'] / max(1, total)) * 100,
                'error_rate': (self.routing_stats['errors'] / max(1, total + self.routing_stats['errors'])) * 100,
                'cache_hit_rate': len(self.route_cache) / max(1, total) * 100
            }
        }
    
    async def shutdown(self):
        """Корректное завершение"""
        print("Shutting down Routing Protocol...")
        
        # Экспорт финальной статистики
        await self.export_stats("final_routing_stats.json")
        
        # Отмена воркеров
        for task in self.worker_tasks:
            task.cancel()
        
        # Ожидание очередей
        await self.routing_queue.join()
        await self.priority_routing_queue.join()
        
        print("Routing Protocol shutdown complete")


# ========== ПРИМЕР ИСПОЛЬЗОВАНИЯ ==========

async def example_usage():
    """Пример использования Enhanced Routing Protocol"""
    
    # Моки для тестирования
    class MockGitHubAPI:
        async def list_files(self, repo, branch, pattern):
            return [
                {"name": "test.py", "path": "src/test.py", "size": 1024, "sha": "abc123"},
                {"name": "config.json", "path": "config/config.json", "size": 512, "sha": "def456"}
            ]
        
        async def get_file_content(self, repo, branch, path):
            return f"# Content of {path}"
    
    class MockCacheManager:
        pass
    
    class MockWebhookManager:
        async def send_webhook(self, event, data, priority):
            print(f"Webhook: {event} - {priority}")
    
    # Создание протокола
    router = RoutingProtocolEnhanced(
        MockGitHubAPI(),
        MockCacheManager(),
        MockWebhookManager()
    )
    
    # Запуск воркеров
    await router.start_routing_workers()
    
    # Тесты маршрутизации
    test_cases = [
        {
            'data_id': 'test_1',
            'data': {'content': 'Python code', 'size_bytes': 1024},
            'metadata': {'filename': 'code_main.py', 'priority': 'HIGH', 'project_name': 'test'}
        },
        {
            'data_id': 'test_2',
            'data': {'content': 'Large file', 'size_bytes': 150 * 1024 * 1024},
            'metadata': {'filename': 'big_data.json', 'priority': 'MEDIUM'}
        },
        {
            'data_id': 'test_3',
            'data': {'content': '{"config": true}', 'size_bytes': 512},
            'metadata': {'filename': 'config_app.json', 'priority': 'CRITICAL', 'config_type': 'app'}
        }
    ]
    
    # Добавление в очередь
    for test in test_cases:
        is_priority = test['metadata']['priority'] in ['CRITICAL', 'HIGH']
        await router.add_to_routing_queue(
            test['data_id'],
            test['data'],
            test['metadata'],
            priority=is_priority
        )
    
    # Ожидание обработки
    await asyncio.sleep(2)
    
    # Статистика
    print("\nRouting Stats:", router.get_routing_stats())
    
    # GitHub синхронизация
    await router.sync_with_github("test-repo", "main", "*.py")
    
    # Экспорт статистики
    await router.export_stats()
    
    # Завершение
    await router.shutdown()


if __name__ == "__main__":
    asyncio.run(example_usage())
