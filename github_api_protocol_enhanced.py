"""
CORTEX v3.0 - GitHub API Protocol ENHANCED
С критическими улучшениями от Mistral
"""

import asyncio
import aiohttp
import json
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import base64
from urllib.parse import urljoin
from functools import lru_cache
import logging
from pathlib import Path

# Prometheus метрики (опционально)
try:
    from prometheus_client import Counter, Gauge, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("GitHubAPIProtocol")

class GitHubOperation(Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    WEBHOOK = "webhook"
    BATCH = "batch"
    GRAPHQL = "graphql"

class RetryStrategy(Enum):
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIXED = "fixed"

@dataclass
class GitHubConfig:
    token: str
    base_url: str = "https://api.github.com"
    timeout: int = 30
    max_retries: int = 3
    retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    rate_limit_buffer: int = 100
    webhook_secret: Optional[str] = None
    default_branch: str = "main"
    cache_ttl: int = 300
    max_concurrent_requests: int = 10
    max_connections: int = 100
    max_connections_per_host: int = 20
    log_file: Optional[str] = "github_api.log"
    enable_prometheus: bool = True

@dataclass
class GitHubRequest:
    operation: GitHubOperation
    endpoint: str
    data: Optional[Dict] = None
    params: Optional[Dict] = None
    headers: Optional[Dict] = None
    priority: int = 5
    retry_count: int = 0
    created_at: float = None
    cache_key: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.cache_key is None and self.operation == GitHubOperation.READ:
            self.cache_key = f"{self.endpoint}:{json.dumps(self.params or {}, sort_keys=True)}"

@dataclass
class GitHubResponse:
    success: bool
    status_code: int
    data: Optional[Any] = None
    error: Optional[str] = None
    rate_limit_remaining: int = 0
    rate_limit_reset: int = 0
    retry_after: Optional[int] = None
    response_time: float = 0
    from_cache: bool = False
    links: Optional[Dict] = None  # Для пагинации

class GitHubAPIProtocolEnhanced:
    """Enhanced GitHub API Protocol с улучшениями от Mistral"""
    
    def __init__(self, config: GitHubConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = 0
        self.request_queue = asyncio.Queue()
        self.priority_queue = asyncio.Queue()
        self.webhook_handlers: Dict[str, callable] = {}
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        
        # Настройка логирования в файл
        if config.log_file:
            file_handler = logging.FileHandler(config.log_file)
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        # Prometheus метрики
        if PROMETHEUS_AVAILABLE and config.enable_prometheus:
            self.request_counter = Counter(
                "github_requests_total",
                "Total GitHub API requests",
                ["method", "endpoint", "status"]
            )
            self.request_latency = Histogram(
                "github_request_latency_seconds",
                "GitHub API request latency",
                ["method", "endpoint"]
            )
            self.rate_limit_gauge = Gauge(
                "github_rate_limit_remaining",
                "GitHub API rate limit remaining"
            )
            self.cache_hit_counter = Counter(
                "github_cache_hits_total",
                "Total cache hits"
            )
        else:
            self.request_counter = None
            self.request_latency = None
            self.rate_limit_gauge = None
            self.cache_hit_counter = None
        
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'rate_limit_hits': 0,
            'cache_hits': 0,
            'average_response_time': 0,
            'last_request_time': 0,
            'webhooks_processed': 0,
            'webhooks_verified': 0
        }
        
    async def initialize(self):
        """Инициализация сессии с пулом соединений"""
        connector = aiohttp.TCPConnector(
            limit=self.config.max_connections,
            limit_per_host=self.config.max_connections_per_host,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'Authorization': f'token {self.config.token}',
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'CORTEX-v3.0-SuperSystemEyelids'
            }
        )
        
        # Проверяем валидность токена
        test_response = await self._make_request(
            GitHubRequest(GitHubOperation.READ, '/user')
        )
        
        if not test_response.success:
            raise Exception(f"GitHub token validation failed: {test_response.error}")
            
        logger.info(f"GitHub API Protocol initialized. User: {test_response.data.get('login')}")
        return True
    
    # ========== БЕЗОПАСНОСТЬ WEBHOOK ==========
    
    def verify_webhook_signature(self, payload: bytes, signature_header: str, secret: str) -> bool:
        """Проверка подписи webhook"""
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        
        signature = signature_header.split("=")[1]
        computed_signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_signature, signature)
    
    # ========== КЭШИРОВАНИЕ ==========
    
    @lru_cache(maxsize=128)
    def _get_cache_key(self, endpoint: str, params: str) -> str:
        """Генерация ключа кэша"""
        return f"{endpoint}:{params}"
    
    def _check_cache(self, cache_key: str) -> Optional[Any]:
        """Проверка кэша с учётом TTL"""
        if cache_key in self.cache:
            data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.config.cache_ttl:
                self.stats['cache_hits'] += 1
                if self.cache_hit_counter:
                    self.cache_hit_counter.inc()
                return data
            else:
                del self.cache[cache_key]
        return None
    
    def _update_cache(self, cache_key: str, data: Any):
        """Обновление кэша с очисткой старых записей"""
        self.cache[cache_key] = (data, time.time())
        
        # Очистка старых записей (каждые 100 записей)
        if len(self.cache) % 100 == 0:
            current_time = time.time()
            expired_keys = [
                key for key, (_, ts) in self.cache.items()
                if current_time - ts > self.config.cache_ttl
            ]
            for key in expired_keys:
                del self.cache[key]
    
    # ========== HTTP ЗАПРОСЫ ==========
    
    async def _make_request(self, request: GitHubRequest) -> GitHubResponse:
        """Выполнение HTTP запроса с семафором"""
        async with self.semaphore:
            return await self._make_request_internal(request)
    
    async def _make_request_internal(self, request: GitHubRequest) -> GitHubResponse:
        """Внутренняя реализация HTTP запроса"""
        if not self.session:
            await self.initialize()
            
        start_time = time.time()
        
        # Проверяем кэш для READ операций
        if request.operation == GitHubOperation.READ and request.cache_key:
            cached_data = self._check_cache(request.cache_key)
            if cached_data is not None:
                logger.debug(f"Cache hit for {request.cache_key}")
                return GitHubResponse(
                    success=True,
                    status_code=200,
                    data=cached_data,
                    response_time=0,
                    from_cache=True
                )
        
        # Проверяем rate limit
        if not await self._check_rate_limit():
            return GitHubResponse(
                success=False,
                status_code=429,
                error="Rate limit exceeded",
                rate_limit_remaining=self.rate_limit_remaining
            )
        
        url = urljoin(self.config.base_url, request.endpoint)
        method = self._get_http_method(request.operation)
        
        try:
            kwargs = {
                'params': request.params,
                'headers': request.headers or {}
            }
            
            if request.data and method in ['POST', 'PUT', 'PATCH']:
                kwargs['json'] = request.data
            
            async with self.session.request(method, url, **kwargs) as response:
                response_time = time.time() - start_time
                
                # Обновляем rate limit
                self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
                self.rate_limit_reset = int(response.headers.get('X-RateLimit-Reset', 0))
                
                # Парсим Link header для пагинации
                links = self._parse_link_header(response.headers.get('Link', ''))
                
                # Обновляем статистику
                self._update_stats(request, response_time, response.status < 400)
                
                if response.status < 400:
                    data = await response.json() if response.content_type == 'application/json' else await response.text()
                    
                    # Обновляем кэш
                    if request.operation == GitHubOperation.READ and request.cache_key:
                        self._update_cache(request.cache_key, data)
                    
                    return GitHubResponse(
                        success=True,
                        status_code=response.status,
                        data=data,
                        rate_limit_remaining=self.rate_limit_remaining,
                        rate_limit_reset=self.rate_limit_reset,
                        response_time=response_time,
                        links=links
                    )
                else:
                    error_data = await response.text()
                    
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        self.stats['rate_limit_hits'] += 1
                        
                        return GitHubResponse(
                            success=False,
                            status_code=response.status,
                            error=f"Rate limit exceeded: {error_data}",
                            retry_after=retry_after,
                            response_time=response_time
                        )
                    
                    logger.error(f"Request failed: {response.status} - {error_data}")
                    return GitHubResponse(
                        success=False,
                        status_code=response.status,
                        error=error_data,
                        response_time=response_time
                    )
                    
        except asyncio.TimeoutError:
            logger.error(f"Request timeout for {url}")
            return GitHubResponse(
                success=False,
                status_code=408,
                error="Request timeout",
                response_time=time.time() - start_time
            )
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return GitHubResponse(
                success=False,
                status_code=500,
                error=f"Request failed: {str(e)}",
                response_time=time.time() - start_time
            )
    
    def _parse_link_header(self, link_header: str) -> Dict[str, str]:
        """Парсинг Link header для пагинации"""
        links = {}
        if not link_header:
            return links
        
        for link in link_header.split(','):
            parts = link.split(';')
            if len(parts) == 2:
                url = parts[0].strip()[1:-1]  # Убираем < и >
                rel = parts[1].split('=')[1].strip()[1:-1]  # Убираем кавычки
                links[rel] = url
        
        return links
    
    def _update_stats(self, request: GitHubRequest, response_time: float, success: bool):
        """Обновление статистики с Prometheus метриками"""
        self.stats['total_requests'] += 1
        self.stats['last_request_time'] = time.time()
        
        if success:
            self.stats['successful_requests'] += 1
        else:
            self.stats['failed_requests'] += 1
            
        # Среднее время ответа
        total_time = self.stats['average_response_time'] * (self.stats['total_requests'] - 1)
        self.stats['average_response_time'] = (total_time + response_time) / self.stats['total_requests']
        
        # Prometheus метрики
        if self.request_counter:
            method = self._get_http_method(request.operation)
            status = "success" if success else "error"
            self.request_counter.labels(method, request.endpoint, status).inc()
        
        if self.request_latency:
            method = self._get_http_method(request.operation)
            self.request_latency.labels(method, request.endpoint).observe(response_time)
        
        if self.rate_limit_gauge:
            self.rate_limit_gauge.set(self.rate_limit_remaining)
    
    # ========== GRAPHQL ПОДДЕРЖКА ==========
    
    async def execute_graphql(self, query: str, variables: Dict = None) -> GitHubResponse:
        """Выполнение GraphQL запроса"""
        data = {"query": query}
        if variables:
            data["variables"] = variables
        
        request = GitHubRequest(
            operation=GitHubOperation.GRAPHQL,
            endpoint="/graphql",
            data=data,
            headers={"Accept": "application/vnd.github.v4+json"},
            priority=5
        )
        
        return await self.execute_request(request)
    
    # ========== ПОИСК С ПАГИНАЦИЕЙ ==========
    
    async def search_repositories_paginated(
        self,
        query: str,
        sort: str = "updated",
        order: str = "desc",
        per_page: int = 30,
        max_results: int = None
    ) -> List[Dict]:
        """Поиск репозиториев с автоматической пагинацией"""
        all_results = []
        page = 1
        
        while True:
            params = {
                "q": query,
                "sort": sort,
                "order": order,
                "per_page": per_page,
                "page": page
            }
            
            request = GitHubRequest(
                operation=GitHubOperation.SEARCH,
                endpoint="/search/repositories",
                params=params,
                priority=6
            )
            
            response = await self.execute_request(request)
            
            if not response.success:
                logger.error(f"Search failed at page {page}: {response.error}")
                break
            
            items = response.data.get("items", [])
            all_results.extend(items)
            
            # Проверяем лимит результатов
            if max_results and len(all_results) >= max_results:
                all_results = all_results[:max_results]
                break
            
            # Проверяем наличие следующей страницы
            if not response.links or "next" not in response.links:
                break
            
            page += 1
            
            # Небольшая задержка между страницами
            await asyncio.sleep(0.5)
        
        logger.info(f"Search completed: {len(all_results)} repositories found")
        return all_results
    
    # ========== WEBHOOK С ПРОВЕРКОЙ ПОДПИСИ ==========
    
    async def process_webhook(self, payload: bytes, headers: Dict) -> bool:
        """Обработка webhook с проверкой подписи"""
        event_type = headers.get('X-GitHub-Event')
        
        # Проверка подписи
        if self.config.webhook_secret:
            signature_header = headers.get("X-Hub-Signature-256", "")
            if not self.verify_webhook_signature(payload, signature_header, self.config.webhook_secret):
                logger.warning(f"Invalid webhook signature for event {event_type}")
                return False
            self.stats['webhooks_verified'] += 1
        
        # Обработка события
        if event_type in self.webhook_handlers:
            try:
                payload_dict = json.loads(payload) if isinstance(payload, bytes) else payload
                await self.webhook_handlers[event_type](payload_dict, headers)
                self.stats['webhooks_processed'] += 1
                logger.info(f"Webhook processed: {event_type}")
                return True
            except Exception as e:
                logger.error(f"Webhook handler error for {event_type}: {e}")
                return False
        
        logger.warning(f"No handler for webhook event: {event_type}")
        return False
    
    # Остальные методы остаются без изменений...
    
    def _get_http_method(self, operation: GitHubOperation) -> str:
        """Получение HTTP метода для операции"""
        mapping = {
            GitHubOperation.CREATE: 'POST',
            GitHubOperation.READ: 'GET',
            GitHubOperation.UPDATE: 'PATCH',
            GitHubOperation.DELETE: 'DELETE',
            GitHubOperation.SEARCH: 'GET',
            GitHubOperation.WEBHOOK: 'POST',
            GitHubOperation.BATCH: 'POST',
            GitHubOperation.GRAPHQL: 'POST'
        }
        return mapping.get(operation, 'GET')
    
    async def _check_rate_limit(self) -> bool:
        """Проверка rate limit"""
        if self.rate_limit_remaining <= self.config.rate_limit_buffer:
            reset_time = datetime.fromtimestamp(self.rate_limit_reset)
            current_time = datetime.now()
            
            if current_time < reset_time:
                wait_time = (reset_time - current_time).total_seconds()
                logger.warning(f"Rate limit reached. Waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time + 1)
                
        return True
    
    def _calculate_retry_delay(self, retry_count: int, retry_after: Optional[int] = None) -> float:
        """Вычисление задержки для retry"""
        if retry_after:
            return retry_after
            
        if self.config.retry_strategy == RetryStrategy.EXPONENTIAL:
            return min(2 ** retry_count, 60)
        elif self.config.retry_strategy == RetryStrategy.LINEAR:
            return retry_count * 2
        else:
            return 5
    
    async def execute_request(self, request: GitHubRequest) -> GitHubResponse:
        """Выполнение запроса с retry логикой"""
        response = await self._make_request(request)
        
        if not response.success and request.retry_count < self.config.max_retries:
            if response.status_code in [429, 500, 502, 503, 504]:
                request.retry_count += 1
                delay = self._calculate_retry_delay(request.retry_count, response.retry_after)
                
                logger.info(f"Retrying request (attempt {request.retry_count}/{self.config.max_retries})")
                await asyncio.sleep(delay)
                
                return await self.execute_request(request)
        
        return response
    
    def get_stats(self) -> Dict:
        """Получение расширенной статистики"""
        success_rate = 0
        if self.stats['total_requests'] > 0:
            success_rate = (self.stats['successful_requests'] / self.stats['total_requests']) * 100
            
        return {
            **self.stats,
            'success_rate': round(success_rate, 2),
            'cache_hit_rate': round((self.stats['cache_hits'] / max(1, self.stats['total_requests'])) * 100, 2),
            'rate_limit_remaining': self.rate_limit_remaining,
            'rate_limit_reset': datetime.fromtimestamp(self.rate_limit_reset).isoformat() if self.rate_limit_reset else None,
            'cache_size': len(self.cache),
            'webhook_verification_rate': round((self.stats['webhooks_verified'] / max(1, self.stats['webhooks_processed'])) * 100, 2) if self.stats['webhooks_processed'] > 0 else 0
        }
    
    async def close(self):
        """Закрытие сессии и очистка ресурсов"""
        if self.session:
            await self.session.close()
            logger.info("GitHub API Protocol session closed")


# Пример использования остаётся без изменений
