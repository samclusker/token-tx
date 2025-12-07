"""Token Transaction Service - Sends EOA transactions at regular intervals."""
import argparse
import asyncio
import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web
from web3 import AsyncWeb3, Web3
from web3.middleware import ExtraDataToPOAMiddleware, SignAndSendRawMiddlewareBuilder
from web3.providers.rpc.async_rpc import AsyncHTTPProvider
from web3.providers.persistent import WebSocketProvider

# Shutdown flag for graceful termination (thread-safe for signal handlers)
shutdown_event = threading.Event()

# State for health checks
service_state = {
    'ready': False,
    'connected': False,
    'last_tx_time': None,
    'last_tx_hash': None,
    'error_count': 0
}

# Service name for logging
SERVICE_NAME = "token-tx"

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter"""

    def format(self, record):
        # format: YYYY-MM-DDTHH:MM:SS.sssZ
        dt = datetime.now(timezone.utc)
        timestamp = dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        level = record.levelname.lower()

        message = record.getMessage()

        # Build JSON log entry
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "service": SERVICE_NAME,
            "message": message
        }

        return json.dumps(log_entry)

def init_logger():
    """Initialize logger with JSON formatter"""
    app_logger = logging.getLogger(SERVICE_NAME)
    app_logger.setLevel(logging.INFO)

    # Create console handler with JSON formatter
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    app_logger.addHandler(handler)

    return app_logger

logger = init_logger()

async def send_funds(w3: AsyncWeb3, tx_data: dict):
    """
    Send funds to an account on a regular interval.

    Args:
        w3: AsyncWeb3 object
        tx_data: Dictionary containing the transaction data
    """

    amount = tx_data['value']
    pk = tx_data['pk']
    to_address = tx_data['to']
    interval = tx_data['interval']
    use_legacy_gas = tx_data['use_legacy_gas']

    # Derive account address from private key
    account = w3.eth.account.from_key(pk)
    w3.eth.default_account = account.address
    # SignAndSendRawMiddlewareBuilder handles signing automatically
    # https://web3py.readthedocs.io/en/stable/middleware.html#web3.middleware.SignAndSendRawMiddlewareBuilder
    middleware = SignAndSendRawMiddlewareBuilder.build(account)  # pylint: disable=no-value-for-parameter
    w3.middleware_onion.inject(middleware, layer=0)


    # Use legacy gas if flag is set
    if use_legacy_gas:
        logger.info("Using legacy gas pricing (--legacy-gas flag set)")
    else:
        logger.info("Using EIP-1559 dynamic fee transactions")

    logger.info("Starting transaction service")
    logger.info(
        "from: %s, to: %s, amount: %s wei, interval: %s seconds",
        account.address,
        to_address,
        amount,
        interval
    )

    # Considered in ready state
    service_state['ready'] = True
    service_state['connected'] = True

    while not shutdown_event.is_set():
        try:
            # Get current gas prices dynamically
            gas_price = await w3.eth.gas_price

            if not use_legacy_gas:
                tx_dict = {
                    'from': account.address,
                    'to': to_address,
                    'value': amount,
                    'maxFeePerGas': int(gas_price * 1.2),  # 20% buffer over base fee
                    'maxPriorityFeePerGas': 1000000000  # 1 gwei tip
                }
            else:
                tx_dict = {
                    'from': account.address,
                    'to': to_address,
                    'value': amount,
                    'gasPrice': gas_price
                }

            tx_hash = await w3.eth.send_transaction(tx_dict)

            logger.info(
                "Sent %s wei to %s, TX: %s",
                amount,
                to_address,
                tx_hash.hex()
            )

            # Update state
            service_state['last_tx_time'] = datetime.now().isoformat()
            service_state['last_tx_hash'] = tx_hash.hex()
            service_state['error_count'] = 0
            service_state['ready'] = True  # Mark as ready on successful tx

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Transaction service cancelled, shutting down")
            break
        except Exception as e:  # pylint: disable=broad-exception-caught
            service_state['error_count'] += 1
            logger.error("Error sending transaction: %s", e)

            # Considered not ready if too many consecutive errors (threshold: 5)
            if service_state['error_count'] >= 5:
                service_state['ready'] = False
                logger.warning(
                    "Service marked as not ready due to %s consecutive errors",
                    service_state['error_count']
                )

            if shutdown_event.is_set():
                logger.info("Shutdown signal received during error handling, stopping")
                break

            logger.info("Retrying in %s seconds", interval)
            await asyncio.sleep(interval)

    logger.info("Transaction service stopped")
    service_state['ready'] = False
    service_state['connected'] = False

async def connect_with_retry(rpc_url: str, max_attempts: int = 3) -> Optional[AsyncWeb3]:
    """
    Connect to RPC

    Args:
        rpc_url: RPC URL to connect to
        max_attempts: Maximum number of connection attempts

    Returns:
        AsyncWeb3 instance if successful, None otherwise
    """
    attempt = 0
    is_websocket = rpc_url.startswith(('ws://', 'wss://'))

    while attempt < max_attempts:
        attempt += 1
        is_final_attempt = attempt >= max_attempts

        try:
            if is_websocket:
                # https://web3py.readthedocs.io/en/stable/providers.html#web3.providers.persistent.WebSocketProvider
                w3 = AsyncWeb3[WebSocketProvider](WebSocketProvider(rpc_url))
                try:
                    await w3.provider.connect()
                except Exception as conn_error:  # pylint: disable=broad-exception-caught
                    if is_final_attempt:
                        logger.error("WebSocket connection failed on final attempt: %s", conn_error)
                        break
                    wait_time = 2 ** attempt
                    logger.warning(
                        "Failed to connect (attempt %s/%s), retrying in %s seconds",
                        attempt,
                        max_attempts,
                        wait_time
                    )
                    await asyncio.sleep(wait_time)
                    continue
            else:
                w3 = AsyncWeb3[AsyncHTTPProvider](AsyncHTTPProvider(rpc_url))

            # Verify connection
            if not await w3.is_connected():
                if is_final_attempt:
                    logger.error("Connection verification failed on final attempt")
                    break
                wait_time = 2 ** attempt
                logger.warning(
                    "Failed to connect (attempt %s/%s), retrying in %s seconds",
                    attempt,
                    max_attempts,
                    wait_time
                )
                await asyncio.sleep(wait_time)
                continue

            # Successfully connected
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            logger.info("Successfully connected to RPC node at %s", rpc_url)
            return w3

        except Exception as e:  # pylint: disable=broad-exception-caught
            if is_final_attempt:
                logger.error("Error connecting on final attempt: %s", e)
                break

            wait_time = 2 ** attempt
            logger.error(
                "Error connecting (attempt %s/%s), retrying in %s seconds: %s",
                attempt,
                max_attempts,
                wait_time,
                e
            )
            await asyncio.sleep(wait_time)

    return None

async def liveness_handler(_request):
    """Liveness probe - is the service running."""
    return web.json_response({'status': 'alive'}, status=200)

async def readiness_handler(_request):
    """Readiness probe - is the service ready to send txs."""
    # Service is ready if: connected, initialized, and not too many errors
    is_ready = (
        service_state['ready'] and
        service_state['connected'] and
        service_state['error_count'] < 5
    )

    if is_ready:
        return web.json_response({
            'status': 'ready',
            'connected': service_state['connected'],
            'last_tx_time': service_state['last_tx_time'],
            'last_tx_hash': service_state['last_tx_hash'],
            'error_count': service_state['error_count']
        }, status=200)
    return web.json_response({
        'status': 'not_ready',
        'ready': service_state['ready'],
        'connected': service_state['connected'],
        'error_count': service_state['error_count'],
        'reason': 'too_many_errors' if service_state['error_count'] >= 5 else 'not_initialized'
    }, status=503)

async def health_handler(_request):
    """Combined health check endpoint."""
    return web.json_response({
        'status': 'healthy' if service_state['ready'] else 'unhealthy',
        **service_state
    }, status=200 if service_state['ready'] else 503)

def setup_signal_handlers():
    """
    Setup signal handlers for graceful shutdown.
    """
    def signal_handler(signum, _frame):
        """
        Handler function called when a signal is received.
        Args:
            signum: Signal number
            _frame: Current stack frame
        """
        logger.info("Received signal %s, initiating graceful shutdown", signum)
        shutdown_event.set()

    # https://docs.python.org/3/library/signal.html#signal.signal
    # Register handler for SIGTERM
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    # (Development) Register handler for SIGINT
    signal.signal(signal.SIGINT, signal_handler)

async def start_health_server(port: int = 8080):
    """Start the health check HTTP server."""
    app = web.Application()
    app.router.add_get('/health', health_handler)
    app.router.add_get('/health/live', liveness_handler)
    app.router.add_get('/health/ready', readiness_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info("Health check server started on http://0.0.0.0:%s", port)
    logger.info(
        "Health endpoints - Liveness: http://localhost:%s/health/live, "
        "Readiness: http://localhost:%s/health/ready, "
        "Health: http://localhost:%s/health",
        port,
        port,
        port
    )
    return runner

async def main():
    """Parses arguments and runs the tx service."""
    parser = argparse.ArgumentParser(
        description=(
            "Token Transaction Service - Sends ETH transactions to a "
            "specified address at regular intervals."
        ),
        epilog="""
