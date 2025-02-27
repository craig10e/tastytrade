import datetime
import time
import pytz
import logging
from typing import Dict, List, Tuple, Optional, Any
from decimal import Decimal

from api.tastytrade_api import TastytradeAPI
from broker.tastytrade_broker import TastytradeBroker


class SPXIronCondorStrategy:
    """
    Implements a 0 DTE SPX Iron Condor trading strategy.
    
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
    """
    
    def __init__(self, api: TastytradeAPI, broker: TastytradeBroker):
        """
        Initialize the strategy with API and broker instances.
        
        Args:
            api: Authenticated TastytradeAPI instance
            broker: TastytradeBroker instance
        """
        self.api = api
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
    
    def set_account(self, account_number: str) -> None:
        """Set the account number to use for trading."""
        self.account_number = account_number
        self.logger.info(f"Using account: {account_number}")
    
    def is_entry_time(self) -> bool:
        """Check if it's time to enter trades based on the configured entry time."""
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
        """Get today's expiration date in YYYY-MM-DD format."""
        today = datetime.date.today()
        return today.strftime("%Y-%m-%d")
    
    def find_option_strikes(self) -> Dict[str, Any]:
        """
        Find appropriate option strikes for the iron condor based on delta targets.
        
        Returns:
            Dictionary with the selected strikes and option chain information.
        """
        expiration_date = self.get_current_expiration()
        underlying_symbol = "SPX"
        
        # Get option chain
        option_chain_data = self.api.get_option_chain(underlying_symbol)
        if not option_chain_data or "data" not in option_chain_data:
            self.logger.error(f"Failed to retrieve option chain for {underlying_symbol}")
            return {}
        
        option_chain = option_chain_data["data"]
        
        # Extract current price
        self.logger.info("Retrieving current SPX price...")
        quote_data = self.broker.symbols_to_monitor.get("SPX")
        if not quote_data or not quote_data.prices:
            self.logger.error("Failed to get current SPX price")
            return {}
        
        current_price = quote_data.prices[-1].last_price
        self.logger.info(f"Current SPX price: {current_price}")
        
        # Find today's expiration in the chain
        target_expiration = None
        for item in option_chain["items"]:
            for exp in item["expirations"]:
                if exp["expiration-date"] == expiration_date:
                    target_expiration = exp
                    break
            if target_expiration:
                break
        
        if not target_expiration:
            self.logger.error(f"No expiration found for today: {expiration_date}")
            return {}
        
        # Find suitable strikes
        short_put_strike = None
        long_put_strike = None
        short_call_strike = None
        long_call_strike = None
        
        # Process all strikes
        all_strikes = []
        for strike in target_expiration["strikes"]:
            strike_price = float(strike["strike-price"])
            
            # Get option data for this strike
            put_symbol = strike["put"]
            call_symbol = strike["call"]
            put_streamer_symbol = strike["put-streamer-symbol"]
            call_streamer_symbol = strike["call-streamer-symbol"]
            
            # Check if we have Greeks data for these options
            put_delta = None
            call_delta = None
            
            # Check in the broker's monitored symbols
            if put_streamer_symbol in self.broker.symbols_to_monitor:
                put_data = self.broker.symbols_to_monitor[put_streamer_symbol]
                if put_data.greeks and put_data.greeks[-1].delta is not None:
                    # Put deltas are negative, take absolute value for comparison
                    put_delta = abs(put_data.greeks[-1].delta)
            
            if call_streamer_symbol in self.broker.symbols_to_monitor:
                call_data = self.broker.symbols_to_monitor[call_streamer_symbol]
                if call_data.greeks and call_data.greeks[-1].delta is not None:
                    call_delta = call_data.greeks[-1].delta
            
            # Store strike with delta information
            all_strikes.append({
                "strike_price": strike_price,
                "put_symbol": put_symbol,
                "call_symbol": call_symbol,
                "put_streamer_symbol": put_streamer_symbol,
                "call_streamer_symbol": call_streamer_symbol,
                "put_delta": put_delta,
                "call_delta": call_delta
            })
        
        # Sort strikes by price
        all_strikes.sort(key=lambda x: x["strike_price"])
        
        # Find put strikes within delta range
        put_strikes = [s for s in all_strikes if s["put_delta"] is not None and 
                     self.target_delta_min <= s["put_delta"] <= self.target_delta_max and
                     s["strike_price"] < current_price]
        
        # Find call strikes within delta range
        call_strikes = [s for s in all_strikes if s["call_delta"] is not None and 
                      self.target_delta_min <= s["call_delta"] <= self.target_delta_max and
                      s["strike_price"] > current_price]
        
        if not put_strikes:
            self.logger.error("No suitable put strikes found in delta range")
            return {}
        
        if not call_strikes:
            self.logger.error("No suitable call strikes found in delta range")
            return {}
        
        # Select short put (highest strike within delta range)
        short_put = put_strikes[-1]
        short_put_strike = short_put["strike_price"]
        
        # Select short call (lowest strike within delta range)
        short_call = call_strikes[0]
        short_call_strike = short_call["strike_price"]
        
        # Find long put strike (enough spread for desired credit)
        put_spread = int(self.target_put_credit / self.put_wing_cost)
        long_put_index = next((i for i, s in enumerate(all_strikes) 
                             if s["strike_price"] == short_put_strike), None)
        
        if long_put_index is not None and long_put_index >= put_spread:
            long_put_strike = all_strikes[long_put_index - put_spread]["strike_price"]
        else:
            self.logger.error("Cannot find appropriate long put strike")
            return {}
        
        # Find long call strike (enough spread for desired credit)
        call_spread = int(self.target_call_credit / self.call_wing_cost)
        short_call_index = next((i for i, s in enumerate(all_strikes) 
                                if s["strike_price"] == short_call_strike), None)
        
        if short_call_index is not None and short_call_index + call_spread < len(all_strikes):
            long_call_strike = all_strikes[short_call_index + call_spread]["strike_price"]
        else:
            self.logger.error("Cannot find appropriate long call strike")
            return {}
        
        self.logger.info(f"Selected strikes - Long Put: {long_put_strike}, Short Put: {short_put_strike}, " +
                        f"Short Call: {short_call_strike}, Long Call: {long_call_strike}")
        
        return {
            "expiration_date": expiration_date,
            "current_price": current_price,
            "long_put_strike": long_put_strike,
            "short_put_strike": short_put_strike,
            "short_call_strike": short_call_strike,
            "long_call_strike": long_call_strike,
            "short_put_delta": short_put["put_delta"],
            "short_call_delta": short_call["call_delta"],
            "all_strikes": all_strikes
        }
    
    def calculate_max_contracts(self, strikes: Dict[str, Any]) -> int:
        """
        Calculate maximum number of iron condors we can trade based on buying power.
        
        Args:
            strikes: Dictionary with strike information
            
        Returns:
            Number of contracts to trade (integer)
        """
        if not self.account_number or not strikes:
            return 0
        
        # Calculate BPR for one iron condor
        bpr_per_contract = self.api.calculate_iron_condor_bpr(
            account_number=self.account_number,
            underlying_symbol="SPX",
            short_put_strike=strikes["short_put_strike"],
            long_put_strike=strikes["long_put_strike"],
            short_call_strike=strikes["short_call_strike"],
            long_call_strike=strikes["long_call_strike"],
            expiration_date=strikes["expiration_date"],
            quantity=1,
            limit_price=self.target_put_credit + self.target_call_credit  # Total credit
        )
        
        if not bpr_per_contract:
            self.logger.error("Failed to calculate buying power reduction")
            return 0
        
        self.logger.info(f"Buying power reduction per contract: ${bpr_per_contract:.2f}")
        
        # Calculate maximum contracts based on our budget
        max_contracts = int(self.max_buying_power / bpr_per_contract)
        
        # Cap at our desired maximum
        max_contracts = min(max_contracts, self.max_iron_condors)
        
        self.logger.info(f"Maximum contracts we can trade: {max_contracts}")
        return max_contracts
    
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
        
        # Prepare option symbols
        short_put = self.api._prepare_option_symbol(
            "SPX", strikes["expiration_date"], strikes["short_put_strike"], "P")
        long_put = self.api._prepare_option_symbol(
            "SPX", strikes["expiration_date"], strikes["long_put_strike"], "P")
        short_call = self.api._prepare_option_symbol(
            "SPX", strikes["expiration_date"], strikes["short_call_strike"], "C")
        long_call = self.api._prepare_option_symbol(
            "SPX", strikes["expiration_date"], strikes["long_call_strike"], "C")
        
        # Calculate total credit
        total_credit = self.target_put_credit + self.target_call_credit
        
        # Create legs for the order
        legs = [
            {"symbol": short_put, "quantity": num_contracts, "action": "Sell to Open", "instrument_type": "Equity Option"},
            {"symbol": long_put, "quantity": num_contracts, "action": "Buy to Open", "instrument_type": "Equity Option"},
            {"symbol": short_call, "quantity": num_contracts, "action": "Sell to Open", "instrument_type": "Equity Option"},
            {"symbol": long_call, "quantity": num_contracts, "action": "Buy to Open", "instrument_type": "Equity Option"}
        ]
        
        # Execute the order
        self.logger.info(f"Executing iron condor with {num_contracts} contracts at ${total_credit:.2f} credit")
        
        # First do a dry run to confirm everything looks good
        dry_run_result = self.api.dry_run_option_order(
            self.account_number, "SPX", legs, order_type="Limit", limit_price=total_credit)
        
        if not dry_run_result:
            self.logger.error("Dry run failed, cancelling trade")
            return {}
        
        if "errors" in dry_run_result and dry_run_result["errors"]:
            self.logger.error(f"Dry run returned errors: {dry_run_result['errors']}")
            return {}
        
        self.logger.info("Dry run successful, proceeding with actual order")
        
        # Submit the actual order
        response = self.api._request("POST", f"/accounts/{self.account_number}/orders", data={
            "order-type": "Limit",
            "time-in-force": "Day",
            "price": total_credit,
            "price-effect": "Credit",
            "legs": [self._dasherize_keys(leg) for leg in legs]
        })
        
        if not response or "data" not in response or "order" not in response["data"]:
            self.logger.error("Failed to submit order")
            return {}
        
        order = response["data"]["order"]
        order_id = order["id"]
        self.logger.info(f"Order submitted successfully with ID: {order_id}")
        
        # Track trade details
        trade = {
            "order_id": order_id,
            "num_contracts": num_contracts,
            "expiration_date": strikes["expiration_date"],
            "entry_time": datetime.datetime.now(),
            "put_credit": self.target_put_credit * num_contracts,
            "call_credit": self.target_call_credit * num_contracts,
            "total_credit": total_credit * num_contracts,
            "strikes": {
                "long_put": strikes["long_put_strike"],
                "short_put": strikes["short_put_strike"],
                "short_call": strikes["short_call_strike"],
                "long_call": strikes["long_call_strike"]
            },
            "symbols": {
                "long_put": long_put,
                "short_put": short_put,
                "short_call": short_call,
                "long_call": long_call
            },
            "put_closed": False,
            "call_closed": False,
            "put_exit_detected_time": None,
            "call_exit_detected_time": None
        }
        
        self.active_trades.append(trade)
        return trade
    
    def _dasherize_keys(self, data):
        """Helper to convert keys from snake_case to dash-case for API."""
        if isinstance(data, dict):
            return {k.replace("_", "-"): v for k, v in data.items()}
        return data
    
    def check_exit_conditions(self) -> None:
        """Check if exit conditions are met for any active trades."""
        for trade in self.active_trades:
            # Skip if both sides already closed
            if trade["put_closed"] and trade["call_closed"]:
                continue
            
            # Get current prices
            if not trade["put_closed"]:
                self._check_put_exit(trade)
            
            if not trade["call_closed"]:
                self._check_call_exit(trade)
    
    def _check_put_exit(self, trade: Dict[str, Any]) -> None:
        """Check exit conditions for the put side of a trade."""
        short_put_symbol = trade["symbols"]["short_put"]
        short_put_info = self.api.get_option_info(short_put_symbol)
        
        if not short_put_info or "data" not in short_put_info:
            self.logger.warning(f"Failed to get information for short put: {short_put_symbol}")
            return
        
        streamer_symbol = short_put_info["data"]["streamer-symbol"]
        
        # Check if we have price data
        if streamer_symbol not in self.broker.symbols_to_monitor:
            self.logger.warning(f"No price data for {streamer_symbol}")
            return
        
        symbol_data = self.broker.symbols_to_monitor[streamer_symbol]
        if not symbol_data.prices:
            return
        
        current_price = symbol_data.prices[-1].ask_price
        original_credit_per_contract = trade["put_credit"] / trade["num_contracts"]
        cost_to_close = current_price * trade["num_contracts"]
        
        # Check if cost to close exceeds our threshold
        if cost_to_close >= original_credit_per_contract * self.exit_threshold * trade["num_contracts"]:
            if trade["put_exit_detected_time"] is None:
                # First time detecting exit condition
                self.logger.info(f"Put exit condition detected. Cost to close: ${cost_to_close:.2f}, " +
                               f"Threshold: ${original_credit_per_contract * self.exit_threshold * trade['num_contracts']:.2f}")
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
        """Check exit conditions for the call side of a trade."""
        short_call_symbol = trade["symbols"]["short_call"]
        short_call_info = self.api.get_option_info(short_call_symbol)
        
        if not short_call_info or "data" not in short_call_info:
            self.logger.warning(f"Failed to get information for short call: {short_call_symbol}")
            return
        
        streamer_symbol = short_call_info["data"]["streamer-symbol"]
        
        # Check if we have price data
        if streamer_symbol not in self.broker.symbols_to_monitor:
            self.logger.warning(f"No price data for {streamer_symbol}")
            return
        
        symbol_data = self.broker.symbols_to_monitor[streamer_symbol]
        if not symbol_data.prices:
            return
        
        current_price = symbol_data.prices[-1].ask_price
        original_credit_per_contract = trade["call_credit"] / trade["num_contracts"]
        cost_to_close = current_price * trade["num_contracts"]
        
        # Check if cost to close exceeds our threshold
        if cost_to_close >= original_credit_per_contract * self.exit_threshold * trade["num_contracts"]:
            if trade["call_exit_detected_time"] is None:
                # First time detecting exit condition
                self.logger.info(f"Call exit condition detected. Cost to close: ${cost_to_close:.2f}, " +
                               f"Threshold: ${original_credit_per_contract * self.exit_threshold * trade['num_contracts']:.2f}")
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
        """Close the put side of a trade (buy back short put)."""
        self.logger.info(f"Closing put side of trade {trade['order_id']}")
        
        # Create order to buy back short put
        short_put_symbol = trade["symbols"]["short_put"]
        
        legs = [{
            "symbol": short_put_symbol,
            "quantity": trade["num_contracts"],
            "action": "Buy to Close",
            "instrument_type": "Equity Option"
        }]
        
        # Market order to close
        response = self.api._request("POST", f"/accounts/{self.account_number}/orders", data={
            "order-type": "Market",
            "time-in-force": "Day",
            "legs": [self._dasherize_keys(leg) for leg in legs]
        })
        
        if response and "data" in response and "order" in response["data"]:
            order_id = response["data"]["order"]["id"]
            self.logger.info(f"Successfully closed put side with order ID: {order_id}")
            trade["put_closed"] = True
        else:
            self.logger.error("Failed to close put side")
    
    def _close_call_side(self, trade: Dict[str, Any]) -> None:
        """Close the call side of a trade (buy back short call)."""
        self.logger.info(f"Closing call side of trade {trade['order_id']}")
        
        # Create order to buy back short call
        short_call_symbol = trade["symbols"]["short_call"]
        
        legs = [{
            "symbol": short_call_symbol,
            "quantity": trade["num_contracts"],
            "action": "Buy to Close",
            "instrument_type": "Equity Option"
        }]
        
        # Market order to close
        response = self.api._request("POST", f"/accounts/{self.account_number}/orders", data={
            "order-type": "Market",
            "time-in-force": "Day",
            "legs": [self._dasherize_keys(leg) for leg in legs]
        })
        
        if response and "data" in response and "order" in response["data"]:
            order_id = response["data"]["order"]["id"]
            self.logger.info(f"Successfully closed call side with order ID: {order_id}")
            trade["call_closed"] = True
        else:
            self.logger.error("Failed to close call side")
    
    def run(self) -> None:
        """Main method to run the trading strategy."""
        if not self.account_number:
            self.logger.error("Account number not set. Call set_account() first.")
            return
            
        self.logger.info("Starting SPX Iron Condor Strategy")
        
        # First, ensure we're subscribed to SPX option data
        self.broker.start_streaming_service(self.account_number)
        
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
                
                # Entry logic
                if not self.active_trades and self.is_entry_time():
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


