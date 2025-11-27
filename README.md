# Token Transaction Service

A Python service that signs an EOA tx and sends an amount (in wei) to a specified address at regular intervals.

## Features

- Sends configurable amounts in wei to any address
- Configurable sending interval (default: 1 second)
- Supports private key via command line argument or environment variable
- Automatic retry logic for RPC connection failures
- Proper transaction signing using EOA private keys
- Support with PoA middleware

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### CLI Usage

```bash
python src/main.py \
  --rpc-url <RPC_URL> \
  --pk <PRIVATE_KEY> \
  --to-address <RECIPIENT_ADDRESS> \
  --amount <AMOUNT_IN_WEI>
```

### Docker Usage

```bash
docker run token-tx:1.0.0 \
  --rpc-url <RPC_URL> \
  --pk <PRIVATE_KEY> \
  --to-address <RECIPIENT_ADDRESS> \
  --amount <AMOUNT_IN_WEI>
```

### Using Environment Variable for Private Key

Create a `.env` file:
```
SENDER_PK=your_private_key_here
```

Then run:
```bash
python src/main.py \
  --rpc-url <RPC_URL> \
  --to-address <RECIPIENT_ADDRESS> \
  --amount <AMOUNT_IN_WEI>
```

### Arguments

- `--rpc-url` (required): RPC URL for the blockchain node
- `--pk` (optional): Private key of the sender account (can also use `SENDER_PK` env var)
- `--to-address` (required): Recipient Ethereum address
- `--amount` (required): Amount to send in wei (must be a positive integer)
- `--interval` (optional): Interval in seconds between transactions (default: 1)

## Security Notes

- **Never commit private keys** to version control
- Use environment variables or `.env` files (which should be in `.gitignore`)
- The `.env` file should never be committed to the repository
- Private keys are sensitive - handle with care

