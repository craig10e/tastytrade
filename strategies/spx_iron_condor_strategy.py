import os
import datetime
import time
import pytz
import logging
from typing import Dict, List, Tuple, Optional, Any, Set
from decimal import Decimal
from dotenv import load_dotenv


class SPXIronCondorStrategy:
    """
    Implements a 0 DTE SPX Iron Condor trading strategy.
    
    This strategy is broker-agnostic and can work with any broker implementation
    that provides the required interface methods.
    
    The strategy:
    - Trades 0 DTE SPX iron condors at 10:10 AM Eastern time
    - Uses a max of $100,000 buying power
    - Targets options in the 16-25 delta range
    - Aims to receive about $5 credit for puts and $5 for calls ($10 total per iron condor)
    - Pays $0.15 for put wings and $0.05 for call wings
    - Aims to enter about 6 iron condors without exceeding buying power limit
    - Monitors short calls and puts separately
    - Exits when cost to close exceeds 90% of credit received for at least 2 minutes
    - Lets untested sides and wings run to expiration
    
    Features:
    - Scans for existing iron condor positions at startup
    - Uses actual account buying power for position sizing
    - Applies consistent exit rules to both new and existing positions
    """
    
    def __init__(self, broker):
        """
        Initialize the strategy with a broker instance.
        
        Args:
            broker: Broker implementation providing required interface methods
        """
        # Load environment variables
        load_dotenv()
        
        self.broker = broker
        self.account_number = None
        self.max_buying_power = 100000.0
        
        # Strategy configuration
        self.entry_time_eastern = "10:10"
        self.target_delta_min = 0.16
        self.target_delta_max = 0.25
        self.target_put_credit = 5.0
        self.target_call_credit = 5.0
        self.put_wing_cost = 0.15
        self.call_wing_cost = 0.05
        self.max_iron_condors = 6
        self.exit_threshold = 0.90  # Exit when cost to close exceeds 90% of credit
        self.exit_confirmation_time = 120  # 2 minutes in seconds
        
        # Strategy state
        self.active_trades = []
        self.monitoring = False
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("spx_iron_condor_strategy.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def select_account(self) -> bool:
        """
        Select the account to use for trading based on environment variable.
        
        First tries to use the account specified in TASTY_ACCOUNT environment variable.
        Falls back to the first available account if TASTY_ACCOUNT is not set or not found.
        
        Returns:
            True if an account was successfully selected, False otherwise
        """
        if not hasattr(self.broker, 'accounts') or not self.broker.accounts:
            self.logger.error("No accounts available in broker. Check credentials and permissions.")
            return False
            
        # Try to get the account from environment variable
        preferred_account = os.getenv("TASTY_ACCOUNT")
        
        if preferred_account and preferred_account in self.broker.accounts:
            self.account_number = preferred_account
            self.logger.info(f"Using account from TASTY_ACCOUNT: {self.account_number}")
            return True
            
        elif preferred_account:
            self.logger.warning(f"Specified account {preferred_account} not found in available accounts.")
            self.logger.warning(f"Available accounts: {list(self.broker.accounts.keys())}")
            
        # Fall back to first account
        self.account_number = list(self.broker.accounts.keys())[0]
        self.logger.info(f"Using first available account: {self.account_number}")
        return True
    
    def set_account(self, account_number: str) -> None:
        """
        Set the account number to use for trading.
        
        Args:
            account_number: The account number to use
        """
        if account_number in self.broker.accounts:
            self.account_number = account_number
            self.logger.info(f"Using account: {account_number}")
        else:
            self.logger.error(f"Account {account_number} not found in available accounts.")
            self.logger.error(f"Available accounts: {list(self.broker.accounts.keys())}")
            raise ValueError(f"Account {account_number} not found in available accounts.")
    
    def is_entry_time(self) -> bool:
        """
        Check if it's time to enter trades based on the configured entry time.
        
        Returns:
            True if current time is within entry window, False otherwise
        """
        eastern = pytz.timezone('US/Eastern')
        now = datetime.datetime.now(eastern)
        target_time = datetime.datetime.strptime(
            f"{now.strftime('%Y-%m-%d')} {self.entry_time_eastern}", 
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=eastern)
        
        # Allow entry within a 5-minute window of the target time
        time_diff = abs((now - target_time).total_seconds())
        return time_diff <= 300  # 5 minutes
    
    def get_current_expiration(self) -> str:
        """
        Get today's expiration date in YYYY-MM-DD format.
        
        Returns:
            Today's date formatted as YYYY-MM-DD
        """
        today = datetime.date.today()
        return today.strftime("%Y-%m-%d")
    
    def find_option_strikes(self) -> Dict[str, Any]:
        """
        Find appropriate option strikes for the iron condor based on delta targets.
        
        Returns:
            Dictionary with strike information.
        """
        # Get today's expiration date
        expiration_date = self.get_current_expiration()
        
        # Use the broker to select strikes for an iron condor
        return self.broker.select_iron_condor_strikes(
            underlying_symbol="SPX",
            expiration_date=expiration_date,
            delta_min=self.target_delta_min,
            delta_max=self.target_delta_max,
            put_wing_cost=self.put_wing_cost,
            call_wing_cost=self.call_wing_cost,
            target_put_credit=self.target_put_credit,
            target_call_credit=self.target_call_credit
        )
    
    def calculate_max_contracts(self, strikes: Dict[str, Any]) -> int:
        """
        Calculate maximum number of iron condors to trade based on buying power.
        
        Args:
            strikes: Dictionary with strike information
            
        Returns:
            Number of contracts to trade (integer)
        """
        if not self.account_number or not strikes:
            return 0
        
        # Calculate the total credit per iron condor
        total_credit = self.target_put_credit + self.target_call_credit
        
        # Use the broker to calculate max contracts
        return self.broker.calculate_max_iron_condor_contracts(
            account_number=self.account_number,
            strikes=strikes,
            max_buying_power=self.max_buying_power,
            max_contracts=self.max_iron_condors,
            total_credit=total_credit
        )
    
    def execute_entry(self, strikes: Dict[str, Any], num_contracts: int) -> Dict[str, Any]:
        """
        Execute the iron condor entry trade.
        
        Args:
            strikes: Dictionary with strike information
            num_contracts: Number of contracts to trade
            
        Returns:
            Dictionary with trade information
        """
        if not self.account_number or num_contracts <= 0:
            return {}
        
        # Calculate total credit
        total_credit = self.target_put_credit + self.target_call_credit
        
        self.logger.info(f"Executing iron condor with {num_contracts} contracts at ${total_credit:.2f} credit")
        
        # Use the broker to execute the iron condor
        trade_info = self.broker.execute_iron_condor(
            account_number=self.account_number,
            underlying_symbol="SPX",
            expiration_date=strikes["expiration_date"],
            strikes=strikes,
            num_contracts=num_contracts,
            credit_price=total_credit
        )
        
        if not trade_info:
            self.logger.error("Failed to execute iron condor trade")
            return {}
        
        self.logger.info(f"Order submitted successfully with ID: {trade_info['order_id']}")
        
        # Add put/call specific credits and exit tracking to the trade info
        trade_info["put_credit"] = self.target_put_credit * num_contracts
        trade_info["call_credit"] = self.target_call_credit * num_contracts
        trade_info["put_closed"] = False
        trade_info["call_closed"] = False
        trade_info["put_exit_detected_time"] = None
        trade_info["call_exit_detected_time"] = None
        
        self.active_trades.append(trade_info)
        return trade_info
    
    def initialize_from_existing_positions(self) -> None:
        """
        Scan for and identify existing iron condor positions.
        
        Uses the broker to find existing positions and adds them
        to the active_trades list for monitoring and management.
        """
        if not self.account_number:
            return

        self.logger.info("Scanning for existing iron condor positions...")
        
        # Use the broker to scan for iron condor positions
        iron_condors = self.broker.scan_for_iron_condor_positions(
            account_number=self.account_number,
            underlying_symbol="SPX",
            expiration_date=self.get_current_expiration()
        )
        
        if not iron_condors:
            self.logger.info("No existing iron condor positions found")
            return
        
        for ic in iron_condors:
            # Add monitoring-specific fields to the trade info
            # Split total credit evenly between put and call sides if not specified
            total_credit = ic.get("total_credit", 0.0)
            put_credit = ic.get("put_credit", total_credit / 2)
            call_credit = ic.get("call_credit", total_credit / 2)
            
            trade = {
                **ic,  # Include all original fields
                "put_credit": put_credit,
                "call_credit": call_credit,
                "put_closed": False,
                "call_closed": False,
                "put_exit_detected_time": None,
                "call_exit_detected_time": None
            }
            
            self.active_trades.append(trade)
            self.logger.info(f"Added existing iron condor to active trades with {trade['num_contracts']} contracts")
    
    def check_exit_conditions(self) -> None:
        """Check if exit conditions are met for any active trades."""
        for trade in self.active_trades:
            # Skip if both sides already closed
            if trade["put_closed"] and trade["call_closed"]:
                continue
            
            # Check put and call exit conditions
            if not trade["put_closed"]:
                self._check_put_exit(trade)
            
            if not trade["call_closed"]:
                self._check_call_exit(trade)
    
    def _check_put_exit(self, trade: Dict[str, Any]) -> None:
        """
        Check exit conditions for the put side of a trade.
        
        Args:
            trade: The trade to check exit conditions for
        """
        short_put_symbol = trade["symbols"]["short_put"]
        
        # Use the broker to check exit condition for the short put
        should_exit, cost_to_close = self.broker.check_option_exit_condition(
            symbol=short_put_symbol,
            original_credit=trade["put_credit"] / trade["num_contracts"],
            num_contracts=trade["num_contracts"],
            exit_threshold=self.exit_threshold
        )
        
        if should_exit:
            if trade["put_exit_detected_time"] is None:
                # First time detecting exit condition
                self.logger.info(f"Put exit condition detected. Cost to close: ${cost_to_close:.2f}, " +
                               f"Original credit: ${trade['put_credit']:.2f}, " +
                               f"Threshold: ${trade['put_credit'] * self.exit_threshold:.2f}")
                trade["put_exit_detected_time"] = datetime.datetime.now()
            else:
                # Check if condition has persisted long enough
                time_since_detection = (datetime.datetime.now() - trade["put_exit_detected_time"]).total_seconds()
                if time_since_detection >= self.exit_confirmation_time:
                    self._close_put_side(trade)
        else:
            # Reset detection time if price improves
            trade["put_exit_detected_time"] = None
    
    def _check_call_exit(self, trade: Dict[str, Any]) -> None:
        """
        Check exit conditions for the call side of a trade.
        
        Args:
            trade: The trade to check exit conditions for
        """
        short_call_symbol = trade["symbols"]["short_call"]
        
        # Use the broker to check exit condition for the short call
        should_exit, cost_to_close = self.broker.check_option_exit_condition(
            symbol=short_call_symbol,
            original_credit=trade["call_credit"] / trade["num_contracts"],
            num_contracts=trade["num_contracts"],
            exit_threshold=self.exit_threshold
        )
        
        if should_exit:
            if trade["call_exit_detected_time"] is None:
                # First time detecting exit condition
                self.logger.info(f"Call exit condition detected. Cost to close: ${cost_to_close:.2f}, " +
                               f"Original credit: ${trade['call_credit']:.2f}, " +
                               f"Threshold: ${trade['call_credit'] * self.exit_threshold:.2f}")
                trade["call_exit_detected_time"] = datetime.datetime.now()
            else:
                # Check if condition has persisted long enough
                time_since_detection = (datetime.datetime.now() - trade["call_exit_detected_time"]).total_seconds()
                if time_since_detection >= self.exit_confirmation_time:
                    self._close_call_side(trade)
        else:
            # Reset detection time if price improves
            trade["call_exit_detected_time"] = None
    
    def _close_put_side(self, trade: Dict[str, Any]) -> None:
        """
        Close the put side of a trade (buy back short put).
        
        Args:
            trade: The trade to close the put side for
        """
        self.logger.info(f"Closing put side of trade {trade['order_id']}")
        
        # Use the broker to close the short put position
        short_put_symbol = trade["symbols"]["short_put"]
        
        order_id = self.broker.close_option_position(
            account_number=self.account_number,
            symbol=short_put_symbol,
            quantity=trade["num_contracts"],
            action="Buy to Close"
        )
        
        if order_id:
            self.logger.info(f"Successfully closed put side with order ID: {order_id}")
            trade["put_closed"] = True
        else:
            self.logger.error("Failed to close put side")
    
    def _close_call_side(self, trade: Dict[str, Any]) -> None:
        """
        Close the call side of a trade (buy back short call).
        
        Args:
            trade: The trade to close the call side for
        """
        self.logger.info(f"Closing call side of trade {trade['order_id']}")
        
        # Use the broker to close the short call position
        short_call_symbol = trade["symbols"]["short_call"]
        
        order_id = self.broker.close_option_position(
            account_number=self.account_number,
            symbol=short_call_symbol,
            quantity=trade["num_contracts"],
            action="Buy to Close"
        )
        
        if order_id:
            self.logger.info(f"Successfully closed call side with order ID: {order_id}")
            trade["call_closed"] = True
        else:
            self.logger.error("Failed to close call side")
    
    def run(self) -> None:
        """Main method to run the trading strategy."""
        # Select account if not already set
        if not self.account_number:
            if not self.select_account():
                self.logger.error("No valid account available. Exiting.")
                return
            
        self.logger.info("Starting SPX Iron Condor Strategy")
        
        # First, ensure we're subscribed to market data
        self.broker.start_streaming_service(self.account_number)
        
        # Scan for existing positions
        self.initialize_from_existing_positions()
        
        # If existing trades found, enable monitoring
        if self.active_trades:
            self.logger.info(f"Found {len(self.active_trades)} existing trades, enabling monitoring")
            self.monitoring = True
        
        try:
            while True:
                current_time = datetime.datetime.now(pytz.timezone('US/Eastern'))
                
                # Check if it's a trading day
                if current_time.weekday() >= 5:  # Saturday or Sunday
                    self.logger.info("Weekend - market closed. Sleeping for 1 hour.")
                    time.sleep(3600)
                    continue
                
                # Check if market is open
                market_open = datetime.time(9, 30)
                market_close = datetime.time(16, 0)
                current_time_only = current_time.time()
                
                if not (market_open <= current_time_only <= market_close):
                    self.logger.info("Market closed. Sleeping for 15 minutes.")
                    time.sleep(900)
                    continue
                
                # Entry logic - only run if no active trades with today's expiration
                today = datetime.date.today().strftime("%Y-%m-%d")
                todays_trades = [t for t in self.active_trades if t["expiration_date"] == today]
                
                if not todays_trades and self.is_entry_time():
                    self.logger.info("Entry time detected. Looking for trades...")
                    
                    # Find appropriate strikes
                    strikes = self.find_option_strikes()
                    if not strikes:
                        self.logger.error("Failed to find appropriate strikes. Trying again in 1 minute.")
                        time.sleep(60)
                        continue
                    
                    # Calculate max contracts
                    num_contracts = self.calculate_max_contracts(strikes)
                    if num_contracts <= 0:
                        self.logger.error("Cannot trade any contracts. Trying again in 1 minute.")
                        time.sleep(60)
                        continue
                    
                    # Execute the trade
                    trade = self.execute_entry(strikes, num_contracts)
                    if not trade:
                        self.logger.error("Failed to execute trade. Trying again in 1 minute.")
                        time.sleep(60)
                        continue
                    
                    self.logger.info(f"Successfully entered iron condor trade with {num_contracts} contracts")
                    self.monitoring = True
                
                # Exit logic - check for conditions to close positions
                if self.monitoring and self.active_trades:
                    self.check_exit_conditions()
                
                # Check if we need to keep monitoring
                active_orders = [t for t in self.active_trades if not (t["put_closed"] and t["call_closed"])]
                if not active_orders:
                    self.monitoring = False
                
                # Sleep between checks
                time.sleep(10)
        
        except KeyboardInterrupt:
            self.logger.info("Strategy stopped by user")
        except Exception as e:
            self.logger.exception(f"Error in strategy: {e}")
        finally:
            self.logger.info("Strategy stopped")


# Example usage:
if __name__ == "__main__":
    # Import only at usage point to avoid circular imports
    from api.tastytrade_api import TastytradeAPI
    from broker.tastytrade_broker import TastytradeBroker
    
    # Initialize broker
    api = TastytradeAPI()
    broker = TastytradeBroker()
    
    # Initialize strategy with the broker
    strategy = SPXIronCondorStrategy(broker)
    
    # Let the strategy select the account from environment or fall back to first account
    if not strategy.select_account():
        print("No accounts found. Please check your credentials.")
        exit(1)
    
    # Run strategy
    strategy.run()
