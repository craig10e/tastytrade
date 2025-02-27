from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any


class Order:
    """
    Represents an options order with all necessary parameters for execution.
    
    This class tracks the status of an order from creation through execution,
    including limit price adjustments and order status updates.
    
    Attributes:
        account (str): Account number for this order.
        underlying_symbol (str): The ticker symbol of the underlying asset.
        action (str): Order action ('Buy to Open', 'Sell to Open', etc.).
        option_type (str): Option type ('C' for call or 'P' for put).
        quantity (int): Number of contracts.
        dte (int): Days to expiration (used if expiration_date not provided).
        expiration_date (date): Specific expiration date for the option.
        delta (Optional[float]): Target delta value for option selection.
        price (Optional[float]): Target price for option selection.
        limit_distance (float): Relative distance between bid/ask for limit orders.
        limit_step (float): Amount to increment limit_distance when adjusting orders.
        seconds_to_wait (int): Seconds to wait before adjusting limit orders.
    """

    def __init__(
        self, 
        account: str, 
        underlying_symbol: str = 'SPX', 
        action: str = 'Buy to Open', 
        option_type: str = 'C', 
        quantity: int = 1,
        dte: int = 0, 
        expiration_date: Optional[date] = None, 
        delta: Optional[float] = None, 
        price: Optional[float] = None, 
        limit_distance: float = 0.4, 
        limit_step: float = 0.1,
        seconds_to_wait: int = 5
    ) -> None:
        """
        Initialize an Order instance.
        
        Args:
            account: Account number for this order.
            underlying_symbol: The ticker symbol of the underlying asset.
            action: Order action ('Buy to Open', 'Sell to Open', 'Buy to Close', 'Sell to Close').
            option_type: Option type ('C' for call or 'P' for put).
            quantity: Number of contracts.
            dte: Days to expiration (used if expiration_date not provided).
            expiration_date: Specific expiration date for the option.
            delta: Target delta value for option selection.
            price: Target price for option selection.
            limit_distance: Relative distance between bid/ask for limit orders (0.0-1.0).
            limit_step: Amount to increment limit_distance when adjusting orders.
            seconds_to_wait: Seconds to wait before adjusting limit orders.
        """
        self.account = account
        self.underlying_symbol = underlying_symbol
        self.action = action
        self.option_type = option_type
        self.quantity = quantity
        self.dte = dte
        self.expiration_date = expiration_date if expiration_date else date.today() + timedelta(days=dte)
        self.delta = delta
        self.price = price
        self.limit_distance = limit_distance  # Distance between bid and ask for calculating limit price
        self.limit_step = limit_step  # Step to increment limit_distance while attempting to fill order
        self.seconds_to_wait = seconds_to_wait  # Seconds to wait before adjusting limit order
        
        # Order execution tracking attributes
        self.datetime: Optional[datetime] = None
        self.order_id: Optional[str] = None
        self.symbol: Optional[str] = None
        self.streamer_symbol: Optional[str] = None
        self.strike_price: Optional[float] = None
        self.option_chain: Optional[List[Dict[str, Any]]] = None
        self.order_status: Optional[str] = None

    def adjust_limit_distance(self) -> None:
        """
        Increases the limit_distance by the limit_step amount.
        
        The limit_distance is capped at 1.0 to prevent the limit price
        from exceeding the ask price.
        """
        self.limit_distance += self.limit_step
        self.limit_distance = 1.0 if self.limit_distance > 1.0 else self.limit_distance
