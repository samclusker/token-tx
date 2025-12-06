"""Tests for the token transaction service."""
import json
import logging
import re
import sys

import pytest
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, 'src')
from main import (  # pylint: disable=wrong-import-position
    JSONFormatter,
    health_handler,
    init_logger,
    liveness_handler,
    readiness_handler,
    service_state
)


def test_json_formatter():
    """Test that JSONFormatter creates valid JSON log entries"""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name='test',
        level=logging.INFO,
        pathname='test.py',
        lineno=1,
        msg='Test message',
        args=(),
        exc_info=None
    )

    result = formatter.format(record)
    log_data = json.loads(result)

    assert 'timestamp' in log_data
    # Verify timestamp format: YYYY-MM-DDTHH:MM:SS.sssZ
    timestamp_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$'
    timestamp = log_data['timestamp']
    assert re.match(timestamp_pattern, timestamp), (
        f"Timestamp {timestamp} does not match expected format "
        "YYYY-MM-DDTHH:MM:SS.sssZ"
    )
    assert 'level' in log_data
    assert 'service' in log_data
    assert 'message' in log_data
    assert log_data['level'] == 'info'
    assert log_data['message'] == 'Test message'
    assert log_data['service'] == 'token-tx'


def test_init_logger():
    """Test that logger is initialized correctly"""
    # Clear existing handlers to test fresh initialization
    logger = logging.getLogger('token-tx')
    logger.handlers.clear()

    logger = init_logger()

    assert logger is not None
    assert logger.name == 'token-tx'
    assert logger.level == logging.INFO
    assert len(logger.handlers) >= 1


@pytest.mark.asyncio
async def test_liveness_handler():
    """Test that liveness handler returns correct response"""
    request = make_mocked_request('GET', '/health/live')
    response = await liveness_handler(request)

    assert response.status == 200
    data = json.loads(response.text)
    assert data['status'] == 'alive'


@pytest.mark.asyncio
async def test_readiness_handler_ready():
    """Test readiness handler when service is ready"""
    # Set service state to ready
    service_state['ready'] = True
    service_state['connected'] = True
    service_state['error_count'] = 0

    request = make_mocked_request('GET', '/health/ready')
    response = await readiness_handler(request)

    assert response.status == 200
    data = json.loads(response.text)
    assert data['status'] == 'ready'
    assert data['connected'] is True


@pytest.mark.asyncio
async def test_readiness_handler_not_ready():
    """Test readiness handler when service is not ready"""
    # Set service state to not ready
    service_state['ready'] = False
    service_state['connected'] = False
    service_state['error_count'] = 0

    request = make_mocked_request('GET', '/health/ready')
    response = await readiness_handler(request)

    assert response.status == 503
    data = json.loads(response.text)
    assert data['status'] == 'not_ready'


@pytest.mark.asyncio
async def test_health_handler():
    """Test health handler returns service state"""
    service_state['ready'] = True
    service_state['connected'] = True

    request = make_mocked_request('GET', '/health')
    response = await health_handler(request)

    assert response.status == 200
    data = json.loads(response.text)
    assert 'status' in data
    assert 'ready' in data
    assert 'connected' in data
