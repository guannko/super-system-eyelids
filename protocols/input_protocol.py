#!/usr/bin/env python3
"""
Input Protocol for CORTEX v3.0 super-system-eyelids
Complete validation, routing and processing of incoming data
"""

import hashlib
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from enum import Enum
from dataclasses import dataclass

class DataType(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    ARCHIVE = "ARCHIVE"

class ValidationResult(Enum):
    VALID = "VALID"
    INVALID_STRUCTURE = "INVALID_STRUCTURE"
    SIZE_EXCEEDED = "SIZE_EXCEEDED"
    TYPE_UNKNOWN = "TYPE_UNKNOWN"
    CORRUPTED = "CORRUPTED"

@dataclass
class InputData:
    content: Any
    metadata: Dict[str, Any]
    source: str
    timestamp: datetime
    size_bytes: int
    checksum: str

class InputProtocol:
    def __init__(self, cache_manager=None, reflex_protocols=None, webhook_manager=None):
        self.cache_manager = cache_manager
        self.reflex_protocols = reflex_protocols
        self.webhook_manager = webhook_manager
        
        # Size limits in bytes
        self.size_limits = {
            DataType.CRITICAL: 500 * 1024 * 1024,  # 500MB
            DataType.HIGH: 200 * 1024 * 1024,      # 200MB
            DataType.MEDIUM: 100 * 1024 * 1024,    # 100MB
            DataType.LOW: 50 * 1024 * 1024,        # 50MB
            DataType.ARCHIVE: 1024 * 1024 * 1024   # 1GB
        }
        
        # Patterns for data type determination
        self.type_patterns = {
            'emergency': DataType.CRITICAL,
            'critical': DataType.CRITICAL,
            'urgent': DataType.HIGH,
            'important': DataType.HIGH,
            'normal': DataType.MEDIUM,
            'backup': DataType.LOW,
            'archive': DataType.ARCHIVE,
            'old': DataType.ARCHIVE
        }
        
        self.processed_count = 0
        self.error_count = 0
    
    def generate_unique_id(self, data: InputData) -> str:
        """Generate unique ID for data"""
        timestamp_str = data.timestamp.isoformat()
        content_hash = hashlib.sha256(str(data.content).encode()).hexdigest()[:16]
        source_hash = hashlib.md5(data.source.encode()).hexdigest()[:8]
        
        return f"eyelids_{timestamp_str}_{content_hash}_{source_hash}"
    
    def validate_data_structure(self, data: Any) -> ValidationResult:
        """Validate data structure"""
        try:
            # Check for None or empty data
            if data is None or (isinstance(data, (str, list, dict)) and len(data) == 0):
                return ValidationResult.INVALID_STRUCTURE
            
            # Check JSON serializability
            json.dumps(data, default=str)
            
            # Check structure correctness
            if isinstance(data, dict):
                if not data.get('content') and not data.get('data'):
                    return ValidationResult.INVALID_STRUCTURE
            
            return ValidationResult.VALID
            
        except (TypeError, ValueError, RecursionError):
            return ValidationResult.CORRUPTED
    
    def check_size_limits(self, data: InputData, data_type: DataType) -> bool:
        """Check size limits"""
        max_size = self.size_limits.get(data_type, self.size_limits[DataType.MEDIUM])
        return data.size_bytes <= max_size
    
    def determine_data_type(self, data: InputData) -> DataType:
        """Determine data type based on metadata and content"""
        # Check metadata
        if 'priority' in data.metadata:
            priority = data.metadata['priority'].lower()
            if priority in ['critical', 'emergency']:
                return DataType.CRITICAL
            elif priority in ['high', 'urgent']:
                return DataType.HIGH
            elif priority in ['low', 'background']:
                return DataType.LOW
            elif priority in ['archive', 'backup']:
                return DataType.ARCHIVE
        
        # Check source
        source_lower = data.source.lower()
        for pattern, data_type in self.type_patterns.items():
            if pattern in source_lower:
                return data_type
        
        # Check file size
        if data.size_bytes > 100 * 1024 * 1024:  # > 100MB
            return DataType.ARCHIVE
        elif data.size_bytes > 50 * 1024 * 1024:  # > 50MB
            return DataType.LOW
        elif data.size_bytes > 10 * 1024 * 1024:  # > 10MB
            return DataType.MEDIUM
        else:
            return DataType.HIGH  # Process small files quickly
    
    async def route_to_cache(self, data_id: str, data: InputData, data_type: DataType) -> bool:
        """Route data to cache"""
        try:
            cache_path = f"incoming/{data_type.value.lower()}/{data_id}"
            
            # Prepare data for cache
            cache_entry = {
                'id': data_id,
                'content': data.content,
                'metadata': data.metadata,
                'source': data.source,
                'timestamp': data.timestamp.isoformat(),
                'size_bytes': data.size_bytes,
                'checksum': data.checksum,
                'data_type': data_type.value,
                'cache_path': cache_path
            }
            
            # Store in cache (mock for now)
            if self.cache_manager:
                success = await self.cache_manager.store_data(cache_path, cache_entry)
                if success:
                    await self.cache_manager.update_stats('incoming', data_type.value, data.size_bytes)
                return success
            
            return True  # Mock success
            
        except Exception as e:
            if self.webhook_manager:
                await self.webhook_manager.send_webhook(
                    'cache_routing_error',
                    {'data_id': data_id, 'error': str(e)},
                    'critical'
                )
            return False
    
    async def trigger_reflex(self, data_id: str, data_type: DataType, metadata: Dict[str, Any]) -> bool:
        """Trigger appropriate reflex"""
        try:
            # Determine priority for reflex
            priority_map = {
                DataType.CRITICAL: 6,
                DataType.HIGH: 5,
                DataType.MEDIUM: 3,
                DataType.LOW: 2,
                DataType.ARCHIVE: 1
            }
            
            priority = priority_map.get(data_type, 3)
            
            # Trigger reflex (mock for now)
            if self.reflex_protocols:
                reflex_result = await self.reflex_protocols.trigger_data_processing(
                    data_id=data_id,
                    priority=priority,
                    data_type=data_type.value,
                    metadata=metadata
                )
                return reflex_result
            
            return True  # Mock success
            
        except Exception as e:
            if self.webhook_manager:
                await self.webhook_manager.send_webhook(
                    'reflex_trigger_error',
                    {'data_id': data_id, 'error': str(e)},
                    'warning'
                )
            return False
    
    async def input_protocol(self, raw_data: Any, source: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """Main input data protocol"""
        start_time = datetime.now()
        
        try:
            # 1. Prepare data
            if metadata is None:
                metadata = {}
            
            # Calculate size and checksum
            data_str = json.dumps(raw_data, default=str)
            size_bytes = len(data_str.encode('utf-8'))
            checksum = hashlib.sha256(data_str.encode()).hexdigest()
            
            input_data = InputData(
                content=raw_data,
                metadata=metadata,
                source=source,
                timestamp=start_time,
                size_bytes=size_bytes,
                checksum=checksum
            )
            
            # 2. Validate data structure
            validation_result = self.validate_data_structure(raw_data)
            if validation_result != ValidationResult.VALID:
                self.error_count += 1
                return False, "", {
                    'error': f'Validation failed: {validation_result.value}',
                    'processing_time_ms': (datetime.now() - start_time).total_seconds() * 1000
                }
            
            # 3. Generate unique ID
            data_id = self.generate_unique_id(input_data)
            
            # 4. Determine data type
            data_type = self.determine_data_type(input_data)
            
            # 5. Check size limits
            if not self.check_size_limits(input_data, data_type):
                self.error_count += 1
                if self.webhook_manager:
                    await self.webhook_manager.send_webhook(
                        'size_limit_exceeded',
                        {
                            'data_id': data_id,
                            'size_bytes': size_bytes,
                            'limit_bytes': self.size_limits[data_type],
                            'data_type': data_type.value
                        },
                        'warning'
                    )
                return False, data_id, {
                    'error': f'Size limit exceeded for {data_type.value}',
                    'size_bytes': size_bytes,
                    'limit_bytes': self.size_limits[data_type]
                }
            
            # 6. Route to cache
            cache_success = await self.route_to_cache(data_id, input_data, data_type)
            if not cache_success:
                self.error_count += 1
                return False, data_id, {
                    'error': 'Failed to route to cache',
                    'data_id': data_id
                }
            
            # 7. Trigger reflex
            reflex_success = await self.trigger_reflex(data_id, data_type, metadata)
            
            # 8. Final statistics
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            self.processed_count += 1
            
            # 9. Send confirmation
            confirmation = {
                'data_id': data_id,
                'data_type': data_type.value,
                'size_bytes': size_bytes,
                'checksum': checksum,
                'processing_time_ms': processing_time,
                'cache_routed': cache_success,
                'reflex_triggered': reflex_success,
                'timestamp': start_time.isoformat()
            }
            
            # Webhook for successful processing
            if data_type == DataType.CRITICAL and self.webhook_manager:
                await self.webhook_manager.send_webhook(
                    'critical_data_processed',
                    confirmation,
                    'info'
                )
            
            return True, data_id, confirmation
            
        except Exception as e:
            self.error_count += 1
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            error_info = {
                'error': str(e),
                'processing_time_ms': processing_time,
                'source': source,
                'metadata': metadata
            }
            
            if self.webhook_manager:
                await self.webhook_manager.send_webhook(
                    'input_protocol_error',
                    error_info,
                    'critical'
                )
            
            return False, "", error_info
    
    def get_stats(self) -> Dict[str, Any]:
        """Get protocol statistics"""
        return {
            'processed_count': self.processed_count,
            'error_count': self.error_count,
            'success_rate': (self.processed_count / (self.processed_count + self.error_count)) * 100 if (self.processed_count + self.error_count) > 0 else 0,
            'size_limits': {dt.value: limit for dt, limit in self.size_limits.items()}
        }