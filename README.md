# Tastytrade Python Trading Library

A comprehensive Python library for automated trading with the Tastytrade platform, providing seamless API integration and broker functionality for options trading strategies.

## Overview

This library offers two main components:

1. **TastytradeAPI**: A Python client for interacting with the Tastytrade REST API and streaming services
2. **TastytradeBroker**: A high-level broker implementation for managing accounts, positions, and orders

Together, these components provide everything needed to build automated trading strategies for the Tastytrade platform.

## Features

### API Client Features
- Comprehensive Tastytrade API integration
- Authentication with username/password or remember token
- Account and position data retrieval
- Option order creation and management
- Real-time market data streaming via WebSockets
- Greeks and quote data streaming
- Heartbeat management for persistent connections

### Broker Features
- High-level account and position management
- Order tracking and execution
- Smart order routing with automatic adjustments
- Market data monitoring and analysis
- Symbol tracking with historical data
- Trend detection for optimal trade entry

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/tastytrade.git
cd tastytrade

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in your project root with your Tastytrade credentials:

```
TASTY_USERNAME=your_username
TASTY_PASSWORD=your_password
TASTY_BASE_URL=https://api.tastytrade.com
TASTY_STREAMER_URL=wss://streamer.tastytrade.com
```

For sandbox/development use, you can use:
```
TASTY_BASE_URL=https://api.cert.tastyworks.com
TASTY_STREAMER_URL=wss://streamer.cert.tastyworks.com
```

## Basic Usage

### API Client

```python
from api.tastytrade_api import TastytradeAPI

# Initialize API client
api = TastytradeAPI()

# Get list of accounts
accounts = api.get_accounts()
account_number = accounts[0]['account']['account-number'] if accounts else None

# Get positions for an account
positions = api.get_positions(account_number)

# Get option chain for a symbol
option_chain = api.get_option_chain('SPX')

# Create an option order
api.create_option_order(
    account_number=account_number,
    underlying_symbol='SPX',
    expiration_date='2025-02-28',
    strike_price=4500.0,
    option_type='C',
    action='Buy to Open',
    quantity=1,
    order_type='Limit',
    limit_price=5.0,
    time_in_force='Day'
)
```

### Broker

```python
from broker.tastytrade_broker import TastytradeBroker

# Initialize broker
broker = TastytradeBroker()

# Access accounts
account_number = list(broker.accounts.keys())[0] if broker.accounts else None

# Start streaming service
broker.start_streaming_service(account_number)

# Create option order
broker.option_order(
    account=account_number,
    underlying_symbol='SPX',
    action='Buy to Open',
    option_type='C',
    quantity=1,
    dte=0,
    delta=0.30
)

# Process orders
broker.process_orders()
```

### Using both components with a strategy

```python
from api.tastytrade_api import TastytradeAPI
from broker.tastytrade_broker import TastytradeBroker
from strategies.spx_iron_condor_strategy import SPXIronCondorStrategy

# Initialize components
api = TastytradeAPI()
broker = TastytradeBroker()

# Get account
account_number = list(broker.accounts.keys())[0] if broker.accounts else None
if not account_number:
    print("No accounts found")
    exit(1)

# Start data streaming
broker.start_streaming_service(account_number)

# Initialize strategy
strategy = SPXIronCondorStrategy(api, broker)
strategy.set_account(account_number)

# Run strategy
strategy.run()
```

## Project Structure

```
tastytrade/
├── api/
│   └── tastytrade_api.py       # Direct API client
├── broker/
│   └── tastytrade_broker.py    # High-level broker functionality
├── models/
│   ├── account.py              # Account model
│   ├── greeks.py               # Greeks data model
│   ├── order.py                # Order model
│   ├── position.py             # Position model
│   ├── price.py                # Price data model
│   └── symbol.py               # Symbol tracking model
├── strategies/
│   └── spx_iron_condor_strategy.py  # Sample strategy
├── .env                        # Environment variables (not in repo)
├── .env-session                # Session tokens (not in repo)
├── requirements.txt            # Dependencies
└── README.md                   # This file
```

## Requirements

- Python 3.7+
- websocket-client
- requests
- python-dotenv
- pytz

## Advanced Features

### Market Data Streaming

The library provides real-time market data:

```python
# Initialize broker to get market data
broker = TastytradeBroker()
account_number = list(broker.accounts.keys())[0]
broker.start_streaming_service(account_number)

# Add custom handlers for quotes and Greeks
broker.api_client.add_quote_handler(lambda symbol, data: print(f"Quote: {symbol} {data}"))
broker.api_client.add_greeks_handler(lambda symbol, data: print(f"Greeks: {symbol} {data}"))

# Stream specific symbols
broker.api_client.subscribe_to_option_quotes(['SPX250321C04500000'])
broker.api_client.subscribe_to_equity_quotes(['SPX'])
```

### Order Management

Advanced order functionality:

```python
# Create an order with delta targeting
broker.option_order(
    account=account_number,
    underlying_symbol='SPX',
    action='Buy to Open',
    option_type='C',
    quantity=1,
    dte=0,  # 0 days to expiration
    delta=0.30,  # Target delta value
)

# Process pending orders (handles adjustments, monitoring, etc.)
broker.process_orders()
```

### Symbol Tracking

The broker tracks price and Greeks data:

```python
# Access symbol tracking data
symbol_data = broker.symbols_to_monitor['SPX']

# Get latest prices
latest_price = symbol_data.prices[-1].midpoint_price if symbol_data.prices else None

# Get trend information
is_trending_up = symbol_data.is_trending_up

# Get volatility information
volatility = symbol_data.volatility_sma if symbol_data.greeks else None
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This library is not affiliated with, maintained, authorized, endorsed, or sponsored by Tastytrade or any of its affiliates. Use at your own risk. Trading options involves significant risk and is not suitable for all investors.