Examples:
  # Basic usage with private key (EIP-1559 dynamic fees)
  python src/main.py --rpc-url https://linea-mainnet.infura.io/v3/YOUR_KEY \\
    --pk 0x1234... --to-address 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb --amount 10

  # Using environment variable for private key
  export SENDER_PK=0x1234...
  python src/main.py --rpc-url https://linea-mainnet.infura.io/v3/YOUR_KEY \\
    --to-address 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb --amount 10 --interval 5

  # Using legacy gas pricing (for local networks or networks without EIP-1559 support)
  python src/main.py --rpc-url http://localhost:8545 \\
    --pk 0x1234... --to-address 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb \\
    --amount 10 --legacy-gas

  # Custom health check port
  python src/main.py --rpc-url https://linea-mainnet.infura.io/v3/YOUR_KEY \\
    --pk 0x1234... --to-address 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb \\
    --amount 100 --health-port 9090

Health Endpoints:
  - Liveness:  http://localhost:8080/health/live
  - Readiness: http://localhost:8080/health/ready
  - Health:    http://localhost:8080/health

For more information, see README.md
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--rpc-url',
        type=str,
        required=True,
        metavar='URL',
        help=(
            "RPC URL for the blockchain node "
            "(e.g., https://linea-mainnet.infura.io/v3/YOUR_KEY)"
        )
    )
    parser.add_argument(
        '--amount',
        type=int,
        required=True,
        metavar='WEI',
        help="Amount to send in wei (smallest unit of ETH). Example: 1000000000000000000 = 1 ETH"
    )
    parser.add_argument(
        '--pk',
        type=str,
        required=False,
        metavar='PRIVATE_KEY',
        help="Private key of the sender account (hex string starting with 0x). "
             "Alternatively, set SENDER_PK environment variable. "
             "WARNING: Never commit private keys to version control!"
    )
    parser.add_argument(
        '--to-address',
        type=str,
        required=True,
        metavar='ADDRESS',
        help="Ethereum address of the recipient (must be a valid 42-character hex address)"
    )
    parser.add_argument(
        '--interval',
        type=int,
        required=False,
        default=1,
        metavar='SECONDS',
        help="Interval in seconds between transactions (default: 1). "
             "Transactions are sent at strict intervals without waiting for confirmation."
    )
    parser.add_argument(
        '--health-port',
        type=int,
        required=False,
        default=8080,
        metavar='PORT',
        help="Port for health check HTTP server (default: 8080). "
             "Provides liveness and readiness probes for Kubernetes/Docker."
    )
    parser.add_argument(
        '--legacy-gas',
        action='store_true',
        required=False,
        help="Use legacy gas pricing instead of EIP-1559 dynamic fees. "
    )

    # Parse arguments
    args = parser.parse_args()

    # Validate arguments
    if not args.rpc_url:
        parser.error("--rpc-url must be provided.")

    pk = args.pk or os.environ.get('SENDER_PK')
    if not pk:
        parser.error(
            "--pk must be provided or SENDER_PK must be set in your "
            "environment variables."
        )

    if not args.to_address:
        parser.error("--to-address must be provided.")

    if not args.amount or args.amount <= 0:
        parser.error("--amount must be provided and greater than 0.")

    # Validate address format
    if not Web3.is_address(args.to_address):
        parser.error(f"Invalid address format: {args.to_address}")

    # Normalize address to checksum format
    to_address = Web3.to_checksum_address(args.to_address)

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    # Start health check server
    health_runner = await start_health_server(args.health_port)

    try:
        # Connect to RPC
        w3 = await connect_with_retry(args.rpc_url)
        if w3 is None:
            logger.error("Failed to connect to RPC node, exiting")
            return

        # Run transaction service (this will run until shutdown_event is set)
        await send_funds(
            w3,
            {
                'value': args.amount,
                'pk': pk,
                'to': to_address,
                'interval': args.interval,
                'use_legacy_gas': args.legacy_gas
            }
        )
    except asyncio.CancelledError:
        logger.info("Service cancelled")
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Unexpected error: %s", e)
    finally:
        # Cleanup
        logger.info("Cleaning up")
        is_websocket = args.rpc_url.startswith(('ws://', 'wss://'))
        if is_websocket:
            await w3.provider.disconnect()
        await health_runner.cleanup()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
        shutdown_event.set()
