## SPX 0 DTE Iron Condor Strategy - Implementation Guide

This guide explains how to set up and run the SPX Iron Condor Strategy.

### Strategy Overview

This strategy implements 0 DTE (0 Days To Expiration) SPX Iron Condor trades with the following specifications:

- **Entry Time**: 10:10 AM Eastern (8:10 AM Utah time)
- **Budget**: $100,000 max buying power
- **Strike Selection**: 16-25 delta range for short options
- **Credit Target**: ~$5 for puts and ~$5 for calls (~$10 total per iron condor)
- **Wing Costs**: $0.15 for put wings, $0.05 for call wings
- **Quantity**: Aims for ~6 iron condors while staying under buying power limit
- **Monitoring**: Short calls and short puts are monitored separately
- **Exit Criteria**:
  - Exit when cost to close exceeds 90% of credit received for at least 2 minutes
  - Let untested sides and wings expire worthless

### Setup Instructions

1. **Dependencies**:
   Make sure you have the required dependencies:
   ```
   pip install pytz
   ```

2. **Configuration**:
   - Ensure your TastytradeAPI implementation includes the buying power functions
   - Configure your account credentials in a secure way (e.g., environment variables)

3. **Starting the Strategy**:

```python
from tastytrade_api import TastytradeAPI
from tastytrade_broker import TastytradeBroker
from spx_iron_condor_strategy import SPXIronCondorStrategy

# Initialize API with credentials
api = TastytradeAPI()

# Initialize broker
broker = TastytradeBroker()

# Get first account
account_number = next(iter(broker.accounts.keys()), None)
if not account_number:
    print("No accounts found. Please check your credentials.")
    exit(1)

# Ensure we're subscribed to market data for SPX
broker.start_streaming_service(account_number)

# Wait for market data to populate
import time
print("Waiting for market data to populate...")
time.sleep(30)

# Initialize strategy
strategy = SPXIronCondorStrategy(api, broker)
strategy.set_account(account_number)

# Optionally adjust strategy parameters
strategy.target_delta_min = 0.16
strategy.target_delta_max = 0.25
strategy.exit_threshold = 0.90 
strategy.max_iron_condors = 6

# Run the strategy
print("Starting the strategy...")
strategy.run()
```

### Key Implementation Details

1. **Strike Selection**:
   - The strategy finds options in the 16-25 delta range for both puts and calls
   - It selects the highest delta put and lowest delta call in this range
   - Wing strikes are calculated to provide the desired credit amount

2. **Buying Power Management**:
   - The strategy calculates buying power reduction per iron condor
   - It determines the maximum number of contracts possible within the budget
   - It caps at 6 iron condors maximum, regardless of buying power

3. **Trade Execution**:
   - Executes at the configured entry time
   - Creates a 4-leg iron condor order at the calculated credit price
   - Tracks active trades for monitoring

4. **Trade Monitoring**:
   - Continuously monitors both short options separately
   - Tracks the cost to close each position
   - If cost to close exceeds 90% of credit received for at least 2 minutes, it exits that side
   - Allows untested sides to expire worthless

5. **Logging**:
   - Comprehensive logging to both console and log file
   - Tracks all decisions, actions, and trade details

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
strategy.max_buying_power = 100000.0
strategy.max_iron_condors = 6
```

### Production Considerations

1. **Reliability**:
   - Consider implementing error handling for network issues
   - Add retries for critical API calls
   - Implement a watchdog process to monitor the strategy

2. **Risk Management**:
   - Consider adding additional stop-loss mechanisms
   - Implement circuit breakers for unusual market conditions
   - Add alerts for trade entries and exits

3. **Performance**:
   - The strategy logs trades and performance
   - Consider implementing a more detailed performance tracking system
   - Store historical trade data for analysis

4. **Testing**:
   - Test the strategy on paper trading accounts first
   - Verify all calculations and logic
   - Run through multiple scenario tests before going live

### Troubleshooting

1. **No Strikes Found**:
   - Check market data connection
   - Verify that option chain data is being properly received
   - Check if delta data is available for SPX options

2. **Order Execution Issues**:
   - Verify account permissions for SPX options
   - Check account buying power
   - Verify the order structure is correct

3. **Monitoring Issues**:
   - Ensure market data streaming is working
   - Check for connectivity to the Tastytrade platform
   - Verify that option prices are being updated correctly
