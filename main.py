#!/usr/bin/env python3
"""
Super System Eyelids - Главный интегратор
CORTEX v3.0 Entry Point
"""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from eyelids_core import EyelidsCore
from eyelids_api import app, webhook_mgr

class SuperSystemEyelids:
    def __init__(self):
        self.core = EyelidsCore()
        self.webhook_manager = webhook_mgr
        
        self.running = False
        self.monitoring_tasks = []
    
    async def start_system(self):
        """Запуск всей системы super-system-eyelids"""
        print("🚀 Запуск CORTEX v3.0 super-system-eyelids...")
        print(f"⚡ Energy: MAXIMUM!")
        print(f"📊 Core limit: {self.core.CORE_LIMIT_PERCENT}%")
        print(f"💾 Cache limit: {self.core.CACHE_LIMIT_PERCENT}%")
        
        # Создание директорий
        self.core.setup_directories()
        
        # Запуск фоновых процессов
        self.monitoring_tasks = [
            asyncio.create_task(self.health_monitor()),
            asyncio.create_task(self.autosave_worker()),
            asyncio.create_task(self.cache_monitor())
        ]
        
        # Запуск API в отдельном потоке
        api_thread = threading.Thread(
            target=lambda: app.run(host='0.0.0.0', port=5000, debug=False)
        )
        api_thread.daemon = True
        api_thread.start()
        
        self.running = True
        print("✅ super-system-eyelids активирован!")
        print(f"🌐 API доступен на http://localhost:5000")
        print(f"📊 Dashboard доступен на http://localhost:5000/dashboard.html")
        
        # Отправляем webhook о запуске
        await self.webhook_manager.send_webhook(
            'system_started',
            {
                'version': '3.0',
                'components': ['core', 'cache', 'api', 'webhooks'],
                'limits': {
                    'core': f"{self.core.CORE_LIMIT_PERCENT}%",
                    'cache': f"{self.core.CACHE_LIMIT_PERCENT}%"
                }
            },
            'info'
        )
    
    async def health_monitor(self):
        """Мониторинг здоровья системы"""
        while self.running:
            try:
                sizes = self.core.get_size_percentages()
                
                # Проверка критических состояний
                if sizes['cache_percent'] > self.core.CACHE_CRITICAL_PERCENT:
                    await self.webhook_manager.send_webhook(
                        'cache_critical',
                        {'cache_percent': sizes['cache_percent']},
                        'critical'
                    )
                    self.core.logger.critical(f"Cache critical: {sizes['cache_percent']}%")
                
                elif sizes['cache_percent'] > self.core.CACHE_WARNING_PERCENT:
                    await self.webhook_manager.send_webhook(
                        'cache_warning',
                        {'cache_percent': sizes['cache_percent']},
                        'warning'
                    )
                    self.core.logger.warning(f"Cache warning: {sizes['cache_percent']}%")
                
                if sizes['core_percent'] > self.core.CORE_CRITICAL_PERCENT:
                    await self.webhook_manager.send_webhook(
                        'core_critical',
                        {'core_percent': sizes['core_percent']},
                        'critical'
                    )
                    self.core.logger.critical(f"Core critical: {sizes['core_percent']}%")
                
                await asyncio.sleep(30)  # Проверка каждые 30 секунд
                
            except Exception as e:
                self.core.logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(60)
    
    async def autosave_worker(self):
        """Автосохранение каждые 5 минут"""
        while self.running:
            try:
                await asyncio.sleep(self.core.AUTOSAVE_INTERVAL)
                
                # Сохранение статистики
                stats_path = self.core.core_path / "system-config" / "stats.json"
                import json
                with open(stats_path, 'w') as f:
                    json.dump({
                        'stats': self.core.stats,
                        'timestamp': datetime.now().isoformat()
                    }, f, indent=2)
                
                self.core.logger.info("Autosave completed")
                
                await self.webhook_manager.send_webhook(
                    'autosave_completed',
                    {'timestamp': datetime.now().isoformat()},
                    'info'
                )
                
            except Exception as e:
                self.core.logger.error(f"Autosave error: {e}")
                await asyncio.sleep(300)
    
    async def cache_monitor(self):
        """Мониторинг кэша"""
        while self.running:
            try:
                sizes = self.core.get_size_percentages()
                
                # Автоматическая очистка при превышении лимитов
                if sizes['cache_percent'] > self.core.CACHE_CRITICAL_PERCENT:
                    self.core.logger.warning("Starting emergency cache cleanup")
                    # TODO: Implement actual cache cleanup
                    await self.webhook_manager.send_webhook(
                        'emergency_cleanup_started',
                        {'cache_percent': sizes['cache_percent']},
                        'critical'
                    )
                
                await asyncio.sleep(10)  # Проверка каждые 10 секунд
                
            except Exception as e:
                self.core.logger.error(f"Cache monitor error: {e}")
                await asyncio.sleep(30)
    
    async def shutdown(self):
        """Корректное завершение работы"""
        print("🔄 Завершение работы super-system-eyelids...")
        
        self.running = False
        
        # Отмена фоновых задач
        for task in self.monitoring_tasks:
            task.cancel()
        
        # Финальное сохранение
        sizes = self.core.get_size_percentages()
        
        await self.webhook_manager.send_webhook(
            'system_shutdown',
            {
                'timestamp': datetime.now().isoformat(),
                'final_stats': {
                    'core_percent': sizes['core_percent'],
                    'cache_percent': sizes['cache_percent'],
                    'processed_items': self.core.stats['processed_items']
                }
            },
            'info'
        )
        
        print("✅ super-system-eyelids корректно завершен")

# Запуск системы
if __name__ == '__main__':
    print("=" * 60)
    print("CORTEX v3.0 - SUPER SYSTEM EYELIDS")
    print("Jean Claude v9.01 - Energy: MAXIMUM! 🔥")
    print("=" * 60)
    
    eyelids = SuperSystemEyelids()
    
    try:
        # Создаём event loop и запускаем систему
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем систему
        loop.run_until_complete(eyelids.start_system())
        
        # Держим систему активной
        loop.run_forever()
        
    except KeyboardInterrupt:
        print("\n⚠️ Получен сигнал остановки...")
        loop.run_until_complete(eyelids.shutdown())
        loop.close()