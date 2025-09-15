"""
CORTEX v3.0 - GitHub API Protocol
Полная интеграция с GitHub для super-system-eyelids
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import base64
from urllib.parse import urljoin
import logging

# Настройка логирования
logger = logging.getLogger(__name__)

class GitHubOperation(Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    WEBHOOK = "webhook"
    BATCH = "batch"

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
    cache_ttl: int = 300  # 5 минут кэша
    max_concurrent_requests: int = 10

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
        if self.cache_key is None:
            # Генерируем ключ кэша для GET запросов
            if self.operation == GitHubOperation.READ:
                self.cache_key = f"{self.endpoint}:{json.dumps(self.params, sort_keys=True)}"

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

class GitHubAPIProtocol:
    """GitHub API Protocol для CORTEX v3.0"""
    
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
        
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'rate_limit_hits': 0,
            'cache_hits': 0,
            'average_response_time': 0,
            'last_request_time': 0,
            'webhooks_processed': 0
        }
        
    async def initialize(self):
        """Инициализация сессии и проверка токена"""
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300
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
    
    def _check_cache(self, cache_key: str) -> Optional[Any]:
        """Проверка кэша"""
        if cache_key in self.cache:
            data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.config.cache_ttl:
                self.stats['cache_hits'] += 1
                return data
            else:
                del self.cache[cache_key]
        return None
    
    def _update_cache(self, cache_key: str, data: Any):
        """Обновление кэша"""
        self.cache[cache_key] = (data, time.time())
        
        # Очистка старых записей
        current_time = time.time()
        expired_keys = [
            key for key, (_, ts) in self.cache.items()
            if current_time - ts > self.config.cache_ttl
        ]
        for key in expired_keys:
            del self.cache[key]
    
    async def _make_request(self, request: GitHubRequest) -> GitHubResponse:
        """Выполнение HTTP запроса с семафором для ограничения конкурентности"""
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
                
                # Обновляем rate limit информацию
                self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
                self.rate_limit_reset = int(response.headers.get('X-RateLimit-Reset', 0))
                
                # Обновляем статистику
                self._update_stats(response_time, response.status < 400)
                
                if response.status < 400:
                    data = await response.json() if response.content_type == 'application/json' else await response.text()
                    
                    # Обновляем кэш для успешных READ операций
                    if request.operation == GitHubOperation.READ and request.cache_key:
                        self._update_cache(request.cache_key, data)
                    
                    return GitHubResponse(
                        success=True,
                        status_code=response.status,
                        data=data,
                        rate_limit_remaining=self.rate_limit_remaining,
                        rate_limit_reset=self.rate_limit_reset,
                        response_time=response_time
                    )
                else:
                    error_data = await response.text()
                    
                    # Если rate limit - планируем retry
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
                    
                    return GitHubResponse(
                        success=False,
                        status_code=response.status,
                        error=error_data,
                        response_time=response_time
                    )
                    
        except asyncio.TimeoutError:
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
    
    async def execute_request(self, request: GitHubRequest) -> GitHubResponse:
        """Выполнение запроса с retry логикой"""
        response = await self._make_request(request)
        
        # Если запрос неуспешен и есть попытки retry
        if not response.success and request.retry_count < self.config.max_retries:
            if response.status_code in [429, 500, 502, 503, 504]:
                request.retry_count += 1
                
                # Вычисляем задержку для retry
                delay = self._calculate_retry_delay(request.retry_count, response.retry_after)
                
                logger.info(f"Retrying request (attempt {request.retry_count}/{self.config.max_retries}) after {delay}s")
                await asyncio.sleep(delay)
                
                return await self.execute_request(request)
        
        return response
    
    def _calculate_retry_delay(self, retry_count: int, retry_after: Optional[int] = None) -> float:
        """Вычисление задержки для retry"""
        if retry_after:
            return retry_after
            
        if self.config.retry_strategy == RetryStrategy.EXPONENTIAL:
            return min(2 ** retry_count, 60)
        elif self.config.retry_strategy == RetryStrategy.LINEAR:
            return retry_count * 2
        else:  # FIXED
            return 5
    
    def _get_http_method(self, operation: GitHubOperation) -> str:
        """Получение HTTP метода для операции"""
        mapping = {
            GitHubOperation.CREATE: 'POST',
            GitHubOperation.READ: 'GET',
            GitHubOperation.UPDATE: 'PATCH',
            GitHubOperation.DELETE: 'DELETE',
            GitHubOperation.SEARCH: 'GET',
            GitHubOperation.WEBHOOK: 'POST',
            GitHubOperation.BATCH: 'POST'
        }
        return mapping.get(operation, 'GET')
    
    async def _check_rate_limit(self) -> bool:
        """Проверка rate limit"""
        if self.rate_limit_remaining <= self.config.rate_limit_buffer:
            reset_time = datetime.fromtimestamp(self.rate_limit_reset)
            current_time = datetime.now()
            
            if current_time < reset_time:
                wait_time = (reset_time - current_time).total_seconds()
                logger.warning(f"Rate limit reached. Waiting {wait_time:.1f}s until reset...")
                await asyncio.sleep(wait_time + 1)
                
        return True
    
    def _update_stats(self, response_time: float, success: bool):
        """Обновление статистики"""
        self.stats['total_requests'] += 1
        self.stats['last_request_time'] = time.time()
        
        if success:
            self.stats['successful_requests'] += 1
        else:
            self.stats['failed_requests'] += 1
            
        # Обновляем среднее время ответа
        total_time = self.stats['average_response_time'] * (self.stats['total_requests'] - 1)
        self.stats['average_response_time'] = (total_time + response_time) / self.stats['total_requests']
    
    # ========== CRUD ОПЕРАЦИИ ДЛЯ РЕПОЗИТОРИЕВ ==========
    
    async def create_repository(self, name: str, description: str = "", private: bool = False, 
                              auto_init: bool = True) -> GitHubResponse:
        """Создание нового репозитория"""
        data = {
            'name': name,
            'description': description,
            'private': private,
            'auto_init': auto_init,
            'gitignore_template': 'Python'
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.CREATE,
            endpoint='/user/repos',
            data=data,
            priority=3
        )
        
        return await self.execute_request(request)
    
    async def get_repository(self, owner: str, repo: str) -> GitHubResponse:
        """Получение информации о репозитории"""
        request = GitHubRequest(
            operation=GitHubOperation.READ,
            endpoint=f'/repos/{owner}/{repo}',
            priority=5
        )
        
        return await self.execute_request(request)
    
    async def update_repository(self, owner: str, repo: str, **kwargs) -> GitHubResponse:
        """Обновление репозитория"""
        request = GitHubRequest(
            operation=GitHubOperation.UPDATE,
            endpoint=f'/repos/{owner}/{repo}',
            data=kwargs,
            priority=4
        )
        
        return await self.execute_request(request)
    
    async def delete_repository(self, owner: str, repo: str) -> GitHubResponse:
        """Удаление репозитория"""
        request = GitHubRequest(
            operation=GitHubOperation.DELETE,
            endpoint=f'/repos/{owner}/{repo}',
            priority=1
        )
        
        return await self.execute_request(request)
    
    # ========== ОПЕРАЦИИ С ФАЙЛАМИ ==========
    
    async def create_file(self, owner: str, repo: str, path: str, content: str, 
                         message: str, branch: str = None) -> GitHubResponse:
        """Создание файла в репозитории"""
        if not branch:
            branch = self.config.default_branch
            
        encoded_content = base64.b64encode(content.encode()).decode()
        
        data = {
            'message': message,
            'content': encoded_content,
            'branch': branch
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.CREATE,
            endpoint=f'/repos/{owner}/{repo}/contents/{path}',
            data=data,
            priority=4
        )
        
        return await self.execute_request(request)
    
    async def get_file(self, owner: str, repo: str, path: str, ref: str = None) -> GitHubResponse:
        """Получение файла из репозитория"""
        params = {'ref': ref} if ref else None
        
        request = GitHubRequest(
            operation=GitHubOperation.READ,
            endpoint=f'/repos/{owner}/{repo}/contents/{path}',
            params=params,
            priority=5
        )
        
        response = await self.execute_request(request)
        
        # Декодируем контент если успешно
        if response.success and isinstance(response.data, dict) and 'content' in response.data:
            encoded_content = response.data['content']
            decoded_content = base64.b64decode(encoded_content).decode('utf-8')
            response.data['decoded_content'] = decoded_content
        
        return response
    
    async def update_file(self, owner: str, repo: str, path: str, content: str, 
                         message: str, sha: str, branch: str = None) -> GitHubResponse:
        """Обновление файла в репозитории"""
        if not branch:
            branch = self.config.default_branch
            
        encoded_content = base64.b64encode(content.encode()).decode()
        
        data = {
            'message': message,
            'content': encoded_content,
            'sha': sha,
            'branch': branch
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.UPDATE,
            endpoint=f'/repos/{owner}/{repo}/contents/{path}',
            data=data,
            priority=4
        )
        
        return await self.execute_request(request)
    
    async def delete_file(self, owner: str, repo: str, path: str, message: str, 
                         sha: str, branch: str = None) -> GitHubResponse:
        """Удаление файла из репозитория"""
        if not branch:
            branch = self.config.default_branch
            
        data = {
            'message': message,
            'sha': sha,
            'branch': branch
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.DELETE,
            endpoint=f'/repos/{owner}/{repo}/contents/{path}',
            data=data,
            priority=3
        )
        
        return await self.execute_request(request)
    
    # ========== BATCH ОПЕРАЦИИ ==========
    
    async def batch_create_files(self, owner: str, repo: str, files: List[Dict[str, str]], 
                                message: str, branch: str = None) -> List[GitHubResponse]:
        """Пакетное создание файлов"""
        results = []
        
        for file_info in files:
            response = await self.create_file(
                owner, repo,
                file_info['path'],
                file_info['content'],
                message,
                branch
            )
            results.append(response)
            
            # Небольшая задержка между запросами
            await asyncio.sleep(0.1)
        
        return results
    
    # ========== WEBHOOK ОПЕРАЦИИ ==========
    
    async def create_webhook(self, owner: str, repo: str, url: str, 
                           events: List[str] = None, secret: str = None) -> GitHubResponse:
        """Создание webhook"""
        if not events:
            events = ['push', 'pull_request', 'issues']
            
        config = {
            'url': url,
            'content_type': 'json'
        }
        
        if secret or self.config.webhook_secret:
            config['secret'] = secret or self.config.webhook_secret
            
        data = {
            'name': 'web',
            'active': True,
            'events': events,
            'config': config
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.WEBHOOK,
            endpoint=f'/repos/{owner}/{repo}/hooks',
            data=data,
            priority=3
        )
        
        return await self.execute_request(request)
    
    async def list_webhooks(self, owner: str, repo: str) -> GitHubResponse:
        """Список webhooks репозитория"""
        request = GitHubRequest(
            operation=GitHubOperation.READ,
            endpoint=f'/repos/{owner}/{repo}/hooks',
            priority=5
        )
        
        return await self.execute_request(request)
    
    async def delete_webhook(self, owner: str, repo: str, hook_id: int) -> GitHubResponse:
        """Удаление webhook"""
        request = GitHubRequest(
            operation=GitHubOperation.DELETE,
            endpoint=f'/repos/{owner}/{repo}/hooks/{hook_id}',
            priority=3
        )
        
        return await self.execute_request(request)
    
    def register_webhook_handler(self, event_type: str, handler: callable):
        """Регистрация обработчика webhook"""
        self.webhook_handlers[event_type] = handler
        logger.info(f"Webhook handler registered for: {event_type}")
    
    async def process_webhook(self, payload: Dict, headers: Dict) -> bool:
        """Обработка входящего webhook"""
        event_type = headers.get('X-GitHub-Event')
        
        if event_type in self.webhook_handlers:
            try:
                await self.webhook_handlers[event_type](payload, headers)
                self.stats['webhooks_processed'] += 1
                return True
            except Exception as e:
                logger.error(f"Webhook handler error for {event_type}: {e}")
                return False
        
        logger.warning(f"No handler for webhook event: {event_type}")
        return False
    
    # ========== ПОИСК ==========
    
    async def search_repositories(self, query: str, sort: str = 'updated', 
                                order: str = 'desc', per_page: int = 30) -> GitHubResponse:
        """Поиск репозиториев"""
        params = {
            'q': query,
            'sort': sort,
            'order': order,
            'per_page': per_page
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.SEARCH,
            endpoint='/search/repositories',
            params=params,
            priority=6
        )
        
        return await self.execute_request(request)
    
    async def search_code(self, query: str, sort: str = 'indexed', 
                         order: str = 'desc', per_page: int = 30) -> GitHubResponse:
        """Поиск кода"""
        params = {
            'q': query,
            'sort': sort,
            'order': order,
            'per_page': per_page
        }
        
        request = GitHubRequest(
            operation=GitHubOperation.SEARCH,
            endpoint='/search/code',
            params=params,
            priority=6
        )
        
        return await self.execute_request(request)
    
    # ========== УТИЛИТЫ ==========
    
    def get_stats(self) -> Dict:
        """Получение статистики протокола"""
        success_rate = 0
        if self.stats['total_requests'] > 0:
            success_rate = (self.stats['successful_requests'] / self.stats['total_requests']) * 100
            
        return {
            **self.stats,
            'success_rate': round(success_rate, 2),
            'cache_hit_rate': round((self.stats['cache_hits'] / max(1, self.stats['total_requests'])) * 100, 2),
            'rate_limit_remaining': self.rate_limit_remaining,
            'rate_limit_reset': datetime.fromtimestamp(self.rate_limit_reset).isoformat() if self.rate_limit_reset else None,
            'cache_size': len(self.cache)
        }
    
    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()
            logger.info("GitHub API Protocol session closed")


# ========== ПРИМЕР ИСПОЛЬЗОВАНИЯ ==========

async def example_usage():
    """Пример использования GitHub API Protocol"""
    
    config = GitHubConfig(
        token="your_github_token_here",
        max_retries=3,
        retry_strategy=RetryStrategy.EXPONENTIAL,
        cache_ttl=300
    )
    
    protocol = GitHubAPIProtocol(config)
    
    try:
        # Инициализация
        await protocol.initialize()
        
        # Создание репозитория
        repo_response = await protocol.create_repository(
            name="cortex-test-repo",
            description="Test repository for CORTEX v3.0",
            private=False
        )
        
        if repo_response.success:
            print(f"Repository created: {repo_response.data['html_url']}")
            
            # Создание файла
            file_response = await protocol.create_file(
                owner="guannko",
                repo="cortex-test-repo",
                path="README.md",
                content="# CORTEX v3.0 Test Repository\n\nThis is a test.",
                message="Initial commit"
            )
            
            if file_response.success:
                print("File created successfully")
            
            # Batch создание файлов
            files = [
                {'path': 'src/main.py', 'content': 'print("Hello CORTEX")'},
                {'path': 'src/config.py', 'content': 'VERSION = "3.0"'},
                {'path': 'docs/README.md', 'content': '# Documentation'}
            ]
            
            batch_results = await protocol.batch_create_files(
                owner="guannko",
                repo="cortex-test-repo",
                files=files,
                message="Add initial files"
            )
            
            print(f"Batch created {len([r for r in batch_results if r.success])} files")
        
        # Поиск репозиториев
        search_response = await protocol.search_repositories(
            query="machine learning python",
            sort="stars",
            per_page=5
        )
        
        if search_response.success:
            print(f"Found {search_response.data['total_count']} repositories")
        
        # Регистрация webhook handler
        async def handle_push(payload, headers):
            print(f"Push event received: {payload.get('ref')}")
        
        protocol.register_webhook_handler('push', handle_push)
        
        # Статистика
        stats = protocol.get_stats()
        print(f"Protocol stats: {json.dumps(stats, indent=2)}")
        
    finally:
        await protocol.close()


if __name__ == "__main__":
    asyncio.run(example_usage())
