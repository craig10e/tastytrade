# Tastytrade Python Trading Library

A comprehensive Python library for automated options trading with a broker-agnostic architecture, providing seamless API integration and an extensible framework for implementing trading strategies.

## Overview

This library offers three main components:

1. **TastytradeAPI**: A Python client for interacting with the Tastytrade REST API and streaming services
2. **TastytradeBroker**: A high-level broker implementation for managing accounts, positions, and orders
3. **Trading Strategies**: Broker-agnostic strategies that can work with any compatible broker implementation

The broker-agnostic design allows strategies to be developed independently of the specific brokerage platform, making your trading systems more flexible and portable.

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
- Standardized interface for strategy integration

### Strategy Features
- Broker-agnostic implementation
- Configurable parameters
- Position monitoring and management
- Automated entry and exit rules
- Support for scanning existing positions

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
TASTY_ACCOUNT=your_account_number  # Specify which account to use for trading
TASTY_BASE_URL=https://api.tastytrade.com
TASTY_STREAMER_URL=wss://streamer.tastytrade.com
```

For sandbox/development use, you can use:
```
TASTY_BASE_URL=https://api.cert.tastyworks.com
TASTY_STREAMER_URL=wss://streamer.cert.tastyworks.com
```

## Basic Usage

### Running a Strategy with Tastytrade

```python
from api.tastytrade_api import TastytradeAPI
from broker.tastytrade_broker import TastytradeBroker
from strategies.spx_iron_condor_strategy import SPXIronCondorStrategy

# Initialize API and broker
api = TastytradeAPI()
broker = TastytradeBroker()

# Initialize strategy with the broker
strategy = SPXIronCondorStrategy(broker)

# Let the strategy select the account
if not strategy.select_account():
    print("No accounts found. Please check your credentials.")
    exit(1)

# Run strategy
strategy.run()
```

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
import os
from dotenv import load_dotenv
from broker.tastytrade_broker import TastytradeBroker

# Load environment variables
load_dotenv()

# Initialize broker
broker = TastytradeBroker()

# Get account from environment variable or use first available
preferred_account = os.getenv("TASTY_ACCOUNT")
if preferred_account and preferred_account in broker.accounts:
    account_number = preferred_account
else:
    account_number = list(broker.accounts.keys())[0] if broker.accounts else None

# Start streaming service
broker.start_streaming_service(account_number)

# Find appropriate iron condor strikes
strikes = broker.select_iron_condor_strikes(
    underlying_symbol="SPX",
    expiration_date="2025-02-28",
    delta_min=0.16,
    delta_max=0.25,
    put_wing_cost=0.15,
    call_wing_cost=0.05,
    target_put_credit=5.0,
    target_call_credit=5.0
)

# Execute an iron condor
trade_info = broker.execute_iron_condor(
    account_number=account_number,
    underlying_symbol="SPX",
    expiration_date="2025-02-28",
    strikes=strikes,
    num_contracts=1,
    credit_price=10.0
)
```

## Creating a New Broker Implementation

The strategy framework is designed to work with any broker implementation that provides the required interface. To create a new broker implementation:

1. Create a new broker class that implements these required methods:
   - `select_iron_condor_strikes()`
   - `calculate_max_iron_condor_contracts()`
   - `scan_for_iron_condor_positions()`
   - `execute_iron_condor()`
   - `check_option_exit_condition()`
   - `close_option_position()`
   - `start_streaming_service()`

2. Ensure your broker class maintains these attributes:
   - `accounts`: A dictionary of available accounts
   - `symbols_to_monitor`: A structure for tracking symbol data

3. Use your new broker with existing strategies:

```python
from strategies.spx_iron_condor_strategy import SPXIronCondorStrategy
from your_module import YourCustomBroker

# Initialize your custom broker
broker = YourCustomBroker()

# Use with existing strategy
strategy = SPXIronCondorStrategy(broker)
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
│   └── spx_iron_condor_strategy.py  # Broker-agnostic strategy
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

### Account Selection

The library supports selecting a specific trading account using the TASTY_ACCOUNT environment variable:

```python
# In your .env file
TASTY_ACCOUNT=your_account_number

# In your code
import os
from dotenv import load_dotenv
load_dotenv()

# Strategy will automatically use the account from the environment variable
strategy = SPXIronCondorStrategy(broker)
strategy.select_account()  # Uses TASTY_ACCOUNT or falls back to first account
```

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

### Strategy Configuration

The SPX Iron Condor strategy has several configurable parameters:

```python
# Initialize strategy
strategy = SPXIronCondorStrategy(broker)

# Configure strategy parameters
strategy.entry_time_eastern = "10:10"  # Format: "HH:MM"
strategy.target_delta_min = 0.16
strategy.target_delta_max = 0.25
strategy.target_put_credit = 5.0
strategy.target_call_credit = 5.0
strategy.put_wing_cost = 0.15
strategy.call_wing_cost = 0.05
strategy.exit_threshold = 0.90  # Exit at 90% of credit received
strategy.exit_confirmation_time = 120  # 2 minutes confirmation period
strategy.max_buying_power = 100000.0 
strategy.max_iron_condors = 6
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
