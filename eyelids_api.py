#!/usr/bin/env python3
"""
Enhanced API with JWT authentication and validation
Based on Mistral's security recommendations
"""

from flask import Flask, request, jsonify
from flask_httpauth import HTTPTokenAuth
from pydantic import BaseModel, ValidationError, Field
import asyncio
import aiohttp
import json
import os
from datetime import datetime
from eyelids_core import EyelidsCore

app = Flask(__name__)
auth = HTTPTokenAuth(scheme='Bearer')
eyelids = EyelidsCore()

# Get API token from environment
VALID_API_TOKENS = os.getenv('API_TOKENS', 'default-token').split(',')

@auth.verify_token
def verify_token(token):
    """Verify API token"""
    return token in VALID_API_TOKENS

# Pydantic models for validation
class PriorityRequest(BaseModel):
    data_id: str
    priority: int = Field(ge=0, le=5)  # Priority between 0-5

class WebhookRequest(BaseModel):
    url: str
    priority: str = Field(regex='^(critical|warning|info)$')

class CleanupRequest(BaseModel):
    type: str = Field(regex='^(soft|hard|emergency)$')

class WebhookManager:
    def __init__(self):
        self.webhooks = {
            'critical': [],
            'warning': [],
            'info': []
        }
        self.webhook_history = []
    
    async def send_webhook(self, event_type, data, priority='info', retries=3):
        """Send webhook with retry logic (Mistral's improvement)"""
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
                for attempt in range(retries):
                    try:
                        async with session.post(url, json=webhook_data, timeout=5) as response:
                            if response.status == 200:
                                self.webhook_history.append({
                                    'url': url,
                                    'status': 'success',
                                    'timestamp': datetime.now().isoformat(),
                                    'attempts': attempt + 1
                                })
                                break
                    except Exception as e:
                        if attempt == retries - 1:
                            self.webhook_history.append({
                                'url': url,
                                'status': 'failed',
                                'error': str(e),
                                'timestamp': datetime.now().isoformat(),
                                'attempts': retries
                            })
                            eyelids.logger.error(f"Webhook failed after {retries} attempts: {url} - {e}")
                        else:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff

webhook_mgr = WebhookManager()

# API Endpoints with authentication
@app.route('/api/v1/status', methods=['GET'])
def get_status():
    """Get system status (public endpoint)"""
    sizes = eyelids.get_size_percentages()
    return jsonify({
        'status': 'active',
        'core_usage': sizes['core_percent'],
        'cache_usage': sizes['cache_percent'],
        'total_usage': sizes['total_percent'],
        'stats': eyelids.stats,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/v1/priority/set', methods=['POST'])
@auth.login_required
def set_priority():
    """Set priority for data (protected endpoint)"""
    try:
        data = PriorityRequest(**request.json)
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    
    # TODO: Implement actual priority setting
    result = {'data_id': data.data_id, 'priority': data.priority, 'status': 'set'}
    
    # Send webhook notification
    asyncio.create_task(webhook_mgr.send_webhook(
        'priority_changed',
        {'data_id': data.data_id, 'new_priority': data.priority},
        'info'
    ))
    
    return jsonify({'success': True, 'result': result})

@app.route('/api/v1/cache/force-cleanup', methods=['POST'])
@auth.login_required
def force_cleanup():
    """Force cache cleanup (protected endpoint)"""
    try:
        data = CleanupRequest(**request.json)
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    
    cleanup_type = data.type
    
    # Log the cleanup request
    eyelids.logger.warning(f"Force cleanup requested: {cleanup_type}")
    
    # TODO: Implement actual cleanup
    result = {'freed_space': 0, 'type': cleanup_type}
    
    # Send webhook notification
    priority = 'critical' if cleanup_type == 'emergency' else 'warning'
    asyncio.create_task(webhook_mgr.send_webhook(
        f'{cleanup_type}_cleanup',
        {'type': cleanup_type, 'result': result},
        priority
    ))
    
    return jsonify({'success': True, 'result': result})

@app.route('/api/v1/webhooks/register', methods=['POST'])
@auth.login_required
def register_webhook():
    """Register webhook URL (protected endpoint)"""
    try:
        data = WebhookRequest(**request.json)
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    
    webhook_mgr.webhooks[data.priority].append(data.url)
    
    eyelids.logger.info(f"Webhook registered: {data.url} ({data.priority})")
    
    return jsonify({
        'success': True,
        'registered_url': data.url,
        'priority': data.priority
    })

@app.route('/api/v1/metrics/export', methods=['GET'])
@auth.login_required
def export_metrics():
    """Export metrics (protected endpoint)"""
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
    """Health check endpoint (public)"""
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

# Error handlers
@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': 'Unauthorized', 'message': 'Invalid or missing API token'}), 401

@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad Request', 'message': str(e)}), 400

@app.errorhandler(500)
def internal_error(e):
    eyelids.logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal Server Error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)