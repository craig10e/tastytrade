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
