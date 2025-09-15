#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CORTEX v3.0 - Monitoring Protocol ENHANCED
Финальный протокол с улучшениями от Mistral
Включает: эскалацию алертов, зависимости компонентов, автовосстановление
"""

import asyncio
import time
import json
import psutil
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple
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

# Настройка логирования в JSON формате
import json
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}',
            "datefmt": "%Y-%m-%d %H:%M:%S"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "level": "INFO"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": "monitoring.log",
            "maxBytes": 10485760,
            "backupCount": 5,
            "level": "DEBUG"
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"]
    }
}

logging.config.dictConfig(LOGGING_CONFIG)

class AlertLevel(Enum):
    """Уровни критичности алертов"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    EMERGENCY = "emergency"
    
    def escalate(self) -> 'AlertLevel':
        """Эскалация уровня алерта"""
        escalation_map = {
            AlertLevel.INFO: AlertLevel.WARNING,
            AlertLevel.WARNING: AlertLevel.ERROR,
            AlertLevel.ERROR: AlertLevel.CRITICAL,
            AlertLevel.CRITICAL: AlertLevel.EMERGENCY,
            AlertLevel.EMERGENCY: AlertLevel.EMERGENCY
        }
        return escalation_map[self]

class ComponentStatus(Enum):
    """Статусы компонентов системы"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    RECOVERING = "recovering"

@dataclass
class ComponentDependency:
    """Зависимость между компонентами"""
    component: str
    depends_on: List[str]
    critical: bool = False
    cascade_failure: bool = True

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
    recovery_attempts: int = 0

@dataclass
class Alert:
    """Системный алерт с поддержкой эскалации"""
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
    escalation_count: int = 0
    last_escalation: Optional[datetime] = None
    escalation_timeout: int = 300  # 5 минут до эскалации

@dataclass
class MonitoringConfig:
    """Расширенная конфигурация мониторинга"""
    monitoring_interval: int = 5
    alert_cooldown: int = 300
    metrics_retention: int = 3600
    health_check_timeout: int = 30
    max_alerts_per_minute: int = 10
    dashboard_update_interval: int = 1
    enable_prometheus: bool = True
    prometheus_port: int = 9090
    enable_webhooks: bool = True
    webhook_urls: List[str] = field(default_factory=list)
    slack_webhook: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    email_settings: Optional[Dict] = None
    enable_auto_recovery: bool = True
    max_recovery_attempts: int = 3
    recovery_cooldown: int = 600
    custom_metrics_config: Optional[str] = None

class MonitoringProtocolEnhanced:
    """Enhanced Monitoring Protocol с улучшениями от Mistral"""
    
    def __init__(self, config: MonitoringConfig = None):
        self.config = config or MonitoringConfig()
        self.logger = logging.getLogger(__name__)
        
        # Хранилища данных
        self.metrics_history = defaultdict(lambda: deque(maxlen=720))
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history = deque(maxlen=1000)
        self.component_statuses: Dict[str, HealthMetric] = {}
        self.alert_rate_limiter = deque(maxlen=60)
        self.recovery_history: Dict[str, List[datetime]] = defaultdict(list)
        
        # Зависимости компонентов
        self.component_dependencies = self._initialize_dependencies()
        
        # Динамические пороги
        self.thresholds = self._load_thresholds()
        
        # Пользовательские метрики
        self.custom_metrics = self._load_custom_metrics()
        
        # Компоненты для мониторинга
        self.monitored_components = {
            'input_protocol': {
                'url': 'http://localhost:8001/health',
                'critical': True,
                'timeout': 10,
                'auto_recover': True
            },
            'routing_protocol': {
                'url': 'http://localhost:8002/health',
                'critical': True,
                'timeout': 10,
                'auto_recover': True
            },
            'github_api': {
                'url': 'http://localhost:8003/health',
                'critical': True,
                'timeout': 15,
                'auto_recover': False
            },
            'emergency_protocol': {
                'url': 'http://localhost:8004/health',
                'critical': False,
                'timeout': 10,
                'auto_recover': True
            },
            'autosave_protocol': {
                'url': 'http://localhost:8005/health',
                'critical': False,
                'timeout': 10,
                'auto_recover': True
            },
            'cortex_memory': {
                'url': 'http://localhost:8080/health',
                'critical': True,
                'timeout': 20,
                'auto_recover': False
            },
            'system_resources': {
                'internal': True,
                'critical': True,
                'auto_recover': False
            }
        }
        
        # Статистика
        self.stats = {
            'total_alerts': 0,
            'resolved_alerts': 0,
            'escalated_alerts': 0,
            'avg_resolution_time': 0.0,
            'system_uptime': time.time(),
            'last_health_check': None,
            'monitoring_errors': 0,
            'health_checks_performed': 0,
            'recovery_attempts': 0,
            'successful_recoveries': 0
        }
        
        # Состояние
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.tasks: List[asyncio.Task] = []
        
        # Prometheus метрики
        if PROMETHEUS_AVAILABLE and self.config.enable_prometheus:
            self._setup_prometheus_metrics()
    
    def _initialize_dependencies(self) -> List[ComponentDependency]:
        """Инициализация зависимостей между компонентами"""
        return [
            ComponentDependency(
                component="autosave_protocol",
                depends_on=["cortex_memory", "github_api"],
                critical=False,
                cascade_failure=True
            ),
            ComponentDependency(
                component="routing_protocol",
                depends_on=["input_protocol"],
                critical=True,
                cascade_failure=True
            ),
            ComponentDependency(
                component="emergency_protocol",
                depends_on=["system_resources"],
                critical=False,
                cascade_failure=False
            )
        ]
    
    def _load_thresholds(self) -> Dict[str, float]:
        """Загрузка динамических порогов из конфигурации"""
        default_thresholds = {
            'cpu_usage': 80.0,
            'memory_usage': 85.0,
            'disk_usage': 90.0,
            'response_time': 2000,
            'error_rate': 5.0,
            'queue_size': 1000,
            'cache_hit_rate': 70.0,
            'snapshot_interval': 600
        }
        
        # Попытка загрузить из файла конфигурации
        if self.config.custom_metrics_config:
            try:
                with open(self.config.custom_metrics_config) as f:
                    custom_thresholds = json.load(f).get('thresholds', {})
                    default_thresholds.update(custom_thresholds)
                    self.logger.info(f"Loaded custom thresholds: {custom_thresholds}")
            except Exception as e:
                self.logger.error(f"Failed to load custom thresholds: {e}")
        
        return default_thresholds
    
    def _load_custom_metrics(self) -> Dict[str, Any]:
        """Загрузка пользовательских метрик"""
        custom_metrics = {}
        
        if self.config.custom_metrics_config:
            try:
                with open(self.config.custom_metrics_config) as f:
                    config = json.load(f)
                    custom_metrics = config.get('custom_metrics', {})
                    self.logger.info(f"Loaded {len(custom_metrics)} custom metrics")
            except Exception as e:
                self.logger.error(f"Failed to load custom metrics: {e}")
        
        return custom_metrics
    
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
        
        self.escalation_counter = Counter(
            'monitoring_alert_escalations_total',
            'Total alert escalations',
            ['component']
        )
        
        self.recovery_counter = Counter(
            'monitoring_recovery_attempts_total',
            'Total recovery attempts',
            ['component', 'result']
        )
        
        self.component_status_gauge = Gauge(
            'monitoring_component_status',
            'Component status',
            ['component']
        )
        
        try:
            start_http_server(self.config.prometheus_port)
            self.logger.info(f"Prometheus metrics server started on port {self.config.prometheus_port}")
        except Exception as e:
            self.logger.error(f"Failed to start Prometheus server: {e}")
    
    async def check_dependencies(self, component: str) -> Tuple[bool, List[str]]:
        """Проверка зависимостей компонента"""
        affected_components = []
        all_dependencies_healthy = True
        
        for dep in self.component_dependencies:
            if dep.component == component:
                for required_component in dep.depends_on:
                    if required_component in self.component_statuses:
                        status = self.component_statuses[required_component].status
                        if status not in [ComponentStatus.HEALTHY, ComponentStatus.DEGRADED]:
                            all_dependencies_healthy = False
                            if dep.cascade_failure:
                                affected_components.append(component)
        
        return all_dependencies_healthy, affected_components
    
    async def auto_recover_component(self, component: str) -> bool:
        """Автоматическое восстановление компонента"""
        if not self.config.enable_auto_recovery:
            return False
        
        if not self.monitored_components[component].get('auto_recover', False):
            return False
        
        # Проверка cooldown
        recent_recoveries = [
            t for t in self.recovery_history[component]
            if (datetime.now() - t).total_seconds() < self.config.recovery_cooldown
        ]
        
        if len(recent_recoveries) >= self.config.max_recovery_attempts:
            self.logger.warning(f"Max recovery attempts reached for {component}")
            return False
        
        self.logger.info(f"Attempting auto-recovery for {component}")
        self.stats['recovery_attempts'] += 1
        
        try:
            # Здесь должна быть логика перезапуска компонента
            # Например, через systemctl или docker restart
            recovery_successful = await self._perform_recovery(component)
            
            if recovery_successful:
                self.stats['successful_recoveries'] += 1
                self.recovery_history[component].append(datetime.now())
                
                if self.recovery_counter:
                    self.recovery_counter.labels(component=component, result='success').inc()
                
                return True
            else:
                if self.recovery_counter:
                    self.recovery_counter.labels(component=component, result='failure').inc()
                
                return False
                
        except Exception as e:
            self.logger.error(f"Recovery failed for {component}: {e}")
            return False
    
    async def _perform_recovery(self, component: str) -> bool:
        """Выполнение восстановления компонента"""
        # Заглушка для реальной логики восстановления
        # В реальной системе здесь будет:
        # - Перезапуск через systemctl/docker
        # - Очистка кэша
        # - Переподключение к БД
        # и т.д.
        
        await asyncio.sleep(2)  # Имитация восстановления
        return True
    
    async def escalate_alert(self, alert: Alert):
        """Эскалация алерта"""
        if alert.level == AlertLevel.EMERGENCY:
            return  # Уже максимальный уровень
        
        alert.level = alert.level.escalate()
        alert.escalation_count += 1
        alert.last_escalation = datetime.now()
        
        self.stats['escalated_alerts'] += 1
        
        if self.escalation_counter:
            self.escalation_counter.labels(component=alert.component).inc()
        
        self.logger.warning(f"Alert {alert.id} escalated to {alert.level.value}")
        
        # Отправка уведомления об эскалации
        await self.send_escalation_notification(alert)
    
    async def send_escalation_notification(self, alert: Alert):
        """Отправка уведомления об эскалации"""
        message = f"🔺 ESCALATION: Alert {alert.id} escalated to {alert.level.value}\n"
        message += f"Component: {alert.component}\n"
        message += f"Message: {alert.message}\n"
        message += f"Escalation count: {alert.escalation_count}"
        
        # Отправка в Slack
        if self.config.slack_webhook:
            await self.send_to_slack(message)
        
        # Отправка в Telegram
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            await self.send_to_telegram(message)
    
    async def send_to_slack(self, message: str):
        """Отправка сообщения в Slack"""
        if not self.config.slack_webhook:
            return
        
        try:
            payload = {"text": message}
            
            if self.session:
                async with self.session.post(
                    self.config.slack_webhook,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        self.logger.debug("Slack notification sent")
        except Exception as e:
            self.logger.error(f"Failed to send Slack notification: {e}")
    
    async def send_to_telegram(self, message: str):
        """Отправка сообщения в Telegram"""
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.config.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            if self.session:
                async with self.session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        self.logger.debug("Telegram notification sent")
        except Exception as e:
            self.logger.error(f"Failed to send Telegram notification: {e}")
    
    async def alert_processing_loop(self):
        """Улучшенный цикл обработки алертов с эскалацией"""
        while self.running:
            try:
                current_time = datetime.now()
                
                for alert_id, alert in list(self.active_alerts.items()):
                    if alert.resolved:
                        continue
                    
                    # Проверка необходимости эскалации
                    if alert.last_escalation:
                        time_since_escalation = (current_time - alert.last_escalation).total_seconds()
                    else:
                        time_since_escalation = (current_time - alert.timestamp).total_seconds()
                    
                    if time_since_escalation > alert.escalation_timeout:
                        await self.escalate_alert(alert)
                    
                    # Проверка автоматического разрешения
                    if alert.auto_resolve:
                        await self.check_alert_resolution(alert.component)
                
                await asyncio.sleep(5)
                
            except Exception as e:
                self.logger.error(f"Error in alert_processing_loop: {e}")
                await asyncio.sleep(5)
    
    async def health_check_loop(self):
        """Улучшенный цикл health check с поддержкой зависимостей и восстановления"""
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
                    
                    # Проверка зависимостей
                    deps_healthy, affected = await self.check_dependencies(component)
                    if not deps_healthy and affected:
                        for affected_component in affected:
                            await self.create_alert(
                                AlertLevel.WARNING,
                                affected_component,
                                f"Component {affected_component} affected by dependency failure",
                                {'dependency_failure': True, 'failed_dependencies': affected}
                            )
                    
                    # Попытка автовосстановления
                    if result.status in [ComponentStatus.OFFLINE, ComponentStatus.UNHEALTHY]:
                        if await self.auto_recover_component(component):
                            result.status = ComponentStatus.RECOVERING
                            result.recovery_attempts += 1
                    
                    # Создание алертов
                    await self.check_and_create_alerts(component, result)
                
                self.stats['last_health_check'] = datetime.now()
                self.stats['health_checks_performed'] += 1
                
                await asyncio.sleep(self.config.monitoring_interval)
                
            except Exception as e:
                self.logger.error(f"Error in health_check_loop: {e}")
                self.stats['monitoring_errors'] += 1
                await asyncio.sleep(5)
    
    async def export_dashboard_data(self, format: str = "json") -> str:
        """Экспорт данных дашборда в различных форматах"""
        dashboard_data = await self.generate_dashboard_data()
        
        if format == "json":
            return json.dumps(dashboard_data, indent=2, default=str)
        elif format == "csv":
            # Упрощенный CSV экспорт метрик
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Заголовки
            writer.writerow(['Timestamp', 'Metric', 'Value'])
            
            # Данные
            for metric_name, values in dashboard_data['recent_metrics'].items():
                for entry in values:
                    writer.writerow([
                        entry['timestamp'],
                        metric_name,
                        entry['value']
                    ])
            
            return output.getvalue()
        else:
            return str(dashboard_data)
    
    # Остальные методы остаются без изменений...
    
    async def initialize(self):
        """Инициализация протокола"""
        connector = aiohttp.TCPConnector(limit=20)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        self.logger.info("Monitoring Protocol Enhanced initialized")
    
    async def check_component_health(self, component: str, config: Dict) -> HealthMetric:
        """Проверка здоровья компонента"""
        start_time = time.time()
        
        try:
            if config.get('internal'):
                result = await self.check_system_resources()
            else:
                result = await self.check_http_health(component, config)
            
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
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            status = ComponentStatus.HEALTHY
            
            if (cpu_percent > self.thresholds['cpu_usage'] or 
                memory.percent > self.thresholds['memory_usage'] or 
                disk.percent > self.thresholds['disk_usage']):
                status = ComponentStatus.DEGRADED
            
            if cpu_percent > 95 or memory.percent > 95 or disk.percent > 95:
                status = ComponentStatus.UNHEALTHY
            
            return HealthMetric(
                component='system_resources',
                metric_name='resource_usage',
                value=max(cpu_percent, memory.percent, disk.percent),
                threshold=max(
                    self.thresholds['cpu_usage'],
                    self.thresholds['memory_usage'],
                    self.thresholds['disk_usage']
                ),
                status=status,
                timestamp=datetime.now(),
                details={
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'disk_percent': disk.percent
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
                response_time = (time.time() - start_time) * 1000
                
                if response.status == 200:
                    try:
                        data = await response.json()
                    except:
                        data = {}
                    
                    status = ComponentStatus.HEALTHY
                    if response_time > self.thresholds['response_time']:
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
                        details={'status_code': response.status}
                    )
                    
        except asyncio.TimeoutError:
            return HealthMetric(
                component=component,
                metric_name='http_health',
                value=0,
                threshold=1,
                status=ComponentStatus.OFFLINE,
                timestamp=datetime.now(),
                details={'error': 'timeout'}
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
        """Проверка и создание алертов"""
        if health.status == ComponentStatus.OFFLINE:
            level = AlertLevel.CRITICAL
            message = f"Component {component} is OFFLINE"
        elif health.status == ComponentStatus.UNHEALTHY:
            level = AlertLevel.ERROR
            message = f"Component {component} is UNHEALTHY"
        elif health.status == ComponentStatus.DEGRADED:
            level = AlertLevel.WARNING
            message = f"Component {component} is DEGRADED"
        elif health.status == ComponentStatus.RECOVERING:
            level = AlertLevel.INFO
            message = f"Component {component} is RECOVERING"
        else:
            await self.check_alert_resolution(component)
            return
        
        if self.monitored_components[component].get('critical') and level == AlertLevel.ERROR:
            level = AlertLevel.CRITICAL
        
        await self.create_alert(level, component, message, health.details)
    
    async def create_alert(self, level: AlertLevel, component: str, message: str, details: Dict[str, Any]):
        """Создание алерта"""
        alert_key = f"{component}:{message}"
        
        # Проверка существующего алерта
        for existing_alert in self.active_alerts.values():
            if (existing_alert.component == component and 
                existing_alert.message == message and 
                not existing_alert.resolved):
                return
        
        alert_id = hashlib.md5(f"{alert_key}:{time.time()}".encode()).hexdigest()[:12]
        
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
        
        if self.alert_counter:
            self.alert_counter.labels(level=level.value, component=component).inc()
        
        self.logger.warning(f"ALERT [{level.value.upper()}] {component}: {message}")
        
        await self.send_notifications(alert)
    
    async def send_notifications(self, alert: Alert):
        """Отправка уведомлений"""
        message = f"Alert: {alert.level.value.upper()}\n"
        message += f"Component: {alert.component}\n"
        message += f"Message: {alert.message}"
        
        if self.config.slack_webhook:
            await self.send_to_slack(message)
        
        if self.config.telegram_bot_token:
            await self.send_to_telegram(message)
    
    async def check_alert_resolution(self, component: str):
        """Проверка разрешения алертов"""
        if component not in self.component_statuses:
            return
        
        current_status = self.component_statuses[component]
        
        if current_status.status == ComponentStatus.HEALTHY:
            for alert_id, alert in list(self.active_alerts.items()):
                if alert.component == component and not alert.resolved:
                    alert.resolved = True
                    alert.resolution_time = datetime.now()
                    
                    resolution_duration = (alert.resolution_time - alert.timestamp).total_seconds()
                    self.stats['resolved_alerts'] += 1
                    
                    if self.stats['resolved_alerts'] > 0:
                        current_avg = self.stats['avg_resolution_time']
                        self.stats['avg_resolution_time'] = (
                            (current_avg * (self.stats['resolved_alerts'] - 1) + resolution_duration) / 
                            self.stats['resolved_alerts']
                        )
                    
                    self.logger.info(f"Alert {alert_id} resolved in {resolution_duration:.1f}s")
                    del self.active_alerts[alert_id]
    
    async def generate_dashboard_data(self) -> Dict[str, Any]:
        """Генерация данных дашборда"""
        return {
            'timestamp': datetime.now().isoformat(),
            'system_status': self.get_overall_system_status(),
            'component_statuses': {
                comp: {
                    'status': status.status.value,
                    'value': status.value,
                    'threshold': status.threshold,
                    'last_check': status.timestamp.isoformat(),
                    'recovery_attempts': status.recovery_attempts
                }
                for comp, status in self.component_statuses.items()
            },
            'active_alerts': [
                {
                    'id': alert.id,
                    'level': alert.level.value,
                    'component': alert.component,
                    'message': alert.message,
                    'timestamp': alert.timestamp.isoformat(),
                    'escalation_count': alert.escalation_count
                }
                for alert in self.active_alerts.values()
            ],
            'system_metrics': {
                'uptime': time.time() - self.stats['system_uptime'],
                'total_alerts': self.stats['total_alerts'],
                'resolved_alerts': self.stats['resolved_alerts'],
                'escalated_alerts': self.stats['escalated_alerts'],
                'avg_resolution_time': self.stats['avg_resolution_time'],
                'recovery_attempts': self.stats['recovery_attempts'],
                'successful_recoveries': self.stats['successful_recoveries']
            },
            'recent_metrics': self.get_recent_metrics()
        }
    
    def get_overall_system_status(self) -> str:
        """Определение общего статуса системы"""
        if not self.component_statuses:
            return ComponentStatus.UNKNOWN.value
        
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
        elif any(status == ComponentStatus.RECOVERING for status in critical_statuses):
            return ComponentStatus.RECOVERING.value
        elif any(status == ComponentStatus.DEGRADED for status in critical_statuses):
            return ComponentStatus.DEGRADED.value
        elif all(status == ComponentStatus.HEALTHY for status in critical_statuses):
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
    
    async def metrics_collection_loop(self):
        """Цикл сбора метрик с поддержкой кастомных метрик"""
        while self.running:
            try:
                metrics = await self.collect_performance_metrics()
                
                # Добавление кастомных метрик
                for metric_name, metric_config in self.custom_metrics.items():
                    if 'command' in metric_config:
                        # Выполнение команды для получения метрики
                        value = await self._execute_custom_metric(metric_config['command'])
                        if value is not None:
                            metrics[metric_name] = value
                
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
    
    async def _execute_custom_metric(self, command: str) -> Optional[float]:
        """Выполнение команды для получения кастомной метрики"""
        try:
            # Заглушка - в реальной системе здесь будет выполнение команды
            return 0.0
        except Exception as e:
            self.logger.error(f"Failed to execute custom metric: {e}")
            return None
    
    async def collect_performance_metrics(self) -> Dict[str, float]:
        """Сбор метрик производительности"""
        metrics = {}
        
        try:
            metrics['cpu_usage'] = psutil.cpu_percent()
            metrics['memory_usage'] = psutil.virtual_memory().percent
            metrics['disk_usage'] = psutil.disk_usage('/').percent
            
            net_io = psutil.net_io_counters()
            metrics['network_bytes_sent'] = net_io.bytes_sent
            metrics['network_bytes_recv'] = net_io.bytes_recv
            
            metrics['process_count'] = len(psutil.pids())
            metrics['active_alerts'] = len(self.active_alerts)
            metrics['health_checks'] = self.stats['health_checks_performed']
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")
        
        return metrics
    
    async def dashboard_update_loop(self):
        """Цикл обновления дашборда"""
        while self.running:
            try:
                dashboard_data = await self.generate_dashboard_data()
                
                # Сохранение в файл для веб-интерфейса
                with open('dashboard_data.json', 'w') as f:
                    json.dump(dashboard_data, f, indent=2, default=str)
                
                await asyncio.sleep(self.config.dashboard_update_interval)
                
            except Exception as e:
                self.logger.error(f"Error in dashboard_update_loop: {e}")
                await asyncio.sleep(5)
    
    async def cleanup_loop(self):
        """Цикл очистки старых данных"""
        while self.running:
            try:
                cutoff_time = datetime.now() - timedelta(seconds=self.config.metrics_retention)
                
                for metric_name, history in self.metrics_history.items():
                    while history and history[0]['timestamp'] < cutoff_time:
                        history.popleft()
                
                await asyncio.sleep(300)
                
            except Exception as e:
                self.logger.error(f"Error in cleanup_loop: {e}")
                await asyncio.sleep(300)
    
    async def start_monitoring(self):
        """Запуск мониторинга"""
        if self.running:
            return
        
        self.running = True
        
        if not self.session:
            await self.initialize()
        
        self.logger.info("Starting Enhanced Monitoring Protocol")
        
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
    
    async def stop_monitoring(self):
        """Остановка мониторинга"""
        self.running = False
        
        for task in self.tasks:
            task.cancel()
        
        if self.session:
            await self.session.close()
        
        self.logger.info("Monitoring Protocol stopped")
    
    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return self.stats
