## SPX 0 DTE Iron Condor Strategy - Implementation Guide

This guide explains how to set up and run the SPX Iron Condor Strategy using our broker-agnostic architecture.

### Strategy Overview

This strategy implements 0 DTE (0 Days To Expiration) SPX Iron Condor trades with the following specifications:

- **Entry Time**: 10:10 AM Eastern (8:10 AM Utah time)
- **Budget**: $100,000 max buying power (dynamically adjusted based on actual account balance)
- **Strike Selection**: 16-25 delta range for short options
- **Credit Target**: ~$5 for puts and ~$5 for calls (~$10 total per iron condor)
- **Wing Costs**: $0.15 for put wings, $0.05 for call wings
- **Quantity**: Aims for ~6 iron condors while staying under buying power limit
- **Monitoring**: Short calls and short puts are monitored separately
- **Exit Criteria**:
  - Exit when cost to close exceeds 90% of credit received for at least 2 minutes
  - Let untested sides and wings expire worthless
- **Position Management**:
  - Automatically scans for existing iron condor positions at startup
  - Reconstructs trade details for existing positions
  - Applies consistent exit rules to both new and existing positions

### Architecture Overview

The strategy follows a broker-agnostic design pattern:

1. **Strategy Layer**: Contains trading logic but no broker-specific code
2. **Broker Interface**: Defines methods required by the strategy
3. **Broker Implementation**: (e.g., TastytradeBroker) implements the interface for a specific platform
4. **API Layer**: Handles direct communication with the brokerage API

This separation allows the strategy to be used with different brokers by simply implementing a new broker class that conforms to the expected interface.

### Setup Instructions

1. **Dependencies**:
   Make sure you have the required dependencies:
   ```
   pip install pytz python-dotenv
   ```

2. **Configuration**:
   - Ensure your broker implementation includes all required methods
   - Configure your account credentials in a secure way using a `.env` file:
   ```
   TASTY_USERNAME=your_username
   TASTY_PASSWORD=your_password
   TASTY_ACCOUNT=your_account_number  # Specify which account to use for trading
   ```

3. **Starting the Strategy**:

```python
from api.tastytrade_api import TastytradeAPI
from broker.tastytrade_broker import TastytradeBroker
from strategies.spx_iron_condor_strategy import SPXIronCondorStrategy

# Initialize API with credentials
api = TastytradeAPI()

# Initialize broker
broker = TastytradeBroker()

# Initialize strategy with the broker
strategy = SPXIronCondorStrategy(broker)

# Let the strategy select the account
if not strategy.select_account():
    print("No accounts found. Please check your credentials.")
    exit(1)

# Ensure we're subscribed to market data for SPX
broker.start_streaming_service(strategy.account_number)

# Wait for market data to populate
import time
print("Waiting for market data to populate...")
time.sleep(30)

# Optionally adjust strategy parameters
strategy.target_delta_min = 0.16
strategy.target_delta_max = 0.25
strategy.exit_threshold = 0.90 
strategy.max_iron_condors = 6

# Run the strategy
print("Starting the strategy...")
strategy.run()
```

### Required Broker Interface

For a broker implementation to work with the SPX Iron Condor strategy, it must provide the following methods:

1. **select_iron_condor_strikes(underlying_symbol, expiration_date, delta_min, delta_max, put_wing_cost, call_wing_cost, target_put_credit, target_call_credit)**:
   - Selects appropriate strikes for an iron condor based on delta targets
   - Returns a dictionary with strike information

2. **calculate_max_iron_condor_contracts(account_number, strikes, max_buying_power, max_contracts, total_credit)**:
   - Calculates maximum number of contracts based on buying power
   - Returns an integer for the number of contracts

3. **scan_for_iron_condor_positions(account_number, underlying_symbol, expiration_date)**:
   - Finds existing iron condor positions
   - Returns a list of dictionaries with position information

4. **execute_iron_condor(account_number, underlying_symbol, expiration_date, strikes, num_contracts, credit_price)**:
   - Executes an iron condor trade
   - Returns a dictionary with trade information

5. **check_option_exit_condition(symbol, original_credit, num_contracts, exit_threshold)**:
   - Checks if an option position meets exit conditions
   - Returns a tuple of (should_exit, cost_to_close)

6. **close_option_position(account_number, symbol, quantity, action, order_type)**:
   - Closes an option position
   - Returns the order ID if successful, None otherwise

7. **start_streaming_service(account_number)**:
   - Starts streaming market data for the account
   - No return value expected

The broker must also maintain these attributes:
- `accounts`: A dictionary of account numbers to Account objects
- `symbols_to_monitor`: A structure for tracking symbol data

### Key Implementation Details

1. **Strategy Logic**:
   - The strategy selects and executes iron condor trades based on delta targets
   - It uses the broker to find appropriate strikes and execute trades
   - It monitors positions and applies exit rules consistently