def initialize_from_existing_positions(self):
    """Scan for and identify existing iron condor positions."""
    if not self.account_number:
        return

    # Get current positions
    positions = self.api.get_positions(self.account_number)
    if not positions:
        return

    # Group positions by expiration date
    spx_positions_by_expiration = {}
    today = datetime.date.today().strftime("%Y-%m-%d")

    for position in positions:
        if position["underlying-symbol"] == "SPX" and position["instrument-type"] == "Equity Option":
            # Get option details
            option_info = self.api.get_option_info(position["symbol"])
            if not option_info or "data" not in option_info:
                continue

            option_data = option_info["data"]
            expiration = option_data.get("expiration-date")

            # Focus only on today's expiration (0 DTE)
            if expiration != today:
                continue

            if expiration not in spx_positions_by_expiration:
                spx_positions_by_expiration[expiration] = []

            spx_positions_by_expiration[expiration].append({
                "symbol": position["symbol"],
                "quantity": position["quantity"],
                "direction": position["quantity-direction"],
                "option_type": option_data.get("option-type"),
                "strike_price": option_data.get("strike-price"),
                "streamer_symbol": option_data.get("streamer-symbol")
            })

    # Identify iron condor structures
    for expiration, positions in spx_positions_by_expiration.items():
        # Find puts and calls
        puts = [p for p in positions if p["option_type"] == "P"]
        calls = [p for p in positions if p["option_type"] == "C"]

        # Sort by strike
        puts.sort(key=lambda x: float(x["strike_price"]))
        calls.sort(key=lambda x: float(x["strike_price"]))

        # Look for iron condor structure (long put, short put, short call, long call)
        # This is simplified and would need more robust pattern matching
        if len(puts) >= 2 and len(calls) >= 2:
            # Check for long put (negative quantity)
            long_puts = [p for p in puts if p["direction"] == "Long"]
            short_puts = [p for p in puts if p["direction"] == "Short"]
            long_calls = [p for p in calls if p["direction"] == "Long"]
            short_calls = [p for p in calls if p["direction"] == "Short"]

            if long_puts and short_puts and long_calls and short_calls:
                # Found a potential iron condor, track it
                self.logger.info(f"Found existing iron condor position for expiration {expiration}")

                # Create a trade structure for monitoring
                # Note: We don't know original entry prices, but can estimate
                trade = {
                    "order_id": "existing",
                    "num_contracts": min(
                        abs(long_puts[0]["quantity"]),
                        abs(short_puts[0]["quantity"]),
                        abs(short_calls[0]["quantity"]),
                        abs(long_calls[0]["quantity"])
                    ),
                    "expiration_date": expiration,
                    "entry_time": datetime.datetime.now() - datetime.timedelta(minutes=30),  # Estimate
                    "put_credit": 5.0,  # Estimated credit, would need market data
                    "call_credit": 5.0,  # Estimated credit, would need market data
                    "total_credit": 10.0,  # Estimated total
                    "strikes": {
                        "long_put": float(long_puts[0]["strike_price"]),
                        "short_put": float(short_puts[0]["strike_price"]),
                        "short_call": float(short_calls[0]["strike_price"]),
                        "long_call": float(long_calls[0]["strike_price"])
                    },
                    "symbols": {
                        "long_put": long_puts[0]["symbol"],
                        "short_put": short_puts[0]["symbol"],
                        "short_call": short_calls[0]["symbol"],
                        "long_call": long_calls[0]["symbol"]
                    },
                    "put_closed": False,
                    "call_closed": False,
                    "put_exit_detected_time": None,
                    "call_exit_detected_time": None
                }

                self.active_trades.append(trade)


def calculate_available_buying_power(self):
    """Get actual available buying power from account."""
    if not self.account_number:
        return self.max_buying_power

    account_balance = self.api._request("GET", f"/accounts/{self.account_number}/balances")

    if not account_balance or "data" not in account_balance:
        self.logger.warning("Could not retrieve account balance, using default max")
        return self.max_buying_power

    # The 'derivative-buying-power' field holds available buying power for options
    available_bp = account_balance["data"].get("derivative-buying-power", self.max_buying_power)
    self.logger.info(f"Actual available buying power: ${available_bp}")

    return min(float(available_bp), self.max_buying_power)


# Example usage:
if __name__ == "__main__":
    # Initialize API and broker
    api = TastytradeAPI()
    broker = TastytradeBroker()
    
    # Initialize strategy
    strategy = SPXIronCondorStrategy(api, broker)
    
    # Set account
    account_number = broker.accounts.keys()[0] if broker.accounts else None
    if account_number:
        strategy.set_account(account_number)
        
        # Run strategy
        strategy.run()
    else:
        print("No accounts found. Please check your credentials.")
