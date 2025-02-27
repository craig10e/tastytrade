from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any

from ..api.tastytrade_api import TastytradeAPI
from ..models.account import Account
from ..models.position import Position
from ..models.order import Order
from ..models.symbol import Symbol


class TastytradeBroker:
    """
    High-level broker implementation for interacting with the Tastytrade platform.
    
    Manages accounts, positions, and orders through the TastytradeAPI.
    Provides functionality for streaming market data and executing option orders.
    
    Attributes:
        name (str): Name of the broker.
        api_client (TastytradeAPI): Instance of the Tastytrade API client.
        accounts (Dict[str, Account]): Map of account numbers to Account objects.
        symbols_to_monitor (Dict[str, Symbol]): Map of symbols to Symbol tracking objects.
        orders_to_fill (List[Order]): List of orders pending execution.
    """

    def __init__(self) -> None:
        """
        Initialize the Tastytrade broker.
        
        Creates an API client and fetches account information.
        """
        self.name = 'Tastytrade'
        self.api_client = TastytradeAPI()
        self.accounts: Dict[str, Account] = {}
        self.symbols_to_monitor: Dict[str, Symbol] = {'SPX': Symbol('SPX')}
        self.orders_to_fill: List[Order] = []
        self._fetch_accounts()

    def process_orders(self) -> None:
        """
        Process all pending orders.
        
        For each order in orders_to_fill:
        1. If filled, consider removing (based on user preference)
        2. If failed (rejected, cancelled, expired), remove and log
        3. If live and time elapsed, adjust the order
        4. If order ID exists, check status
        5. If symbol exists, create the order
        6. If option chain exists, find the appropriate symbol
        7. Otherwise, fetch the option chain
        """
        # Create a list to track orders that should be removed
        orders_to_remove = []
        
        for order in self.orders_to_fill:
            if order.order_status == 'Filled':
                # Order is complete, mark for removal
                orders_to_remove.append(order)
                print(f"Order {order.order_id} for {order.symbol} is filled and will be removed from tracking.")
                
            elif order.order_status in ("Removed", "Rejected", "Cancelled", "Expired"):
                # Order failed, mark for removal and log
                orders_to_remove.append(order)
                print(f"Order {order.order_id} for {order.symbol} {order.order_status}. Removing from tracking.")
                
            elif order.order_id == 'Live':
                # Check if enough time has elapsed to adjust the order
                elapsed = datetime.now() - order.datetime if order.datetime else timedelta(seconds=order.seconds_to_wait + 1)
                if elapsed > timedelta(seconds=order.seconds_to_wait):
                    self._adjust_order(order)
                    
            elif order.order_id:
                # Check status of existing order
                order.order_status = self.api_client.get_order_status(order.account, order.order_id)
                
            elif order.symbol:
                # Check trend if applicable before creating order
                if order.streamer_symbol in self.symbols_to_monitor:
                    symbol_data = self.symbols_to_monitor[order.streamer_symbol]
                    # For buy orders, prefer uptrend; for sell orders, prefer downtrend
                    trend_favorable = (
                        (symbol_data.is_trending_up and order.action.startswith('Buy')) or
                        (not symbol_data.is_trending_up and order.action.startswith('Sell'))
                    )
                    if trend_favorable or symbol_data.is_trending_up is None:
                        # Create the order if trend is favorable or can't determine trend
                        order.order_id = self._create_order(order)
                        order.datetime = datetime.now()
                    else:
                        print(f"Delaying order for {order.symbol} due to unfavorable trend.")
                else:
                    # No trend data available, proceed with order creation
                    order.order_id = self._create_order(order)
                    order.datetime = datetime.now()
                    
            elif order.option_chain:
                # Find the appropriate symbol from the option chain
                symbol_data = self._find_symbol_from_option_chain(order)
                if symbol_data:
                    order.symbol, order.streamer_symbol, order.strike_price = symbol_data
                    
            else:
                # Fetch the option chain
                order.option_chain = self._add_option_chain_to_streaming(order)
        
        # Remove processed orders
        for order in orders_to_remove:
            self.orders_to_fill.remove(order)

    def option_order(
        self, 
        account: Optional[str] = None, 
        underlying_symbol: str = 'SPX', 
        action: str = 'Buy to Open', 
        option_type: str = 'C',
        quantity: int = 1, 
        dte: int = 0, 
        delta: Optional[float] = None, 
        price: Optional[float] = None
    ) -> None:
        """
        Create and queue a new option order.
        
        Args:
            account: Account number to use for the order.
            underlying_symbol: The ticker symbol of the underlying asset.
            action: Order action ('Buy to Open', 'Sell to Open', etc.).
            option_type: Option type ('C' for call or 'P' for put).
            quantity: Number of contracts.
            dte: Days to expiration.
            delta: Target delta value for option selection.
            price: Target price for option selection.
        """
        underlying_symbol = 'SPXW' if underlying_symbol == 'SPX' else underlying_symbol  # Need weeklies
        self.orders_to_fill.append(
            Order(account=account, underlying_symbol=underlying_symbol, action=action,
            option_type=option_type, quantity=quantity, dte=dte, delta=delta, price=price)
        )

    def start_streaming_service(self, account: str) -> None:
        """
        Start the market data and account data streaming services.
        
        Sets up handlers for quote and Greeks updates, then connects to the
        streaming services for the specified account.
        
        Args:
            account: Account number to stream data for.
        """
        self.api_client.add_quote_handler(self.handle_quote_update)
        self.api_client.add_greeks_handler(self.handle_greeks_update)

        streamer_symbols = []
        for position in self.accounts[account].positions:
            streamer_symbols.append(position.streamer_symbol)
        self.api_client.connect_market_data_stream(options_to_stream=list(set(streamer_symbols)))
        self.api_client.connect_account_data_stream()
        self.api_client.start_heartbeat_thread()

    def handle_quote_update(self, symbol: str, quote_data: Dict[str, Any]) -> None:
        """
        Handle quote updates from the streaming service.
        
        Updates the symbols_to_monitor with the latest quote data.
        
        Args:
            symbol: The symbol for which the quote was received.
            quote_data: Dictionary with the quote data.
        """
        print("Strategy Quote Handler called with", symbol, quote_data)
        if symbol in self.symbols_to_monitor:
            self.symbols_to_monitor[symbol].update_prices(quote_data)

    def handle_greeks_update(self, symbol: str, greeks_data: Dict[str, Any]) -> None:
        """
        Handle Greeks updates from the streaming service.
        
        Updates the symbols_to_monitor with the latest Greeks data.
        
        Args:
            symbol: The symbol for which the Greeks were received.
            greeks_data: Dictionary with the Greeks data.
        """
        print("Strategy Greeks Handler called with", symbol, greeks_data)
        if symbol in self.symbols_to_monitor:
            self.symbols_to_monitor[symbol].update_greeks(greeks_data)

    def _adjust_order(self, order: Order) -> None:
        """
        Adjust a limit order by increasing the limit price.
        
        Args:
            order: The Order to adjust.
        """
        order.adjust_limit_distance()
        symbol = self.symbols_to_monitor[order.streamer_symbol]
        bid_ask_distance = symbol.prices[-1].ask_price - symbol.prices[-1].bid_price
        limit_price = symbol.prices[-1].bid_price + (bid_ask_distance * order.limit_distance)
        response = self.api_client.replace_option_order(order.account, order.order_id, limit_price)
        print(response)

    def _create_order(self, order: Order) -> Optional[str]:
        """
        Create an order with the Tastytrade API.
        
        Calculates an appropriate limit price based on the current bid/ask spread
        and the order's limit_distance parameter.
        
        Args:
            order: The Order to create.
            
        Returns:
            The order ID if created successfully, or None if creation failed.
        """
        symbol = self.symbols_to_monitor[order.streamer_symbol]
        bid_ask_distance = symbol.prices[-1].ask_price - symbol.prices[-1].bid_price
        limit_price = symbol.prices[-1].bid_price + (bid_ask_distance * order.limit_distance)
        response = self.api_client.create_option_order(
            order.account, 
            order.underlying_symbol,
            order.expiration_date, 
            order.strike_price, 
            order.option_type,
            action=order.action, 
            quantity=order.quantity,
            order_type='Limit', 
            price=limit_price,
            time_in_force='Day'
        )
        
        if response and "data" in response and "order" in response["data"] and "id" in response["data"]["order"]:
            order_id = response["data"]["order"]["id"]
            return order_id
        return None

    def _find_symbol_from_option_chain(self, order: Order) -> Optional[Tuple[str, str, float]]:
        """
        Find an appropriate option symbol from the option chain.
        
        For calls, finds the first option with delta <= target_delta.
        For puts, finds the last option with delta <= target_delta.
        If price is specified, finds the option with price in the bid/ask range.
        
        Args:
            order: The Order containing selection criteria.
            
        Returns:
            Tuple of (symbol, streamer_symbol, strike_price) if found, None otherwise.
        """
        order_symbol = None
        order_streamer_symbol = None
        order_strike_price = None
        
        if not order.option_chain:
            return None
            
        for strike in order.option_chain:
            streamer_symbol = strike['streamer-symbol']
            
            if streamer_symbol not in self.symbols_to_monitor:
                continue  # Skip if we don't have price data for this symbol
                
            symbol_data = self.symbols_to_monitor[streamer_symbol]
            
            if not symbol_data.prices:
                continue  # Skip if no price data available
                
            if order.price and symbol_data.prices[-1].bid_price < order.price <= symbol_data.prices[-1].ask_price:
                # Found an option with price in the bid/ask range
                order_symbol = strike['symbol']
                order_streamer_symbol = streamer_symbol
                order_strike_price = float(strike['strike-price'])
                break
                
            elif order.delta and symbol_data.greeks and symbol_data.greeks[-1].delta <= order.delta:
                # Found an option with delta <= target_delta
                order_symbol = strike['symbol']
                order_streamer_symbol = streamer_symbol
                order_strike_price = float(strike['strike-price'])
                
                if order.option_type == 'C':
                    # For calls, take the first strike with delta <= target_delta
                    break
                # For puts, continue to find the last strike with delta <= target_delta
        
        if order_symbol and order_streamer_symbol and order_strike_price:
            return (order_symbol, order_streamer_symbol, order_strike_price)
        return None

    def _add_option_chain_to_streaming(self, order: Optional[Order] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch option chain data and add relevant strikes to monitoring.
        
        Args:
            order: The Order containing selection criteria.
            
        Returns:
            List of option data dictionaries for relevant strikes, or None if retrieval fails.
        """
        if not order:
            return None
            
        option_chain = self.api_client.get_option_chain(order.underlying_symbol)
        if not option_chain:
            print(f"Failed to retrieve {order.underlying_symbol} option chain.")
            return None

        expiration_str = order.expiration_date.strftime("%Y-%m-%d")
        target_expiration = None

        option_chain_data = option_chain['data']
        option_chain_items = option_chain_data['items']
        for item in option_chain_items:
            for expiration in item['expirations']:
                if expiration['expiration-date'] == expiration_str:
                    target_expiration = expiration
                    break
                    
        if target_expiration is None:
            print(f"No expiration found for {expiration_str}.")
            return None

        # Get the current price of SPX (or use another reference if needed)
        spx_price = 0
        if 'SPX' in self.symbols_to_monitor and self.symbols_to_monitor['SPX'].prices:
            spx_price = self.symbols_to_monitor['SPX'].prices[-1].last_price
        else:
            print("Warning: No SPX price available for strike selection.")
            return None

        strikes = target_expiration["strikes"]
        
        # Track streamer symbols we've already added to avoid duplicates
        added_streamer_symbols = set()
        option_chain_to_return = []
        
        for strike in strikes:
            if order.option_type.upper() == 'P':
                min_strike_price = spx_price - 200
                max_strike_price = spx_price + 20
                symbol = strike['put']
                streamer_symbol = strike['put-streamer-symbol']
            else:
                min_strike_price = spx_price - 20
                max_strike_price = spx_price + 200
                symbol = strike['call']
                streamer_symbol = strike['call-streamer-symbol']

            if min_strike_price <= float(strike['strike-price']) <= max_strike_price:
                # Only add if not already monitoring this symbol
                if streamer_symbol not in added_streamer_symbols and streamer_symbol not in self.symbols_to_monitor:
                    self.symbols_to_monitor[streamer_symbol] = Symbol(symbol=symbol, streamer_symbol=streamer_symbol)
                    added_streamer_symbols.add(streamer_symbol)
                
                option_chain_to_return.append({
                    'symbol': symbol,
                    'streamer-symbol': streamer_symbol,
                    'strike-price': strike['strike-price']
                })
        
        # Subscribe to all new symbols at once
        if added_streamer_symbols:
            self.api_client.subscribe_to_option_quotes(list(added_streamer_symbols), reset=False)
            
        return option_chain_to_return

    def _fetch_accounts(self) -> None:
        """
        Fetches and creates Account objects for Tastytrade accounts.
        
        Populates the accounts dictionary with Account objects for all
        accounts associated with the logged-in user.
        """
        accounts_data = self.api_client.get_accounts()
        if accounts_data:
            for account_data in accounts_data:
                account_number = account_data['account']['account-number']
                account_type = account_data['account']['account-type-name']
                account = Account(account_number=account_number, account_type=account_type)
                self._fetch_positions_for_account(account)
                self.accounts[account_number] = account
        else:
            print(f"Warning: Could not fetch accounts for Tastytrade broker: {self.name}")

    def _fetch_positions_for_account(self, account: Account) -> None:
        """
        Fetches and creates Position objects for a given Tastytrade account.
        
        Args:
            account: The Account object to fetch positions for.
        """
        positions_data = self.api_client.get_positions(account.account_number)
        if positions_data:
            for pos_data in positions_data:
                symbol_info = self.api_client.get_option_info(pos_data['symbol'])
                if not symbol_info or 'data' not in symbol_info or 'streamer-symbol' not in symbol_info['data']:
                    print(f"Warning: Could not fetch streamer symbol for {pos_data['symbol']}")
                    continue
                    
                position = Position(
                    symbol=pos_data['symbol'],
                    streamer_symbol=symbol_info['data']['streamer-symbol'],
                    underlying_symbol=pos_data['underlying-symbol'],
                    instrument_type=pos_data['instrument-type'],
                    quantity=pos_data['quantity'],
                    direction=pos_data['quantity-direction'],
                    cost_effect=pos_data['cost-effect'],
                    average_cost=pos_data['average-open-price']
                )
                account.add_position(position)
        else:
             print(f"Warning: Could not fetch positions for account: {account.account_number} in {self.name} broker")

    def get_option_strikes_by_delta(
            self,
            underlying_symbol: str,
            expiration_date: str,
            delta_min: float,
            delta_max: float
    ) -> Dict[str, Any]:
        """
        Find appropriate option strikes for a strategy based on delta targets.

        Args:
            underlying_symbol: The ticker symbol of the underlying asset.
            expiration_date: Expiration date in 'YYYY-MM-DD' format.
            delta_min: Minimum delta value to consider.
            delta_max: Maximum delta value to consider.

        Returns:
            Dictionary with selected strikes and option chain information.
        """
        # Get option chain
        option_chain_data = self.api_client.get_option_chain(underlying_symbol)
        if not option_chain_data or "data" not in option_chain_data:
            print(f"Failed to retrieve option chain for {underlying_symbol}")
            return {}

        option_chain = option_chain_data["data"]

        # Extract current price
        quote_data = self.symbols_to_monitor.get(underlying_symbol)
        if not quote_data or not quote_data.prices:
            print(f"Failed to get current {underlying_symbol} price")
            return {}

        current_price = quote_data.prices[-1].last_price

        # Find specified expiration in the chain
        target_expiration = None
        for item in option_chain["items"]:
            for exp in item["expirations"]:
                if exp["expiration-date"] == expiration_date:
                    target_expiration = exp
                    break
            if target_expiration:
                break

        if not target_expiration:
            print(f"No expiration found for: {expiration_date}")
            return {}

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

            # Check in monitored symbols
            if put_streamer_symbol in self.symbols_to_monitor:
                put_data = self.symbols_to_monitor[put_streamer_symbol]
                if put_data.greeks and put_data.greeks[-1].delta is not None:
                    # Put deltas are negative, take absolute value for comparison
                    put_delta = abs(put_data.greeks[-1].delta)

            if call_streamer_symbol in self.symbols_to_monitor:
                call_data = self.symbols_to_monitor[call_streamer_symbol]
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
                       delta_min <= s["put_delta"] <= delta_max and
                       s["strike_price"] < current_price]

        # Find call strikes within delta range
        call_strikes = [s for s in all_strikes if s["call_delta"] is not None and
                        delta_min <= s["call_delta"] <= delta_max and
                        s["strike_price"] > current_price]

        if not put_strikes:
            print("No suitable put strikes found in delta range")
            return {}

        if not call_strikes:
            print("No suitable call strikes found in delta range")
            return {}

        # Select short put (highest strike within delta range)
        short_put = put_strikes[-1]
        short_put_strike = short_put["strike_price"]

        # Select short call (lowest strike within delta range)
        short_call = call_strikes[0]
        short_call_strike = short_call["strike_price"]

        return {
            "expiration_date": expiration_date,
            "current_price": current_price,
            "short_put_strike": short_put_strike,
            "short_call_strike": short_call_strike,
            "short_put_delta": short_put["put_delta"],
            "short_call_delta": short_call["call_delta"],
            "all_strikes": all_strikes
        }

    def select_iron_condor_strikes(
            self,
            underlying_symbol: str,
            expiration_date: str,
            delta_min: float,
            delta_max: float,
            put_wing_cost: float,
            call_wing_cost: float,
            target_put_credit: float,
            target_call_credit: float
    ) -> Dict[str, Any]:
        """
        Select appropriate strikes for an iron condor based on delta and credit targets.

        Args:
            underlying_symbol: The ticker symbol of the underlying asset.
            expiration_date: Expiration date in 'YYYY-MM-DD' format.
            delta_min: Minimum delta value for short options.
            delta_max: Maximum delta value for short options.
            put_wing_cost: Approximate cost of the put wing (for width calculation).
            call_wing_cost: Approximate cost of the call wing (for width calculation).
            target_put_credit: Desired credit for put spread.
            target_call_credit: Desired credit for call spread.

        Returns:
            Dictionary with selected strikes for the iron condor.
        """
        # Get initial strikes by delta
        strikes = self.get_option_strikes_by_delta(
            underlying_symbol, expiration_date, delta_min, delta_max)

        if not strikes:
            return {}

        all_strikes = strikes["all_strikes"]
        short_put_strike = strikes["short_put_strike"]
        short_call_strike = strikes["short_call_strike"]

        # Find long put strike (enough spread for desired credit)
        put_spread = int(target_put_credit / put_wing_cost)
        long_put_index = next((i for i, s in enumerate(all_strikes)
                               if s["strike_price"] == short_put_strike), None)

        if long_put_index is not None and long_put_index >= put_spread:
            long_put_strike = all_strikes[long_put_index - put_spread]["strike_price"]
        else:
            print("Cannot find appropriate long put strike")
            return {}

        # Find long call strike (enough spread for desired credit)
        call_spread = int(target_call_credit / call_wing_cost)
        short_call_index = next((i for i, s in enumerate(all_strikes)
                                 if s["strike_price"] == short_call_strike), None)

        if short_call_index is not None and short_call_index + call_spread < len(all_strikes):
            long_call_strike = all_strikes[short_call_index + call_spread]["strike_price"]
        else:
            print("Cannot find appropriate long call strike")
            return {}

        # Return complete iron condor strikes
        return {
            "expiration_date": expiration_date,
            "current_price": strikes["current_price"],
            "long_put_strike": long_put_strike,
            "short_put_strike": short_put_strike,
            "short_call_strike": short_call_strike,
            "long_call_strike": long_call_strike,
            "short_put_delta": strikes["short_put_delta"],
            "short_call_delta": strikes["short_call_delta"],
            "all_strikes": all_strikes
        }

    def calculate_max_iron_condor_contracts(
            self,
            account_number: str,
            strikes: Dict[str, Any],
            max_buying_power: float,
            max_contracts: int,
            total_credit: float
    ) -> int:
        """
        Calculate the maximum number of iron condor contracts based on buying power.

        Args:
            account_number: The account number.
            strikes: Dictionary with strike information.
            max_buying_power: Maximum buying power to use.
            max_contracts: Maximum number of contracts regardless of buying power.
            total_credit: Total credit per iron condor.

        Returns:
            Maximum number of contracts to trade.
        """
        if not account_number or not strikes:
            return 0

        # Get available buying power
        available_bp = self.api_client.get_available_buying_power(account_number)

        if available_bp is None:
            print("Could not retrieve account buying power, using max cap")
            available_bp = max_buying_power
        else:
            # Cap at our maximum
            available_bp = min(available_bp, max_buying_power)

        # Calculate BPR for one iron condor
        bpr_per_contract = self.api_client.calculate_iron_condor_bpr(
            account_number=account_number,
            underlying_symbol="SPX",
            short_put_strike=strikes["short_put_strike"],
            long_put_strike=strikes["long_put_strike"],
            short_call_strike=strikes["short_call_strike"],
            long_call_strike=strikes["long_call_strike"],
            expiration_date=strikes["expiration_date"],
            quantity=1,
            limit_price=total_credit
        )

        if not bpr_per_contract:
            print("Failed to calculate buying power reduction")
            return 0

        # Calculate maximum contracts based on our budget
        max_possible_contracts = int(available_bp / bpr_per_contract)

        # Cap at our desired maximum
        return min(max_possible_contracts, max_contracts)

    def scan_for_iron_condor_positions(
            self,
            account_number: str,
            underlying_symbol: str = "SPX",
            expiration_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan for and identify existing iron condor positions.

        Args:
            account_number: The account number to scan.
            underlying_symbol: The ticker symbol of the underlying asset.
            expiration_date: Optional specific expiration date to look for.
                If None, uses today's date.

        Returns:
            List of dictionaries with iron condor position information.
        """
        if not account_number:
            return []

        # Use today's date as default expiration if not specified
        if expiration_date is None:
            expiration_date = datetime.date.today().strftime("%Y-%m-%d")

        # Get current positions
        positions = self.api_client.get_positions(account_number)
        if not positions:
            return []

        # Keep track of all streamer symbols to add to monitoring
        streamer_symbols_to_monitor = set()

        # Group positions by expiration date
        positions_by_expiration = {}

        for position in positions:
            if position["underlying-symbol"] == underlying_symbol and position["instrument-type"] == "Equity Option":
                # Get option details
                option_info = self.api_client.get_option_info(position["symbol"])
                if not option_info or "data" not in option_info:
                    continue

                option_data = option_info["data"]
                position_expiration = option_data.get("expiration-date")

                # Add to streaming service
                streamer_symbol = option_data.get("streamer-symbol")
                if streamer_symbol:
                    streamer_symbols_to_monitor.add(streamer_symbol)

                # Focus only on specified expiration
                if position_expiration != expiration_date:
                    continue

                if position_expiration not in positions_by_expiration:
                    positions_by_expiration[position_expiration] = []

                positions_by_expiration[position_expiration].append({
                    "symbol": position["symbol"],
                    "quantity": position["quantity"],
                    "direction": position["quantity-direction"],
                    "option_type": option_data.get("option-type"),
                    "strike_price": float(option_data.get("strike-price")),
                    "streamer_symbol": streamer_symbol,
                    "average_open_price": float(position.get("average-open-price", 0))
                })

        # Add all streamer symbols to monitoring if not already monitored
        for streamer_symbol in streamer_symbols_to_monitor:
            if streamer_symbol not in self.symbols_to_monitor:
                self.symbols_to_monitor[streamer_symbol] = Symbol(symbol=None, streamer_symbol=streamer_symbol)

        # List to hold identified iron condors
        iron_condors = []

        # Identify iron condor structures
        for expiration, positions in positions_by_expiration.items():
            # Find puts and calls
            puts = [p for p in positions if p["option_type"] == "P"]
            calls = [p for p in positions if p["option_type"] == "C"]

            # Sort by strike
            puts.sort(key=lambda x: x["strike_price"])
            calls.sort(key=lambda x: x["strike_price"])

            # Look for iron condor structure
            long_puts = [p for p in puts if p["direction"] == "Long"]
            short_puts = [p for p in puts if p["direction"] == "Short"]
            long_calls = [p for p in calls if p["direction"] == "Long"]
            short_calls = [p for p in calls if p["direction"] == "Short"]

            if long_puts and short_puts and long_calls and short_calls:
                # Found a potential iron condor
                print(f"Found existing iron condor position for expiration {expiration}")

                # Get order history to estimate entry time and credits
                orders = self.api_client.get_orders(
                    account_number,
                    status="all",
                    start_date=datetime.date.today() - datetime.timedelta(days=7)
                )

                # Look for orders with the same symbols
                relevant_orders = []
                if orders and "data" in orders and "items" in orders["data"]:
                    for order in orders["data"]["items"]:
                        # Check if this is a related order
                        if "legs" in order:
                            order_symbols = [leg.get("symbol") for leg in order["legs"]]
                            if (short_puts[0]["symbol"] in order_symbols and
                                    long_puts[0]["symbol"] in order_symbols and
                                    short_calls[0]["symbol"] in order_symbols and
                                    long_calls[0]["symbol"] in order_symbols):
                                relevant_orders.append(order)

                # Estimate entry time and credits
                entry_time = datetime.datetime.now() - datetime.timedelta(hours=1)  # Default estimate
                total_credit = 0.0  # Default estimate

                # If we found the original order, use its details
                if relevant_orders:
                    # Use the oldest order as the entry
                    oldest_order = min(relevant_orders, key=lambda o: o.get("placed-time", ""))
                    if "placed-time" in oldest_order:
                        try:
                            entry_time = datetime.datetime.fromisoformat(
                                oldest_order["placed-time"].replace("Z", "+00:00"))
                        except ValueError:
                            pass  # Fall back to estimate

                    # Try to extract actual credits
                    if "price" in oldest_order:
                        total_credit = float(oldest_order["price"])

                # Calculate number of contracts (minimum quantity across all legs)
                num_contracts = min(
                    abs(long_puts[0]["quantity"]),
                    abs(short_puts[0]["quantity"]),
                    abs(short_calls[0]["quantity"]),
                    abs(long_calls[0]["quantity"])
                )

                # Create a iron condor structure for monitoring
                iron_condor = {
                    "order_id": "existing",
                    "num_contracts": num_contracts,
                    "expiration_date": expiration,
                    "entry_time": entry_time,
                    "total_credit": total_credit * num_contracts,
                    "strikes": {
                        "long_put": long_puts[0]["strike_price"],
                        "short_put": short_puts[0]["strike_price"],
                        "short_call": short_calls[0]["strike_price"],
                        "long_call": long_calls[0]["strike_price"]
                    },
                    "symbols": {
                        "long_put": long_puts[0]["symbol"],
                        "short_put": short_puts[0]["symbol"],
                        "short_call": short_calls[0]["symbol"],
                        "long_call": long_calls[0]["symbol"]
                    },
                    "streamer_symbols": {
                        "long_put": long_puts[0]["streamer_symbol"],
                        "short_put": short_puts[0]["streamer_symbol"],
                        "short_call": short_calls[0]["streamer_symbol"],
                        "long_call": long_calls[0]["streamer_symbol"]
                    }
                }

                iron_condors.append(iron_condor)

        return iron_condors

    def execute_iron_condor(
            self,
            account_number: str,
            underlying_symbol: str,
            expiration_date: str,
            strikes: Dict[str, Any],
            num_contracts: int,
            credit_price: float
    ) -> Dict[str, Any]:
        """
        Execute an iron condor trade.

        Args:
            account_number: The account number.
            underlying_symbol: The ticker symbol of the underlying asset.
            expiration_date: Expiration date in 'YYYY-MM-DD' format.
            strikes: Dictionary with strike information.
            num_contracts: Number of contracts to trade.
            credit_price: Credit price to receive for the iron condor.

        Returns:
            Dictionary with trade execution information.
        """
        if not account_number or num_contracts <= 0:
            return {}

        # Prepare option symbols
        short_put = self.api_client._prepare_option_symbol(
            underlying_symbol, expiration_date, strikes["short_put_strike"], "P")
        long_put = self.api_client._prepare_option_symbol(
            underlying_symbol, expiration_date, strikes["long_put_strike"], "P")
        short_call = self.api_client._prepare_option_symbol(
            underlying_symbol, expiration_date, strikes["short_call_strike"], "C")
        long_call = self.api_client._prepare_option_symbol(
            underlying_symbol, expiration_date, strikes["long_call_strike"], "C")

        # Create legs for the order
        legs = [
            {"symbol": short_put, "quantity": num_contracts, "action": "Sell to Open",
             "instrument_type": "Equity Option"},
            {"symbol": long_put, "quantity": num_contracts, "action": "Buy to Open",
             "instrument_type": "Equity Option"},
            {"symbol": short_call, "quantity": num_contracts, "action": "Sell to Open",
             "instrument_type": "Equity Option"},
            {"symbol": long_call, "quantity": num_contracts, "action": "Buy to Open",
             "instrument_type": "Equity Option"}
        ]

        # Do a dry run to confirm everything looks good
        dry_run_result = self.api_client.dry_run_option_order(
            account_number, underlying_symbol, legs, order_type="Limit", limit_price=credit_price)

        if not dry_run_result:
            print("Dry run failed, cancelling trade")
            return {}

        if "errors" in dry_run_result and dry_run_result["errors"]:
            print(f"Dry run returned errors: {dry_run_result['errors']}")
            return {}

        # Submit the actual order
        response = self.api_client.create_iron_condor_order(
            account_number=account_number,
            short_put_symbol=short_put,
            long_put_symbol=long_put,
            short_call_symbol=short_call,
            long_call_symbol=long_call,
            quantity=num_contracts,
            credit_price=credit_price
        )

        if not response or "data" not in response or "order" not in response["data"]:
            print("Failed to submit iron condor order")
            return {}

        order = response["data"]["order"]
        order_id = order["id"]

        # Build trade info
        trade_info = {
            "order_id": order_id,
            "num_contracts": num_contracts,
            "expiration_date": expiration_date,
            "entry_time": datetime.datetime.now(),
            "total_credit": credit_price * num_contracts,
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
            }
        }

        return trade_info

    def check_option_exit_condition(
            self,
            symbol: str,
            original_credit: float,
            num_contracts: int,
            exit_threshold: float
    ) -> Tuple[bool, float]:
        """
        Check if an option position meets exit conditions based on cost to close.

        Args:
            symbol: The option symbol to check.
            original_credit: Original credit received per contract.
            num_contracts: Number of contracts.
            exit_threshold: Threshold as percentage of original credit.

        Returns:
            Tuple of (should_exit, cost_to_close).
        """
        option_info = self.api_client.get_option_info(symbol)

        if not option_info or "data" not in option_info:
            return False, 0.0

        streamer_symbol = option_info["data"]["streamer-symbol"]

        # Check if we have price data
        if streamer_symbol not in self.symbols_to_monitor:
            return False, 0.0

        symbol_data = self.symbols_to_monitor[streamer_symbol]
        if not symbol_data.prices:
            return False, 0.0

        current_price = symbol_data.prices[-1].ask_price
        cost_to_close = current_price * num_contracts

        # Check if cost to close exceeds threshold
        if cost_to_close >= original_credit * exit_threshold * num_contracts:
            return True, cost_to_close

        return False, cost_to_close

    def close_option_position(
            self,
            account_number: str,
            symbol: str,
            quantity: int,
            action: str = "Buy to Close",
            order_type: str = "Market"
    ) -> Optional[str]:
        """
        Close an option position with a market order.

        Args:
            account_number: The account number.
            symbol: The option symbol to close.
            quantity: Number of contracts.
            action: Order action (usually 'Buy to Close' for short options).
            order_type: Order type (usually 'Market' for closing).

        Returns:
            Order ID if successful, None otherwise.
        """
        response = self.api_client.create_market_order(
            account_number=account_number,
            symbol=symbol,
            quantity=quantity,
            action=action,
            instrument_type="Equity Option"
        )

        if response and "data" in response and "order" in response["data"]:
            return response["data"]["order"]["id"]

        return None
