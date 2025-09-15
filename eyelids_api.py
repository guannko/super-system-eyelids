#!/usr/bin/env python3
"""
API для управления super-system-eyelids
Webhooks, приоритеты, метрики
"""

from flask import Flask, request, jsonify
import asyncio
import aiohttp
import json
from datetime import datetime
from eyelids_core import EyelidsCore
# from cache_manager import CacheManager
# from reflex_protocols import ReflexProtocolSystem

app = Flask(__name__)
eyelids = EyelidsCore()

class WebhookManager:
    def __init__(self):
        self.webhooks = {
            'critical': [],
            'warning': [],
            'info': []
        }
        self.webhook_history = []
    
    async def send_webhook(self, event_type, data, priority='info'):
        """Отправка webhook уведомлений"""
        webhook_data = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'priority': priority,
            'data': data,
            'source': 'super-system-eyelids'
        }
        
        urls = self.webhooks.get(priority, [])
        
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.post(url, json=webhook_data, timeout=5) as response:
                        if response.status == 200:
                            self.webhook_history.append({
                                'url': url,
                                'status': 'success',
                                'timestamp': datetime.now().isoformat()
                            })
                except Exception as e:
                    self.webhook_history.append({
                        'url': url,
                        'status': 'failed',
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    })

webhook_mgr = WebhookManager()

# API Endpoints
@app.route('/api/v1/status', methods=['GET'])
def get_status():
    """Получить статус системы"""
    sizes = eyelids.get_size_percentages()
    return jsonify({
        'status': 'active',
        'core_usage': sizes['core_percent'],
        'cache_usage': sizes['cache_percent'],
        'total_usage': sizes['total_percent'],
        'stats': eyelids.stats,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/v1/cache/force-cleanup', methods=['POST'])
def force_cleanup():
    """Принудительная очистка кэша"""
    data = request.json
    cleanup_type = data.get('type', 'soft')  # soft, hard, emergency
    
    # TODO: Implement actual cleanup
    result = {'freed_space': 0, 'type': cleanup_type}
    
    # Send webhook notification
    asyncio.create_task(webhook_mgr.send_webhook(
        'cache_cleanup',
        {'type': cleanup_type, 'result': result},
        'warning' if cleanup_type != 'emergency' else 'critical'
    ))
    
    return jsonify({'success': True, 'result': result})

@app.route('/api/v1/webhooks/register', methods=['POST'])
def register_webhook():
    """Регистрация webhook URL"""
    data = request.json
    url = data.get('url')
    priority = data.get('priority', 'info')
    
    if not url or priority not in ['critical', 'warning', 'info']:
        return jsonify({'error': 'Invalid url or priority'}), 400
    
    webhook_mgr.webhooks[priority].append(url)
    
    return jsonify({
        'success': True,
        'registered_url': url,
        'priority': priority
    })

@app.route('/api/v1/metrics/export', methods=['GET'])
def export_metrics():
    """Экспорт метрик для мониторинга"""
    sizes = eyelids.get_size_percentages()
    metrics = {
        'core_metrics': {
            'usage_percent': sizes['core_percent'],
            'size_bytes': sizes['core_bytes']
        },
        'cache_metrics': {
            'usage_percent': sizes['cache_percent'],
            'size_bytes': sizes['cache_bytes']
        },
        'system_stats': eyelids.stats,
        'webhook_metrics': {
            'registered_webhooks': sum(len(urls) for urls in webhook_mgr.webhooks.values()),
            'recent_deliveries': webhook_mgr.webhook_history[-50:]
        },
        'timestamp': datetime.now().isoformat()
    }
    
    return jsonify(metrics)

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    sizes = eyelids.get_size_percentages()
    
    # Determine health status
    if sizes['cache_percent'] > 2.0 or sizes['core_percent'] > 7.0:
        status = 'CRITICAL'
    elif sizes['cache_percent'] > 1.5 or sizes['core_percent'] > 6.0:
        status = 'WARNING'
    else:
        status = 'HEALTHY'
    
    return jsonify({
        'status': status,
        'checks': {
            'core': 'OK' if sizes['core_percent'] < 7.0 else 'FAIL',
            'cache': 'OK' if sizes['cache_percent'] < 2.0 else 'FAIL',
            'total': 'OK' if sizes['total_percent'] < 9.0 else 'FAIL'
        },
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)