2. **Broker Implementation**:
   - The broker translates strategy requests into platform-specific actions
   - It provides data and execution services without exposing API details
   - It manages platform-specific behavior and quirks

3. **API Layer**:
   - The API client handles direct communication with the brokerage platform
   - It provides methods for authentication, data retrieval, and order submission
   - It abstracts away HTTP requests, WebSockets, and other low-level details

### Creating a New Broker Implementation

To create a broker implementation for a different platform:

1. **Create a Broker Class**:
   - Implement all required methods from the broker interface
   - Maintain the necessary attributes (accounts, symbols_to_monitor)
   - Handle platform-specific details and quirks

2. **Create an API Client**:
   - Implement direct communication with the brokerage API
   - Handle authentication, data retrieval, and order submission
   - Manage WebSocket connections if applicable

3. **Example Structure**:
```python
class YourBroker:
    def __init__(self):
        self.api_client = YourAPIClient()
        self.accounts = {}
        self.symbols_to_monitor = {}
        self._initialize_accounts()
        
    def _initialize_accounts(self):
        # Fetch accounts from API
        # Populate self.accounts
        
    def select_iron_condor_strikes(self, underlying_symbol, expiration_date, delta_min, delta_max, 
                                 put_wing_cost, call_wing_cost, target_put_credit, target_call_credit):
        # Implementation specific to your platform
        
    # Implement other required methods
```

### Customization Options

The strategy has several parameters you can adjust:

```python
# Strategy entry timing
strategy.entry_time_eastern = "10:10"  # Format: "HH:MM"

# Delta range for strike selection
strategy.target_delta_min = 0.16
strategy.target_delta_max = 0.25

# Credit targets
strategy.target_put_credit = 5.0
strategy.target_call_credit = 5.0

# Wing costs
strategy.put_wing_cost = 0.15
strategy.call_wing_cost = 0.05

# Exit parameters
strategy.exit_threshold = 0.90  # Exit at 90% of credit received
strategy.exit_confirmation_time = 120  # 2 minutes confirmation period

# Position sizing
strategy.max_buying_power = 100000.0  # Cap on buying power
strategy.max_iron_condors = 6
```

### Production Considerations

1. **Account Configuration**:
   - Use the TASTY_ACCOUNT environment variable to specify which account to trade with
   - For multi-account setups, you can create different .env files for different configurations
   - Consider implementing account rotation or distribution strategies for large-scale implementations

2. **Broker Support**:
   - Ensure your broker implementation handles all edge cases
   - Test thoroughly with each supported brokerage platform
   - Consider adding fallback mechanisms for platform-specific failures

3. **Reliability**:
   - Implement error handling for network issues
   - Add retries for critical API calls
   - Implement a watchdog process to monitor the strategy

4. **Risk Management**:
   - Consider adding additional stop-loss mechanisms
   - Implement circuit breakers for unusual market conditions
   - Add alerts for trade entries and exits

5. **Performance**:
   - The strategy logs trades and performance
   - Consider implementing a more detailed performance tracking system
   - Store historical trade data for analysis

6. **Testing**:
   - Test the strategy on paper trading accounts first
   - Verify all calculations and logic
   - Run through multiple scenario tests before going live

7. **Position Recovery**:
   - The system can now recover state after restarts by scanning existing positions
   - Consider adding a database for more robust state persistence
   - Test the recovery process by intentionally restarting the strategy

### Troubleshooting

1. **Broker Interface Issues**:
   - Verify that your broker implementation provides all required methods
   - Check that method signatures match what the strategy expects
   - Ensure the broker maintains the required attributes

2. **Account Selection Issues**:
   - Verify that your TASTY_ACCOUNT environment variable is correctly set in .env
   - Check that the account number in TASTY_ACCOUNT matches one of your actual account numbers
   - Ensure you have proper permissions for the selected account
   - Look for warnings in the log about account selection fallbacks

3. **No Strikes Found**:
   - Check market data connection in your broker implementation
   - Verify that option chain data is being properly received
   - Check if delta data is available for SPX options

4. **Order Execution Issues**:
   - Verify account permissions for SPX options
   - Check account buying power
   - Verify the order structure is correct

5. **Monitoring Issues**:
   - Ensure market data streaming is working
   - Check for connectivity to the brokerage platform
   - Verify that option prices are being updated correctly

6. **Position Detection Issues**:
   - If existing positions aren't correctly identified, verify API permissions
   - Check the format of symbols to ensure they match expected patterns
   - Review logs for any errors during the position scanning process

7. **Credit Estimation Issues**:
   - If credits for existing positions seem incorrect, they might be using default estimates
   - Check if the order history API is functioning correctly
   - Consider manually setting more accurate credit values if needed
