#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CORTEX v3.0 - Monitoring Protocol
Финальный протокол системы super-system-eyelids
Real-time наблюдение за всеми компонентами
"""

import asyncio
import time
import json
import psutil
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, asdict, field
from enum import Enum
import logging
from collections import deque, defaultdict
import hashlib

# Prometheus метрики
try:
    from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class AlertLevel(Enum):
    """Уровни критичности алертов"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

class ComponentStatus(Enum):
    """Статусы компонентов системы"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"
    UNKNOWN = "unknown"

@dataclass
class HealthMetric:
    """Метрика здоровья компонента"""
    component: str
    metric_name: str
    value: float
    threshold: float
    status: ComponentStatus
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Alert:
    """Системный алерт"""
    id: str
    level: AlertLevel
    component: str
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    resolved: bool = False
    resolution_time: Optional[datetime] = None
    auto_resolve: bool = True
    notifications_sent: Set[str] = field(default_factory=set)

@dataclass
class MonitoringConfig:
    """Конфигурация мониторинга"""
    monitoring_interval: int = 5  # секунды
    alert_cooldown: int = 300  # 5 минут
    metrics_retention: int = 3600  # 1 час
    health_check_timeout: int = 30
    max_alerts_per_minute: int = 10
    dashboard_update_interval: int = 1
    enable_prometheus: bool = True
    prometheus_port: int = 9090
    enable_webhooks: bool = True
    webhook_urls: List[str] = field(default_factory=list)

class MonitoringProtocol:
    """Enhanced Monitoring Protocol для CORTEX v3.0"""
    
    def __init__(self, config: MonitoringConfig = None):
        self.config = config or MonitoringConfig()
        self.logger = logging.getLogger(__name__)
        
        # Хранилища данных
        self.metrics_history = defaultdict(lambda: deque(maxlen=720))
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history = deque(maxlen=1000)
        self.component_statuses: Dict[str, HealthMetric] = {}
        self.alert_rate_limiter = deque(maxlen=60)  # Для rate limiting
        
        # Пороговые значения
        self.thresholds = {
            'cpu_usage': 80.0,
            'memory_usage': 85.0,
            'disk_usage': 90.0,
            'response_time': 2000,  # мс
            'error_rate': 5.0,  # %
            'queue_size': 1000,
            'cache_hit_rate': 70.0,  # %
            'snapshot_interval': 600,  # секунды (10 минут без снапшота - алерт)
        }
        
        # Компоненты для мониторинга
        self.monitored_components = {
            'input_protocol': {
                'url': 'http://localhost:8001/health',
                'critical': True,
                'timeout': 10
            },
            'routing_protocol': {
                'url': 'http://localhost:8002/health',
                'critical': True,
                'timeout': 10
            },
            'github_api': {
                'url': 'http://localhost:8003/health',
                'critical': True,
                'timeout': 15
            },
            'emergency_protocol': {
                'url': 'http://localhost:8004/health',
                'critical': False,
                'timeout': 10
            },
            'autosave_protocol': {
                'url': 'http://localhost:8005/health',
                'critical': False,
                'timeout': 10
            },
            'cortex_memory': {
                'url': 'http://localhost:8080/health',
                'critical': True,
                'timeout': 20
            },
            'system_resources': {
                'internal': True,
                'critical': True
            }
        }
        
        # Статистика
        self.stats = {
            'total_alerts': 0,
            'resolved_alerts': 0,
            'avg_resolution_time': 0.0,
            'system_uptime': time.time(),
            'last_health_check': None,
            'monitoring_errors': 0,
            'health_checks_performed': 0,
            'false_positives': 0
        }
        
        # Состояние
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Задачи
        self.tasks: List[asyncio.Task] = []
        
        # Prometheus метрики
        if PROMETHEUS_AVAILABLE and self.config.enable_prometheus:
            self._setup_prometheus_metrics()
        else:
            self.health_check_duration = None
            self.alert_counter = None
            self.component_status_gauge = None
            self.metrics_gauge = None
    
    def _setup_prometheus_metrics(self):
        """Настройка Prometheus метрик"""
        self.health_check_duration = Histogram(
            'monitoring_health_check_duration_seconds',
            'Duration of health checks',
            ['component']
        )
        
        self.alert_counter = Counter(
            'monitoring_alerts_total',
            'Total alerts created',
            ['level', 'component']
        )
        
        self.component_status_gauge = Gauge(
            'monitoring_component_status',
            'Component status (0=unknown, 1=healthy, 2=degraded, 3=unhealthy, 4=offline)',
            ['component']
        )
        
        self.metrics_gauge = Gauge(
            'monitoring_system_metrics',
            'System metrics',
            ['metric_name']
        )
        
        self.alert_resolution_time = Summary(
            'monitoring_alert_resolution_seconds',
            'Time to resolve alerts'
        )
        
        # Запуск HTTP сервера для Prometheus
        try:
            start_http_server(self.config.prometheus_port)
            self.logger.info(f"Prometheus metrics server started on port {self.config.prometheus_port}")
        except Exception as e:
            self.logger.error(f"Failed to start Prometheus server: {e}")
    
    async def initialize(self):
        """Инициализация протокола"""
        # Создаем HTTP сессию
        connector = aiohttp.TCPConnector(limit=20)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        
        self.logger.info("Monitoring Protocol initialized")
    
    async def start_monitoring(self):
        """Запуск системы мониторинга"""
        if self.running:
            return
        
        self.running = True
        
        if not self.session:
            await self.initialize()
        
        self.logger.info("Starting Monitoring Protocol for super-system-eyelids")
        
        # Запуск основных циклов
        self.tasks = [
            asyncio.create_task(self.health_check_loop()),
            asyncio.create_task(self.metrics_collection_loop()),
            asyncio.create_task(self.alert_processing_loop()),
            asyncio.create_task(self.dashboard_update_loop()),
            asyncio.create_task(self.cleanup_loop())
        ]
        
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            self.logger.info("Monitoring tasks cancelled")
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")
            self.stats['monitoring_errors'] += 1
    
    async def health_check_loop(self):
        """Основной цикл проверки здоровья"""
        while self.running:
            try:
                start_time = time.time()
                
                # Параллельная проверка всех компонентов
                health_tasks = []
                for component, config in self.monitored_components.items():
                    task = self.check_component_health(component, config)
                    health_tasks.append(task)
                
                health_results = await asyncio.gather(*health_tasks, return_exceptions=True)
                
                # Обработка результатов
                for component, result in zip(self.monitored_components.keys(), health_results):
                    if isinstance(result, Exception):
                        self.logger.error(f"Health check failed for {component}: {result}")
                        result = HealthMetric(
                            component=component,
                            metric_name='health_check',
                            value=0,
                            threshold=1,
                            status=ComponentStatus.UNKNOWN,
                            timestamp=datetime.now(),
                            details={'error': str(result)}
                        )
                    
                    self.component_statuses[component] = result
                    
                    # Обновление Prometheus метрик
                    if self.component_status_gauge:
                        status_value = {
                            ComponentStatus.UNKNOWN: 0,
                            ComponentStatus.HEALTHY: 1,
                            ComponentStatus.DEGRADED: 2,
                            ComponentStatus.UNHEALTHY: 3,
                            ComponentStatus.OFFLINE: 4
                        }.get(result.status, 0)
                        self.component_status_gauge.labels(component=component).set(status_value)
                    
                    # Создание алертов при необходимости
                    await self.check_and_create_alerts(component, result)
                
                self.stats['last_health_check'] = datetime.now()
                self.stats['health_checks_performed'] += 1
                
                check_duration = time.time() - start_time
                
                # Алерт если проверка занимает слишком много времени
                if check_duration > self.config.health_check_timeout:
                    await self.create_alert(
                        AlertLevel.WARNING,
                        'monitoring_protocol',
                        f"Health check took {check_duration:.2f}s (limit: {self.config.health_check_timeout}s)",
                        {'duration': check_duration}
                    )
                
                await asyncio.sleep(self.config.monitoring_interval)
                
            except Exception as e:
                self.logger.error(f"Error in health_check_loop: {e}")
                self.stats['monitoring_errors'] += 1
                await asyncio.sleep(5)
    
    async def check_component_health(self, component: str, config: Dict) -> HealthMetric:
        """Проверка здоровья компонента"""
        start_time = time.time()
        
        try:
            if config.get('internal'):
                # Внутренняя проверка системных ресурсов
                result = await self.check_system_resources()
            else:
                # HTTP health check
                result = await self.check_http_health(component, config)
            
            # Prometheus метрика длительности
            if self.health_check_duration:
                duration = time.time() - start_time
                self.health_check_duration.labels(component=component).observe(duration)
            
            return result
            
        except Exception as e:
            return HealthMetric(
                component=component,
                metric_name='health_check',
                value=0,
                threshold=1,
                status=ComponentStatus.UNKNOWN,
                timestamp=datetime.now(),
                details={'error': str(e)}
            )
    
    async def check_system_resources(self) -> HealthMetric:
        """Проверка системных ресурсов"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # Disk
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            
            # Network
            net_io = psutil.net_io_counters()
            
            # Процессы
            process_count = len(psutil.pids())
            
            # Определение статуса
            status = ComponentStatus.HEALTHY
            
            if (cpu_percent > self.thresholds['cpu_usage'] or 
                memory_percent > self.thresholds['memory_usage'] or 
                disk_percent > self.thresholds['disk_usage']):
                status = ComponentStatus.DEGRADED
            
            if cpu_percent > 95 or memory_percent > 95 or disk_percent > 95:
                status = ComponentStatus.UNHEALTHY
            
            # Обновление Prometheus метрик
            if self.metrics_gauge:
                self.metrics_gauge.labels(metric_name='cpu_usage').set(cpu_percent)
                self.metrics_gauge.labels(metric_name='memory_usage').set(memory_percent)
                self.metrics_gauge.labels(metric_name='disk_usage').set(disk_percent)
                self.metrics_gauge.labels(metric_name='process_count').set(process_count)
            
            return HealthMetric(
                component='system_resources',
                metric_name='resource_usage',
                value=max(cpu_percent, memory_percent, disk_percent),
                threshold=max(
                    self.thresholds['cpu_usage'],
                    self.thresholds['memory_usage'],
                    self.thresholds['disk_usage']
                ),
                status=status,
                timestamp=datetime.now(),
                details={
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory_percent,
                    'memory_available_gb': memory.available / (1024**3),
                    'disk_percent': disk_percent,
                    'disk_free_gb': disk.free / (1024**3),
                    'network_bytes_sent': net_io.bytes_sent,
                    'network_bytes_recv': net_io.bytes_recv,
                    'process_count': process_count
                }
            )
            
        except Exception as e:
            self.logger.error(f"System resources check failed: {e}")
            return HealthMetric(
                component='system_resources',
                metric_name='resource_check',
                value=0,
                threshold=1,
                status=ComponentStatus.UNKNOWN,
                timestamp=datetime.now(),
                details={'error': str(e)}
            )
    
    async def check_http_health(self, component: str, config: Dict) -> HealthMetric:
        """HTTP проверка здоровья компонента"""
        if not self.session:
            await self.initialize()
        
        start_time = time.time()
        url = config['url']
        timeout = config.get('timeout', 10)
        
        try:
            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                response_time = (time.time() - start_time) * 1000  # мс
                
                if response.status == 200:
                    try:
                        data = await response.json()
                    except:
                        data = {}
                    
                    status = ComponentStatus.HEALTHY
                    if response_time > self.thresholds['response_time']:
                        status = ComponentStatus.DEGRADED
                    
                    # Проверка специфичных метрик компонента
                    if 'error_rate' in data and data['error_rate'] > self.thresholds['error_rate']:
                        status = ComponentStatus.DEGRADED
                    
                    return HealthMetric(
                        component=component,
                        metric_name='http_health',
                        value=response_time,
                        threshold=self.thresholds['response_time'],
                        status=status,
                        timestamp=datetime.now(),
                        details={
                            'response_time': response_time,
                            'status_code': response.status,
                            'health_data': data
                        }
                    )
                else:
                    return HealthMetric(
                        component=component,
                        metric_name='http_health',
                        value=0,
                        threshold=1,
                        status=ComponentStatus.UNHEALTHY,
                        timestamp=datetime.now(),
                        details={
                            'status_code': response.status,
                            'response_time': response_time
                        }
                    )
                    
        except asyncio.TimeoutError:
            return HealthMetric(
                component=component,
                metric_name='http_health',
                value=0,
                threshold=1,
                status=ComponentStatus.OFFLINE,
                timestamp=datetime.now(),
                details={'error': 'timeout', 'timeout': timeout}
            )
        except Exception as e:
            return HealthMetric(
                component=component,
                metric_name='http_health',
                value=0,
                threshold=1,
                status=ComponentStatus.OFFLINE,
                timestamp=datetime.now(),
                details={'error': str(e)}
            )
    
    async def check_and_create_alerts(self, component: str, health: HealthMetric):
        """Проверка и создание алертов на основе здоровья компонента"""
        # Определение уровня алерта
        if health.status == ComponentStatus.OFFLINE:
            level = AlertLevel.CRITICAL
            message = f"Component {component} is OFFLINE"
        elif health.status == ComponentStatus.UNHEALTHY:
            level = AlertLevel.ERROR
            message = f"Component {component} is UNHEALTHY"
        elif health.status == ComponentStatus.DEGRADED:
            level = AlertLevel.WARNING
            message = f"Component {component} is DEGRADED"
        else:
            # Здоровый компонент - проверяем, есть ли активные алерты для разрешения
            await self.check_alert_resolution(component)
            return
        
        # Критичные компоненты получают более высокий приоритет
        if self.monitored_components[component].get('critical') and level == AlertLevel.ERROR:
            level = AlertLevel.CRITICAL
        
        await self.create_alert(level, component, message, health.details)
    
    async def create_alert(self, level: AlertLevel, component: str, message: str, details: Dict[str, Any]):
        """Создание нового алерта с проверками"""
        # Rate limiting
        current_time = time.time()
        self.alert_rate_limiter.append(current_time)
        
        # Очистка старых записей
        while self.alert_rate_limiter and self.alert_rate_limiter[0] < current_time - 60:
            self.alert_rate_limiter.popleft()
        
        if len(self.alert_rate_limiter) > self.config.max_alerts_per_minute:
            self.logger.warning(f"Alert rate limit exceeded, dropping alert: {message}")
            return
        
        # Проверка cooldown
        alert_key = f"{component}:{message}"
        if self.is_alert_in_cooldown(alert_key):
            return
        
        # Генерация ID
        alert_id = hashlib.md5(f"{alert_key}:{current_time}".encode()).hexdigest()[:12]
        
        # Проверка существующего алерта
        for existing_alert in self.active_alerts.values():
            if (existing_alert.component == component and 
                existing_alert.message == message and 
                not existing_alert.resolved):
                return  # Алерт уже существует
        
        alert = Alert(
            id=alert_id,
            level=level,
            component=component,
            message=message,
            details=details,
            timestamp=datetime.now()
        )
        
        self.active_alerts[alert_id] = alert
        self.alert_history.append(alert)
        self.stats['total_alerts'] += 1
        
        # Prometheus метрика
        if self.alert_counter:
            self.alert_counter.labels(level=level.value, component=component).inc()
        
        self.logger.warning(f"ALERT [{level.value.upper()}] {component}: {message}")
        
        # Отправка уведомлений
        await self.send_notifications(alert)
    
    def is_alert_in_cooldown(self, alert_key: str) -> bool:
        """Проверка cooldown для алерта"""
        cooldown_time = datetime.now() - timedelta(seconds=self.config.alert_cooldown)
        
        for alert in reversed(self.alert_history):
            if alert.timestamp < cooldown_time:
                break
            key = f"{alert.component}:{alert.message}"
            if key == alert_key:
                return True
        
        return False
    
    async def send_notifications(self, alert: Alert):
        """Отправка уведомлений об алерте"""
        if not self.config.enable_webhooks:
            return
        
        notification_data = {
            'alert_id': alert.id,
            'level': alert.level.value,
            'component': alert.component,
            'message': alert.message,
            'timestamp': alert.timestamp.isoformat(),
            'details': alert.details
        }
        
        # Отправка на все webhook URLs
        for webhook_url in self.config.webhook_urls:
            try:
                if self.session:
                    async with self.session.post(
                        webhook_url,
                        json=notification_data,
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            alert.notifications_sent.add(webhook_url)
            except Exception as e:
                self.logger.error(f"Failed to send notification to {webhook_url}: {e}")
    
    async def alert_processing_loop(self):
        """Цикл обработки и разрешения алертов"""
        while self.running:
            try:
                # Проверка автоматического разрешения алертов
                for alert_id, alert in list(self.active_alerts.items()):
                    if alert.resolved:
                        continue
                    
                    if alert.auto_resolve:
                        await self.check_alert_resolution(alert.component)
                
                await asyncio.sleep(5)
                
            except Exception as e:
                self.logger.error(f"Error in alert_processing_loop: {e}")
                await asyncio.sleep(5)
    
    async def check_alert_resolution(self, component: str):
        """Проверка разрешения алертов для компонента"""
        if component not in self.component_statuses:
            return
        
        current_status = self.component_statuses[component]
        
        if current_status.status == ComponentStatus.HEALTHY:
            # Разрешаем все алерты для этого компонента
            for alert_id, alert in list(self.active_alerts.items()):
                if alert.component == component and not alert.resolved:
                    alert.resolved = True
                    alert.resolution_time = datetime.now()
                    
                    resolution_duration = (alert.resolution_time - alert.timestamp).total_seconds()
                    self.stats['resolved_alerts'] += 1
                    
                    # Обновление средней времени разрешения
                    if self.stats['resolved_alerts'] > 0:
                        current_avg = self.stats['avg_resolution_time']
                        self.stats['avg_resolution_time'] = (
                            (current_avg * (self.stats['resolved_alerts'] - 1) + resolution_duration) / 
                            self.stats['resolved_alerts']
                        )
                    
                    # Prometheus метрика
                    if self.alert_resolution_time:
                        self.alert_resolution_time.observe(resolution_duration)
                    
                    self.logger.info(f"Alert {alert_id} resolved in {resolution_duration:.1f}s")
                    del self.active_alerts[alert_id]
    
    async def metrics_collection_loop(self):
        """Цикл сбора метрик"""
        while self.running:
            try:
                # Сбор метрик производительности
                metrics = await self.collect_performance_metrics()
                
                # Сохранение в историю
                timestamp = datetime.now()
                for metric_name, value in metrics.items():
                    self.metrics_history[metric_name].append({
                        'timestamp': timestamp,
                        'value': value
                    })
                
                await asyncio.sleep(self.config.monitoring_interval)
                
            except Exception as e:
                self.logger.error(f"Error in metrics_collection_loop: {e}")
                await asyncio.sleep(5)
    
    async def collect_performance_metrics(self) -> Dict[str, float]:
        """Сбор метрик производительности"""
        metrics = {}
        
        try:
            # Системные метрики
            metrics['cpu_usage'] = psutil.cpu_percent()
            metrics['memory_usage'] = psutil.virtual_memory().percent
            metrics['disk_usage'] = psutil.disk_usage('/').percent
            
            # Метрики сети
            net_io = psutil.net_io_counters()
            metrics['network_bytes_sent'] = net_io.bytes_sent
            metrics['network_bytes_recv'] = net_io.bytes_recv
            
            # Метрики процессов
            metrics['process_count'] = len(psutil.pids())
            
            # Метрики мониторинга
            metrics['active_alerts'] = len(self.active_alerts)
            metrics['health_checks'] = self.stats['health_checks_performed']
            metrics['monitoring_errors'] = self.stats['monitoring_errors']
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")
        
        return metrics
    
    async def dashboard_update_loop(self):
        """Цикл обновления дашборда"""
        while self.running:
            try:
                dashboard_data = await self.generate_dashboard_data()
                
                # Здесь будет отправка данных в веб-интерфейс
                # Например, через WebSocket или сохранение в файл
                
                await asyncio.sleep(self.config.dashboard_update_interval)
                
            except Exception as e:
                self.logger.error(f"Error in dashboard_update_loop: {e}")
                await asyncio.sleep(5)
    
    async def generate_dashboard_data(self) -> Dict[str, Any]:
        """Генерация данных для дашборда"""
        return {
            'timestamp': datetime.now().isoformat(),
            'system_status': self.get_overall_system_status(),
            'component_statuses': {
                comp: {
                    'status': status.status.value,
                    'value': status.value,
                    'threshold': status.threshold,
                    'last_check': status.timestamp.isoformat()
                }
                for comp, status in self.component_statuses.items()
            },
            'active_alerts': [
                {
                    'id': alert.id,
                    'level': alert.level.value,
                    'component': alert.component,
                    'message': alert.message,
                    'timestamp': alert.timestamp.isoformat()
                }
                for alert in self.active_alerts.values()
            ],
            'system_metrics': {
                'uptime': time.time() - self.stats['system_uptime'],
                'total_alerts': self.stats['total_alerts'],
                'resolved_alerts': self.stats['resolved_alerts'],
                'avg_resolution_time': self.stats['avg_resolution_time'],
                'monitoring_errors': self.stats['monitoring_errors'],
                'health_checks_performed': self.stats['health_checks_performed']
            },
            'recent_metrics': self.get_recent_metrics()
        }
    
    def get_overall_system_status(self) -> str:
        """Определение общего статуса системы"""
        if not self.component_statuses:
            return ComponentStatus.UNKNOWN.value
        
        statuses = [status.status for status in self.component_statuses.values()]
        
        # Проверка критичных компонентов
        critical_components = [
            comp for comp, config in self.monitored_components.items()
            if config.get('critical')
        ]
        
        critical_statuses = [
            self.component_statuses[comp].status
            for comp in critical_components
            if comp in self.component_statuses
        ]
        
        if any(status == ComponentStatus.OFFLINE for status in critical_statuses):
            return ComponentStatus.OFFLINE.value
        elif any(status == ComponentStatus.UNHEALTHY for status in critical_statuses):
            return ComponentStatus.UNHEALTHY.value
        elif any(status == ComponentStatus.DEGRADED for status in statuses):
            return ComponentStatus.DEGRADED.value
        elif all(status == ComponentStatus.HEALTHY for status in statuses):
            return ComponentStatus.HEALTHY.value
        else:
            return ComponentStatus.UNKNOWN.value
    
    def get_recent_metrics(self, minutes: int = 10) -> Dict[str, List[Dict]]:
        """Получение последних метрик"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        recent_metrics = {}
        
        for metric_name, history in self.metrics_history.items():
            recent_metrics[metric_name] = [
                entry for entry in history
                if entry['timestamp'] >= cutoff_time
            ]
        
        return recent_metrics
    
    async def cleanup_loop(self):
        """Цикл очистки старых данных"""
        while self.running:
            try:
                # Очистка старых метрик
                cutoff_time = datetime.now() - timedelta(seconds=self.config.metrics_retention)
                
                for metric_name, history in self.metrics_history.items():
                    while history and history[0]['timestamp'] < cutoff_time:
                        history.popleft()
                
                await asyncio.sleep(300)  # Каждые 5 минут
                
            except Exception as e:
                self.logger.error(f"Error in cleanup_loop: {e}")
                await asyncio.sleep(300)
    
    async def stop_monitoring(self):
        """Остановка мониторинга"""
        self.running = False
        
        # Отмена всех задач
        for task in self.tasks:
            task.cancel()
        
        # Закрытие HTTP сессии
        if self.session:
            await self.session.close()
        
        self.logger.info("Monitoring Protocol stopped")
    
    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Получение статистики мониторинга"""
        return {
            'uptime': time.time() - self.stats['system_uptime'],
            'total_alerts': self.stats['total_alerts'],
            'active_alerts': len(self.active_alerts),
            'resolved_alerts': self.stats['resolved_alerts'],
            'avg_resolution_time': self.stats['avg_resolution_time'],
            'monitoring_errors': self.stats['monitoring_errors'],
            'health_checks_performed': self.stats['health_checks_performed'],
            'component_count': len(self.monitored_components),
            'metrics_collected': sum(len(history) for history in self.metrics_history.values()),
            'overall_status': self.get_overall_system_status()
        }

# Пример использования
async def main():
    """Пример запуска мониторинга"""
    
    config = MonitoringConfig(
        monitoring_interval=5,
        alert_cooldown=300,
        enable_prometheus=True,
        prometheus_port=9090,
        enable_webhooks=True,
        webhook_urls=[
            'http://localhost:8000/webhooks/alerts'
        ]
    )
    
    monitor = MonitoringProtocol(config)
    
    try:
        await monitor.initialize()
        await monitor.start_monitoring()
    finally:
        await monitor.stop_monitoring()

if __name__ == "__main__":
    asyncio.run(main())
