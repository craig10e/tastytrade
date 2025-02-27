import os
from dotenv import load_dotenv
import requests
import json
import datetime
from typing import Dict, List, Any, Optional, Callable, Union, Set, Tuple
from urllib.parse import urlencode
import websocket
import threading
import time


class TastytradeAPI:
    """
    A Python library for interacting with the Tastytrade API.
    
    This class provides methods to authenticate with the Tastytrade API,
    retrieve account information, place and monitor orders, and stream
    real-time market data.
    
    Attributes:
        BASE_URL (str): Base URL for the Tastytrade API.
        STREAMER_URL (str): WebSocket URL for streaming data.
        username (str): Tastytrade account username.
        password (str): Tastytrade account password.
        session_token (Optional[str]): Current session authentication token.
        authorization_header (Optional[Dict[str, str]]): HTTP header for authentication.
        stream_token (Optional[str]): Token for market data streaming.
        dxlink_url (Optional[str]): URL for DxLink streaming connection.
        quote_data (Dict[str, Dict]): Storage for the latest quote data by symbol.
        greeks_data (Dict[str, Dict]): Storage for the latest Greeks data by symbol.
    """

    # Load environment variables from .env file
    load_dotenv()
    BASE_URL: str = os.getenv("TASTY_BASE_URL") or "https://api.cert.tastyworks.com"  # Default to sandbox
    STREAMER_URL: str = os.getenv("TASTY_STREAMER_URL") or "wss://streamer.cert.tastyworks.com"

    def __init__(
        self, 
        username: Optional[str] = None, 
        password: Optional[str] = None, 
        quote_handler: Optional[Callable[[str, Dict[str, Any]], None]] = None, 
        greeks_handler: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> None:
        """
        Initialize the Tastytrade API client.

        Args:
            username: Tastytrade username. If None, loads from TASTY_USERNAME env var.
            password: Tastytrade password. If None, loads from TASTY_PASSWORD env var.
            quote_handler: Optional callback function for processing quote updates.
            greeks_handler: Optional callback function for processing Greeks updates.

        Raises:
            ValueError: If username or password are not provided via parameters or env vars.
        """
        self.username = username or os.getenv("TASTY_USERNAME")  # Get from env if not passed directly.
        self.password = password or os.getenv("TASTY_PASSWORD")  # Get from env if not passed directly.

        if not self.username or not self.password:
            raise ValueError(
                "Username and password must be provided either directly or via environment variables (TASTY_USERNAME, TASTY_PASSWORD).")

        self.session_token: Optional[str] = None
        self.authorization_header: Optional[Dict[str, str]] = None
        self._session = threading.local()  # Thread-local session object
        self.login()
        self.stream_token: Optional[str] = None
        self.dxlink_url: Optional[str] = None

        # WebSocket Variables
        self.ws_market_data: Optional[websocket.WebSocketApp] = None
        self.ws_account_data: Optional[websocket.WebSocketApp] = None
        self.ws_market_thread: Optional[threading.Thread] = None
        self.ws_account_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None

        # DxLink Variables
        self.dxlink_channel_counter: int = 0
        self.quote_data: Dict[str, Dict[str, Optional[float]]] = {}
        self.greeks_data: Dict[str, Dict[str, Optional[float]]] = {}
        self.setup_channel: Optional[int] = None

        self.quote_handlers: List[Callable[[str, Dict[str, Any]], None]] = [quote_handler] if quote_handler else []
        self.greeks_handlers: List[Callable[[str, Dict[str, Any]], None]] = [greeks_handler] if greeks_handler else []

        self.equities_to_stream: Optional[List[str]] = None
        self.options_to_stream: Optional[List[str]] = None

    def add_quote_handler(self, quote_handler: Callable[[str, Dict[str, Any]], None]) -> None:
        """
        Add a callback function to handle quote data updates.
        
        Args:
            quote_handler: A function that takes (symbol, quote_data) as parameters.
        """
        self.quote_handlers.append(quote_handler)

    def add_greeks_handler(self, greeks_handler: Callable[[str, Dict[str, Any]], None]) -> None:
        """
        Add a callback function to handle Greeks data updates.
        
        Args:
            greeks_handler: A function that takes (symbol, greeks_data) as parameters.
        """
        self.greeks_handlers.append(greeks_handler)

    def get_session(self) -> requests.Session:
        """
        Get a thread-safe session object.
        
        Returns:
            A requests.Session object specific to the current thread.
        """
        if not hasattr(self._session, "session"):
            self._session.session = requests.Session()
        return self._session.session

    def _request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None, 
        data: Optional[Dict[str, Any]] = None, 
        headers: Optional[Dict[str, str]] = None, 
        is_retry: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Internal method to make HTTP requests to the Tastytrade API.

        Args:
            method: HTTP method (GET, POST, etc.).
            endpoint: API endpoint path.
            params: Optional query parameters.
            data: Optional request body data.
            headers: Optional HTTP headers.
            is_retry: Whether this is a retry attempt.

        Returns:
            API response data as a dictionary or None on failure.
        """
        url = self.BASE_URL + endpoint
        session = self.get_session()

        if headers is None:
            headers = {}

        headers['User-Agent'] = 'tastytrade-python-client/0.1'
        headers['Accept'] = 'application/json'

        if self.authorization_header:
            headers.update(self.authorization_header)

        if data:
            data = self._dasherize_keys(data)
            headers['Content-Type'] = 'application/json'

        try:
            response = session.request(method, url, params=params, json=data, headers=headers,
                                       timeout=10)  # Added timeout
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401 and not is_retry:
                if "Unauthorized" in str(e):
                    print("401 Unauthorized.")
                    return None
                else:
                    print(f"HTTP Error: {e}")
                    return None
            elif e.response.status_code == 400:
                print(f"Bad request Error: {e}")
                return None
            elif e.response.status_code == 403:
                print(f"Forbidden Error: {e}")
                return None
            elif e.response.status_code == 404:
                print(f"Not Found Error: {e}")
                return None
            elif e.response.status_code == 422:
                print(f"Unprocessable Content Error: {e}")
                return None
            elif e.response.status_code == 429:
                print(f"Too Many Requests Error: {e}")
                return None
            elif e.response.status_code == 500:
                print(f"Internal Server Error: {e}")
                return None
            else:
                print(f"HTTP Error: {e}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Request Exception: {e}")
            return None

    def _dasherize_keys(self, data: Any) -> Any:
        """
        Recursively convert camelCase or snake_case keys to dasherized-keys.

        Args:
            data: The data to transform (dict, list, or primitive type).
            
        Returns:
            Transformed data with dasherized keys.
        """
        if isinstance(data, dict):
            return {
                k.replace("_", "-"): self._dasherize_keys(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._dasherize_keys(item) for item in data]
        else:
            return data

    def login(self) -> bool:
        """
        Login using remember token or username/password.
        
        First attempts to use a stored remember token, then falls back to username/password.
        If login is successful with username/password, saves the new remember token.
        
        Returns:
            True if login was successful, False otherwise.
        """
        load_dotenv(dotenv_path=".env-session")
        remember_token = os.getenv("TASTY_REMEMBER_TOKEN")

        if remember_token:
            print("Attempting to log in with remember token...")
            endpoint = "/sessions"
            data = {
                "login": self.username,
                "remember-token": remember_token,
                "remember-me": True
            }
            response_data = self._request("POST", endpoint, data=data)

            if self._is_login_successful(response_data):
                print("Login with remember token successful.")
                return True

        print("Attempting to log in with username/password...")
        endpoint = "/sessions"
        data = {
            "login": self.username,
            "password": self.password,
            "remember-me": True
        }
        response_data = self._request("POST", endpoint, data=data)

        if self._is_login_successful(response_data):
            print("Login with username/password successful.")
            if "remember-token" in response_data["data"]:
                remember_token = response_data["data"]["remember-token"]
                with open(".env-session", "w") as f:
                    f.write(f"TASTY_REMEMBER_TOKEN={remember_token}\n")
                print("Remember token saved to .env-session")
            return True
        else:
            print("Login failed.")
            return False

    def _is_login_successful(self, response_data: Optional[Dict[str, Any]]) -> bool:
        """
        Helper function to check if login response is successful.
        
        Args:
            response_data: The API response from a login attempt.
            
        Returns:
            True if login was successful, False otherwise.
        """
        if response_data and "data" in response_data and "session-token" in response_data["data"]:
            self.session_token = response_data["data"]["session-token"]
            self.authorization_header = {"Authorization": self.session_token}
            return True
        else:
            self.session_token = None
            self.authorization_header = None
            return False

    def get_accounts(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get accounts for the logged-in user.
        
        Returns:
            A list of account data dictionaries or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        customer_data = self._request("GET", "/customers/me")
        if not customer_data or "data" not in customer_data or "id" not in customer_data["data"]:
            print("Failed to retrieve customer ID.")
            return None
        customer_id = customer_data["data"]["id"]

        endpoint = f"/customers/{customer_id}/accounts"
        response_data = self._request("GET", endpoint)
        return response_data["data"]["items"] if response_data and "data" in response_data and "items" in response_data[
            "data"] else None

    def get_account_numbers(self) -> List[str]:
        """
        Helper to get all account numbers for the logged-in user.
        
        Returns:
            A list of account numbers as strings. Empty list if no accounts found.
        """
        accounts = self.get_accounts()
        return [account['account']['account-number'] for account in accounts] if accounts else []

    def get_positions(self, account_number: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get positions for a specific account.
        
        Args:
            account_number: The account number to retrieve positions for.
            
        Returns:
            A list of position data dictionaries or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None
        endpoint = f"/accounts/{account_number}/positions"
        response_data = self._request("GET", endpoint)
        return response_data["data"]["items"] if response_data and "data" in response_data and "items" in response_data[
            "data"] else None

    def _prepare_option_symbol(
        self, 
        underlying_symbol: str, 
        expiration_date: Union[datetime.date, str], 
        strike_price: float, 
        option_type: str
    ) -> str:
        """
        Construct OCC option symbol.
        
        Args:
            underlying_symbol: The ticker symbol of the underlying asset.
            expiration_date: The option expiration date (datetime.date or string 'YYYY-MM-DD').
            strike_price: The option strike price.
            option_type: 'C' for call or 'P' for put.
            
        Returns:
            The OCC-formatted option symbol string.
            
        Raises:
            ValueError: If expiration_date string format is invalid.
        """
        root = underlying_symbol.ljust(6)
        
        if isinstance(expiration_date, str):
            try:
                expiration_date = datetime.datetime.strptime(expiration_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Invalid expiration_date format. Use YYYY-MM-DD.")
                
        exp_str = expiration_date.strftime("%y%m%d")
        option_type_str = option_type.upper()
        strike_str = f"{int(strike_price * 1000):08}"
        return f"{root}{exp_str}{option_type_str}{strike_str}"

    def get_order_status(self, account_number: str, order_id: str) -> Optional[str]:
        """
        Get the current status of an order.
        
        Args:
            account_number: The account number.
            order_id: The ID of the order to check.
            
        Returns:
            The order status string or None if status retrieval fails.
        """
        order_status_response = self._request("GET", f"/accounts/{account_number}/orders/{order_id}")
        if order_status_response and order_status_response.get("data") and order_status_response["data"].get("order"):
            order_status = order_status_response["data"]["order"]["status"]
            print(f"Order status: {order_status}")
            if order_status == "Filled":
                print(f"Order filled.")
            elif order_status in ("Rejected", "Cancelled", "Expired"):  # Consider more terminal statuses.
                print(f"Order terminated with status: {order_status}.")
            return order_status
        else:
            print("Error retrieving order status.")  # Error getting status.
        return None

    def replace_option_order(
        self, 
        account_number: str, 
        order_id: str, 
        limit_price: float, 
        time_in_force: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Replace an existing option order with new parameters.
        
        Uses PATCH /accounts/{account_number}/orders/{id} endpoint.
        
        Args:
            account_number: The account number.
            order_id: The ID of the order to replace.
            limit_price: The new limit price for the order.
            time_in_force: New time-in-force. If None, existing value is kept.

        Returns:
            The API response for the order replacement, or None on failure.
            
        Raises:
            ValueError: If order_id or limit_price is not provided.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        if not order_id:
            raise ValueError("order_id must be provided to replace an order.")
        if limit_price is None:  # Limit price is mandatory for this function.
            raise ValueError("Price must be specified for replace_option_order.")

        endpoint = f"/accounts/{account_number}/orders/{order_id}"
        replace_data = {
            "order-type": "Limit",
            "price": limit_price,
        }
        if time_in_force:
            replace_data["time-in-force"] = time_in_force

        response = self._request("PATCH", endpoint, data=replace_data)
        return response

    def create_option_order(
        self, 
        account_number: str, 
        underlying_symbol: str, 
        expiration_date: Union[datetime.date, str], 
        strike_price: float, 
        option_type: str, 
        action: str,
        quantity: int, 
        order_type: str = "Limit", 
        limit_price: Optional[float] = None, 
        time_in_force: str = "Day"
    ) -> Optional[Dict[str, Any]]:
        """
        Create an option order.
        
        Args:
            account_number: The account number.
            underlying_symbol: The ticker symbol of the underlying asset.
            expiration_date: The option expiration date.
            strike_price: The option strike price.
            option_type: 'C' for call or 'P' for put.
            action: Order action ('Buy to Open', 'Sell to Open', 'Buy to Close', 'Sell to Close').
            quantity: Number of contracts.
            order_type: 'Limit' or 'Market'.
            limit_price: Price for limit orders (required if order_type is 'Limit').
            time_in_force: 'Day', 'GTC', or 'GTD'.
            
        Returns:
            The API response for the order creation, or None on failure.
            
        Raises:
            ValueError: If required parameters are missing or invalid.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        if order_type == "Limit" and limit_price is None:
            raise ValueError("Price must be specified for Limit orders.")
        if order_type not in ("Limit", "Market"):
            raise ValueError("Order type must be Limit or Market")
        if time_in_force not in ("Day", "GTC", "GTD"):
            raise ValueError("time_in_force must be Day, GTC, or GTD")

        if isinstance(expiration_date, str):
            try:
                expiration_date = datetime.datetime.strptime(expiration_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Invalid expiration_date format. Use YYYY-MM-DD.")

        option_symbol = self._prepare_option_symbol(underlying_symbol, expiration_date, strike_price, option_type)

        endpoint = f"/accounts/{account_number}/orders"
        order_data = {
            "source": "user",
            "order-type": order_type,
            "time-in-force": time_in_force,
            "legs": [
                {
                    "instrument-type": "Equity Option",
                    "symbol": option_symbol,
                    "quantity": quantity,
                    "action": action,
                }
            ],
        }
        if order_type == "Limit":
            order_data["price"] = limit_price
            order_data["price-effect"] = "Debit" if action.startswith("Buy") else "Credit"

        return self._request("POST", endpoint, data=order_data)

    def get_option_quote_stream_token(self) -> Optional[Dict[str, Any]]:
        """
        Get quote stream token.
        
        Returns:
            Token data or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        endpoint = "/api-quote-tokens"
        response_data = self._request("GET", endpoint)
        return response_data["data"] if response_data else None

    def get_stream_token_and_url(self) -> bool:
        """
        Get and store stream token and URL.
        
        Returns:
            True if successful, False otherwise.
        """
        if not self.session_token:
            print("Not logged in.")
            return False

        endpoint = "/api-quote-tokens"
        response_data = self._request("GET", endpoint)
        if response_data and "data" in response_data:
            self.stream_token = response_data["data"]["token"]
            self.dxlink_url = response_data["data"]["dxlink-url"]
            print(f"Stream token acquired: {self.stream_token}")
            return True
        else:
            print("Failed to acquire stream token.")
            self.stream_token = None
            self.dxlink_url = None
            return False

    def get_equity_info(self, symbol: Union[str, List[str]]) -> Optional[Dict[str, Any]]:
        """
        Get equity information by symbol.
        
        Args:
            symbol: A single equity symbol or a list of symbols.
            
        Returns:
            Equity information or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None
        endpoint = f"/instruments/equities/{symbol}" if isinstance(symbol,
                                                                   str) else f"/instruments/equities?{urlencode([('symbol[]', s) for s in symbol], doseq=True)}"
        return self._request("GET", endpoint)

    def get_option_info(self, symbol: Union[str, List[str]]) -> Optional[Dict[str, Any]]:
        """
        Get option information by symbol.
        
        Args:
            symbol: A single option symbol or a list of symbols.
            
        Returns:
            Option information or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None
        endpoint = f"/instruments/equity-options/{symbol}" if isinstance(symbol, str) else f"/instruments/equity-options?{urlencode([('symbol[]', s) for s in symbol], doseq=True)}"
        return self._request("GET", endpoint)

    def get_option_chain(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get option chain for a symbol.
        
        Args:
            symbol: The underlying symbol to get option chain for.
            
        Returns:
            Option chain data or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None
        endpoint = f"/option-chains/{symbol}/nested"
        return self._request("GET", endpoint)

    def _ws_market_data_on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """
        Handles incoming market data messages, including authorization, setup, and quote data.
        
        Args:
            ws: The WebSocket connection.
            message: The received message string.
        """
        try:
            data = json.loads(message)
            print("Market Data Received:", data)  # Keep for debugging

            # Handle DxLink responses (Authorization and Setup)
            if data.get("type") == "AUTH_STATE" and data.get("state") == "UNAUTHORIZED":
                auth_message = {
                    "type": "AUTH",
                    "channel": 0,
                    "token": self.stream_token,
                }
                ws.send(json.dumps(auth_message))

            elif data.get("type") == "AUTH_STATE" and data.get("state") == "AUTHORIZED":
                print("DxLink Authorization Successful")
                self._dxlink_send(ws, "CHANNEL_REQUEST", data={"service": "FEED", "parameters": {"contract": "AUTO"}})

            elif data.get("type") == "CHANNEL_OPENED":
                self.setup_channel = data.get("channel")
                print(f"Channel opened. Channel ID: {self.setup_channel}")
                self._dxlink_send(ws, "FEED_SETUP", data={
                    "acceptAggregationPeriod": 0.1,
                    "acceptDataFormat": "COMPACT",
                    "acceptEventFields": {
                        "Quote": ["eventType", "eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize"],
                        "Greeks": ["eventType", "eventSymbol", "volatility", "delta", "gamma", "theta", "rho", "vega"]
                    }
                }, channel=self.setup_channel)

            elif data.get("type") == "FEED_CONFIG":
                print("Received FEED_CONFIG - Setup Complete! - Calling on_feed_config_callback")
                if self.equities_to_stream:
                    self.subscribe_to_equity_quotes(self.equities_to_stream)
                if self.options_to_stream:
                    self.subscribe_to_option_quotes(self.options_to_stream, reset=False)

            # Handle Quote Data and store in quote_data dictionary.
            elif data.get("type") == "FEED_DATA":
              if data.get('channel') == self.setup_channel: #Only handle data on the setup channel.
                for item in data['data']: #Iterate because it's a list.
                  if isinstance(item, list) and len(item) > 1: #Check it's a list and has elements.
                    if item[0] in ['Quote', 'Greeks']:
                        # item structure ['Quote', 'AAPL', 170.5, 170.55, 100, 200,
                        #                 'Quote', TSLA', 360.01, 360.09, 26.0, 356.0,
                        #                 'Quote', 'SPX', 6121.88, 6125.48, 'NaN', 'NaN']]
                        #                 'Quote', symbol, bid, ask, bidSize, askSize,
                        for i in range(len(item)):
                            if item[i] == 'Quote':
                                try:
                                    event_symbol = item[i + 1]
                                    bid_price = item[i + 2]
                                    ask_price = item[i + 3]
                                    bid_size = item[i + 4]
                                    ask_size = item[i + 5]

                                    quote_data = {
                                        "bid_price": float(bid_price) if bid_price != "NaN" else None,
                                        "ask_price": float(ask_price) if ask_price != "NaN" else None,
                                        "bid_size": int(bid_size) if bid_size != "NaN" and bid_size is not None else None,
                                        "ask_size": int(ask_size) if ask_size != "NaN" and ask_size is not None else None,
                                        "last_price": float(ask_price) if ask_price != "NaN" else float(bid_price) if bid_price != "NaN" else None
                                    }
                                    self.quote_data[event_symbol] = quote_data
                                    for quote_handler in self.quote_handlers:
                                        quote_handler(event_symbol, quote_data)

                                except (ValueError, IndexError) as e:
                                    print(f"Error parsing Quote data: {e}, data: {item}")
                                    continue #Skip to next
                            elif item[i] == 'Greeks':
                                # ['Greeks', '.SPX250321C200', 1.275330638042824, 0.999033865052559, 1.812352621491491e-24,
                                #            symbol, volatility, delta, gamma, theta, rho, vega
                                # 0.1725584556698835, 0.1624037745129343, 7.11055169723468e-20]
                                print('Greeks', item)
                                try:
                                    event_symbol = item[i + 1]
                                    volatility = item[i + 2]
                                    delta = item[i + 3]
                                    gamma = item[i + 4]
                                    theta = item[i + 5]
                                    rho = item[i + 6]
                                    vega = item[i + 7]

                                    greeks_data = {
                                        "volatility": float(volatility) if volatility != 'NaN' else None,
                                        "delta": float(delta) if delta != 'NaN' else None,
                                        "gamma": float(gamma) if gamma != 'NaN' else None,
                                        "theta": float(theta) if theta != 'NaN' else None,
                                        "rho": float(rho) if rho != 'NaN' else None,
                                        "vega": float(vega) if vega != 'NaN' else None,
                                    }
                                    self.greeks_data[event_symbol] = greeks_data
                                    for greeks_handler in self.greeks_handlers:
                                        greeks_handler(event_symbol, greeks_data)
                                except (ValueError, IndexError) as e:
                                    print(f"Error parsing Quote data: {e}, data: {item}")
                                    continue  # Skip to next

            elif data.get("type") == "KEEPALIVE":
              #Could handle keepalives from server, but not required.
              pass

        except json.JSONDecodeError:
            print(f"Invalid JSON received: {message}")

    def _ws_market_data_on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """
        Handle market data websocket errors.
        
        Args:
            ws: The WebSocket connection.
            error: The error that occurred.
        """
        print(f"Market Data WebSocket Error: {error}")

    def _ws_market_data_on_close(self, ws: websocket.WebSocketApp, close_status_code: Optional[int], close_msg: Optional[str]) -> None:
        """
        Handle market data websocket close.
        
        Args:
            ws: The WebSocket connection.
            close_status_code: The close status code.
            close_msg: The close message.
        """
        print("Market Data WebSocket Closed:", close_status_code, close_msg)
        self.ws_market_data = None

    def _ws_market_data_on_open(self, ws: websocket.WebSocketApp) -> None:
        """
        Handle market data websocket open - setup and auth.
        
        Args:
            ws: The WebSocket connection.
        """
        print("Market Data WebSocket Opened")
        setup_message = {
            "type": "SETUP",
            "channel": 0,
            "version": "0.1-DXF-JS/0.3.0",
            "keepaliveTimeout": 60,
            "acceptKeepaliveTimeout": 60,
        }
        ws.send(json.dumps(setup_message))

    def _dxlink_send(self, ws: websocket.WebSocketApp, message_type: str, data: Optional[Dict[str, Any]] = None, channel: Optional[int] = None) -> None:
        """
        Send message to DxLink, incrementing channel.
        
        Args:
            ws: The WebSocket connection.
            message_type: The type of message to send.
            data: Additional data to include in the message.
            channel: The channel to use (if None, uses incremented channel counter).
        """
        self.dxlink_channel_counter += 1
        message = {"type": message_type, "channel": self.dxlink_channel_counter if channel is None else channel}
        if data:
            message.update(data)
        ws.send(json.dumps(message))

    def _ws_market_data_thread(self) -> None:
        """
        Thread for market data websocket connection.
        
        Continuously attempts to maintain a connection to the market data stream.
        Reconnects on failure with a delay.
        """
        while True:
            if not self.get_stream_token_and_url():
                print("Failed to get stream token. Retrying in 60 seconds...")
                time.sleep(60)
                continue

            self.ws_market_data = websocket.WebSocketApp(
                self.dxlink_url,
                on_open=self._ws_market_data_on_open,
                on_message=self._ws_market_data_on_message,
                on_error=self._ws_market_data_on_error,
                on_close=self._ws_market_data_on_close,
            )
            self.ws_market_data.run_forever()
            print("Market Data Websocket Closed. Attempting to reconnect in 10 seconds...")
            time.sleep(10)

    def connect_market_data_stream(self, equities_to_stream: Optional[List[str]] = None, options_to_stream: Optional[List[str]] = None) -> None:
        """
        Start market data websocket stream.
        
        Args:
            equities_to_stream: Optional list of equity symbols to stream.
            options_to_stream: Optional list of option symbols to stream.
        """
        if self.ws_market_thread is None or not self.ws_market_thread.is_alive():
            self.ws_market_thread = threading.Thread(target=self._ws_market_data_thread, daemon=True)
            self.ws_market_thread.start()
            print("Market data stream thread started.")
        else:
            print("Market data stream thread already running.")
        self.equities_to_stream = equities_to_stream
        self.options_to_stream = options_to_stream

    def subscribe_to_option_quotes(self, symbols: List[str], reset: bool = True) -> None:
        """
        Subscribes to quote events for the given option symbols.
        
        Args:
            symbols: List of option symbols to subscribe to.
            reset: Whether to reset existing subscriptions.
        """
        if not self.ws_market_data:
            print("Market data WebSocket not connected.")
            return

        # Add FEED_SUBSCRIPTION
        subscription_message = {
            "reset": reset,
            "add": [{"type": "Quote", "symbol": symbol} for symbol in symbols] +
                   [{"type": "Greeks", "symbol": symbol} for symbol in symbols]
        }
        print(f"Sending FEED_SUBSCRIPTION: {subscription_message}")
        self._dxlink_send(self.ws_market_data, "FEED_SUBSCRIPTION", data=subscription_message,
                          channel=self.setup_channel)

    def subscribe_to_equity_quotes(self, symbols: List[str], reset: bool = True) -> None:
        """
        Subscribes to quote events for the given equity symbols.
        
        Args:
            symbols: List of equity symbols to subscribe to.
            reset: Whether to reset existing subscriptions.
        """
        if not self.ws_market_data:
            print("Market data WebSocket not connected.")
            return

        # Add FEED_SUBSCRIPTION
        subscription_message = {
            "reset": reset,
            "add": [
                {"type": "Quote", "symbol": symbol} for symbol in symbols
            ]
        }
        print(f"Sending FEED_SUBSCRIPTION: {subscription_message}")
        self._dxlink_send(self.ws_market_data, "FEED_SUBSCRIPTION", data=subscription_message,
                          channel=self.setup_channel)

    def get_streamer_symbols(self, symbols: List[str], instrument_type: str) -> Optional[List[str]]:
        """
        Get streamer symbols for a list of symbols.
        
        Args:
            symbols: List of symbols to get streamer symbols for.
            instrument_type: Type of instrument ('Equity Option' or 'Equity').
            
        Returns:
            List of streamer symbols or None if retrieval fails.
        """
        streamer_symbols = []
        if instrument_type == "Equity Option":
            options_data = self._request("GET",
                                         f"/instruments/equity-options?{urlencode([('symbol[]', s) for s in symbols], doseq=True)}")
            if options_data and "data" in options_data and "items" in options_data["data"]:
                for option in options_data["data"]["items"]:
                    streamer_symbols.append(option["streamer-symbol"])
        elif instrument_type == "Equity":
            equities_data = self.get_equity_info(symbols)
            if equities_data and "data" in equities_data and "items" in equities_data["data"]:
                for equity in equities_data["data"]["items"]:
                    streamer_symbols.append(equity["streamer-symbol"])
        else:
            print("Instrument type not yet implemented")
            return None
        return streamer_symbols

    def _ws_account_data_on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """
        Handle account data websocket messages.
        
        Args:
            ws: The WebSocket connection.
            message: The received message string.
        """
        try:
            data = json.loads(message)
            print("Account Data Received:", data)  # For debug
        except json.JSONDecodeError:
            print(f"Invalid JSON received: {message}")

    def _ws_account_data_on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """
        Handle account data websocket errors.
        
        Args:
            ws: The WebSocket connection.
            error: The error that occurred.
        """
        print(f"Account Data WebSocket Error: {error}")

    def _ws_account_data_on_close(self, ws: websocket.WebSocketApp, close_status_code: Optional[int], close_msg: Optional[str]) -> None:
        """
        Handle account data websocket close.
        
        Args:
            ws: The WebSocket connection.
            close_status_code: The close status code.
            close_msg: The close message.
        """
        print("Account Data WebSocket Closed:", close_status_code, close_msg)
        self.ws_account_data = None

    def _ws_account_data_on_open(self, ws: websocket.WebSocketApp) -> None:
        """
        Handle account data websocket open - connect.
        
        Args:
            ws: The WebSocket connection.
        """
        print("Account Data WebSocket Opened")
        account_numbers = self.get_account_numbers()
        if account_numbers:
            connect_message = {
                "action": "connect",
                "value": account_numbers,
                "auth-token": self.session_token,
            }
            print(connect_message)
            ws.send(json.dumps(connect_message))
        else:
            print("No accounts for event stream subscription")

    def _ws_account_data_thread(self) -> None:
        """
        Thread for account data websocket connection.
        
        Continuously attempts to maintain a connection to the account data stream.
        Reconnects on failure with a delay.
        """
        while True:
            if not self.session_token:
                print("Not logged in, cannot connect to account data stream. Retrying in 60 seconds.")
                time.sleep(60)
                continue
            self.ws_account_data = websocket.WebSocketApp(
                url=self.STREAMER_URL,
                on_open=self._ws_account_data_on_open,
                on_message=self._ws_account_data_on_message,
                on_error=self._ws_account_data_on_error,
                on_close=self._ws_account_data_on_close,
            )
            self.ws_account_data.run_forever()
            print("Account Data WebSocket Closed. Attempting to reconnect in 10 seconds")
            time.sleep(10)

    def connect_account_data_stream(self) -> None:
        """
        Start account data websocket stream.
        
        Initiates a thread to maintain a connection to the account data stream.
        """
        if self.ws_account_thread is None or not self.ws_account_thread.is_alive():
            self.ws_account_thread = threading.Thread(target=self._ws_account_data_thread, daemon=True)
            self.ws_account_thread.start()
            print("Account data stream thread started.")
        else:
            print("Account data stream thread already running.")

    def _send_heartbeat(self) -> None:
        """
        Sends heartbeat messages to both websockets if they are connected.
        
        Runs in a continuous loop, sending heartbeat messages every 30 seconds.
        """
        while True:
            time.sleep(30)  # 30 seconds, per API docs.

            if self.ws_market_data and self.ws_market_data.sock and self.ws_market_data.sock.connected:
                self._dxlink_send(self.ws_market_data, "KEEPALIVE", channel=0)

            if self.ws_account_data and self.ws_account_data.sock and self.ws_account_data.sock.connected:
                heartbeat_message = {
                    "action": "heartbeat",
                    "auth-token": self.session_token,
                }
                try:
                    self.ws_account_data.send(json.dumps(heartbeat_message))
                    # print("Account Data Heartbeat Sent") #Optional
                except websocket.WebSocketConnectionClosedException:
                    print("Account Data WebSocket connection closed.")
                    self.ws_account_data = None

    def start_heartbeat_thread(self) -> None:
        """
        Start heartbeat thread.
        
        Initiates a daemon thread that sends periodic heartbeat messages to maintain connections.
        """
        self.heartbeat_thread = threading.Thread(target=self._send_heartbeat, daemon=True)
        self.heartbeat_thread.start()

    def get_account_balance(self, account_number: str) -> Optional[Dict[str, Any]]:
        """
        Get account balance information including buying power.

        Args:
            account_number: The account number to retrieve balance for.

        Returns:
            Dictionary with account balance data or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        return self._request("GET", f"/accounts/{account_number}/balances")

    def get_available_buying_power(self, account_number: str) -> Optional[float]:
        """
        Get available derivative buying power for an account.

        Args:
            account_number: The account number to retrieve buying power for.

        Returns:
            Available buying power as a float, or None if retrieval fails.
        """
        account_balance = self.get_account_balance(account_number)

        if not account_balance or "data" not in account_balance:
            print("Could not retrieve account balance.")
            return None

        # The 'derivative-buying-power' field holds available buying power for options
        available_bp = account_balance["data"].get("derivative-buying-power")
        if available_bp is not None:
            return float(available_bp)
        return None

    def get_orders(
            self,
            account_number: str,
            status: str = "all",
            start_date: Optional[datetime.date] = None,
            end_date: Optional[datetime.date] = None,
            limit: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Get orders for an account with optional filtering.

        Args:
            account_number: The account number to retrieve orders for.
            status: Order status filter ('all', 'open', 'filled', etc.).
            start_date: Optional start date for filtering.
            end_date: Optional end date for filtering.
            limit: Maximum number of orders to return.

        Returns:
            Dictionary with orders data or None if retrieval fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        params = {"status": status, "per-page": limit}

        if start_date:
            params["start-date"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["end-date"] = end_date.strftime("%Y-%m-%d")

        return self._request("GET", f"/accounts/{account_number}/orders", params=params)

    def calculate_iron_condor_bpr(
            self,
            account_number: str,
            underlying_symbol: str,
            short_put_strike: float,
            long_put_strike: float,
            short_call_strike: float,
            long_call_strike: float,
            expiration_date: str,
            quantity: int = 1,
            limit_price: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate buying power reduction for an iron condor.

        Args:
            account_number: The account number.
            underlying_symbol: The ticker symbol of the underlying asset.
            short_put_strike: Strike price of the short put.
            long_put_strike: Strike price of the long put.
            short_call_strike: Strike price of the short call.
            long_call_strike: Strike price of the long call.
            expiration_date: Expiration date in 'YYYY-MM-DD' format.
            quantity: Number of contracts.
            limit_price: Optional limit price for the order.

        Returns:
            Buying power reduction as a float, or None if calculation fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        # Prepare option symbols
        short_put = self._prepare_option_symbol(underlying_symbol, expiration_date, short_put_strike, "P")
        long_put = self._prepare_option_symbol(underlying_symbol, expiration_date, long_put_strike, "P")
        short_call = self._prepare_option_symbol(underlying_symbol, expiration_date, short_call_strike, "C")
        long_call = self._prepare_option_symbol(underlying_symbol, expiration_date, long_call_strike, "C")

        # Create legs for the request
        legs = [
            {"symbol": short_put, "quantity": quantity, "action": "Sell to Open", "instrument-type": "Equity Option"},
            {"symbol": long_put, "quantity": quantity, "action": "Buy to Open", "instrument-type": "Equity Option"},
            {"symbol": short_call, "quantity": quantity, "action": "Sell to Open", "instrument-type": "Equity Option"},
            {"symbol": long_call, "quantity": quantity, "action": "Buy to Open", "instrument-type": "Equity Option"}
        ]

        # Prepare request data
        data = {
            "legs": legs,
            "source": "user"
        }

        if limit_price is not None:
            data["price"] = limit_price
            data["price-effect"] = "Credit"
            data["order-type"] = "Limit"

        # Make dry run request to calculate BPR
        response = self._request("POST", f"/accounts/{account_number}/orders/dry-run", data=data)

        if not response or "data" not in response or "buying-power-effect" not in response["data"]:
            print("Failed to calculate buying power reduction.")
            return None

        bpr = response["data"]["buying-power-effect"]["change"]["effect"]
        return abs(float(bpr))  # Return positive value

    def dry_run_option_order(
            self,
            account_number: str,
            underlying_symbol: str,
            legs: List[Dict[str, Any]],
            order_type: str = "Limit",
            limit_price: Optional[float] = None,
            time_in_force: str = "Day"
    ) -> Optional[Dict[str, Any]]:
        """
        Perform a dry run of an option order to check validity.

        Args:
            account_number: The account number.
            underlying_symbol: The ticker symbol of the underlying asset.
            legs: List of order legs, each containing symbol, quantity, action, instrument_type.
            order_type: 'Limit' or 'Market'.
            limit_price: Price for limit orders.
            time_in_force: 'Day', 'GTC', or 'GTD'.

        Returns:
            Dry run response data, or None if the request fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        # Prepare request data
        data = {
            "source": "user",
            "order-type": order_type,
            "time-in-force": time_in_force,
            "legs": [self._dasherize_keys(leg) for leg in legs]
        }

        if order_type == "Limit" and limit_price is not None:
            data["price"] = limit_price
            data["price-effect"] = "Credit"

        # Make dry run request
        return self._request("POST", f"/accounts/{account_number}/orders/dry-run", data=data)

    def create_multi_leg_order(
            self,
            account_number: str,
            legs: List[Dict[str, Any]],
            order_type: str = "Limit",
            time_in_force: str = "Day",
            price: Optional[float] = None,
            price_effect: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a multi-leg option order.

        Args:
            account_number: The account number.
            legs: List of order legs, each containing symbol, quantity, action, instrument_type.
            order_type: 'Limit' or 'Market'.
            time_in_force: 'Day', 'GTC', or 'GTD'.
            price: Price for limit orders.
            price_effect: 'Credit' or 'Debit' for limit orders.

        Returns:
            API response for the order creation, or None if creation fails.
        """
        if not self.session_token:
            print("Not logged in.")
            return None

        # Prepare order data
        data = {
            "order-type": order_type,
            "time-in-force": time_in_force,
            "legs": [self._dasherize_keys(leg) for leg in legs]
        }

        if order_type == "Limit" and price is not None:
            data["price"] = price
            if price_effect:
                data["price-effect"] = price_effect

        # Submit the order
        return self._request("POST", f"/accounts/{account_number}/orders", data=data)

    def create_market_order(
            self,
            account_number: str,
            symbol: str,
            quantity: int,
            action: str,
            instrument_type: str = "Equity Option",
            time_in_force: str = "Day"
    ) -> Optional[Dict[str, Any]]:
        """
        Create a simple market order for a single instrument.

        Args:
            account_number: The account number.
            symbol: The instrument symbol.
            quantity: Number of shares or contracts.
            action: Order action ('Buy to Open', 'Sell to Open', 'Buy to Close', 'Sell to Close').
            instrument_type: Type of instrument ('Equity Option' or 'Equity').
            time_in_force: 'Day', 'GTC', or 'GTD'.

        Returns:
            API response for the order creation, or None if creation fails.
        """
        legs = [{
            "symbol": symbol,
            "quantity": quantity,
            "action": action,
            "instrument_type": instrument_type
        }]

        return self.create_multi_leg_order(
            account_number=account_number,
            legs=legs,
            order_type="Market",
            time_in_force=time_in_force
        )

    def create_iron_condor_order(
            self,
            account_number: str,
            short_put_symbol: str,
            long_put_symbol: str,
            short_call_symbol: str,
            long_call_symbol: str,
            quantity: int,
            credit_price: float,
            time_in_force: str = "Day"
    ) -> Optional[Dict[str, Any]]:
        """
        Create a four-leg iron condor order.

        Args:
            account_number: The account number.
            short_put_symbol: Symbol for the short put.
            long_put_symbol: Symbol for the long put.
            short_call_symbol: Symbol for the short call.
            long_call_symbol: Symbol for the long call.
            quantity: Number of contracts.
            credit_price: Limit price for the credit received.
            time_in_force: 'Day', 'GTC', or 'GTD'.

        Returns:
            API response for the order creation, or None if creation fails.
        """
        legs = [
            {"symbol": short_put_symbol, "quantity": quantity, "action": "Sell to Open",
             "instrument_type": "Equity Option"},
            {"symbol": long_put_symbol, "quantity": quantity, "action": "Buy to Open", "instrument_type": "Equity Option"},
            {"symbol": short_call_symbol, "quantity": quantity, "action": "Sell to Open",
             "instrument_type": "Equity Option"},
            {"symbol": long_call_symbol, "quantity": quantity, "action": "Buy to Open", "instrument_type": "Equity Option"}
        ]

        return self.create_multi_leg_order(
            account_number=account_number,
            legs=legs,
            order_type="Limit",
            time_in_force=time_in_force,
            price=credit_price,
            price_effect="Credit"
        )
