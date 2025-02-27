from typing import List, Dict, Any, Optional
from .price import Price
from .greeks import Greeks


class Symbol:
    """
    Tracks price and Greeks data for a financial instrument over time.
    
    Maintains a historical record of price and Greeks data, and calculates
    simple moving averages for key metrics.
    
    Attributes:
        symbol (str): The option or equity symbol.
        streamer_symbol (str): The symbol used by the streaming service.
        max_history (int): Maximum number of historical data points to keep.
        prices (List[Price]): Historical price data.
        price_sma (float): Simple moving average of midpoint prices.
        trading_range (float): Difference between highest ask and lowest bid.
        greeks (List[Greeks]): Historical Greeks data.
        volatility_sma (float): Simple moving average of volatility.
        delta_sma (float): Simple moving average of delta.
    """

    def __init__(
        self, 
        symbol: Optional[str] = None, 
        streamer_symbol: Optional[str] = None, 
        max_history: int = 10
    ) -> None:
        """
        Initialize Symbol tracking.
        
        Args:
            symbol: The option or equity symbol.
            streamer_symbol: The symbol used by the streaming service.
            max_history: Maximum number of historical data points to keep.
        """
        self.symbol = symbol
        self.streamer_symbol = streamer_symbol
        self.max_history = max_history

        self.prices: List[Price] = []
        self.price_sma: Optional[float] = None
        self.trading_range: Optional[float] = None
        self.is_trending_up: Optional[bool] = None

        self.greeks: List[Greeks] = []
        self.volatility_sma: Optional[float] = None
        self.delta_sma: Optional[float] = None

    def update_prices(self, quote_data: Dict[str, Any]) -> None:
        """
        Update price history with new quote data.
        
        Adds new price data to history, trims excess history,
        and recalculates price statistics.
        
        Args:
            quote_data: Dictionary with bid_price, ask_price, bid_size, ask_size, and last_price.
        """
        self.prices.append(Price(
            quote_data['bid_price'], 
            quote_data['ask_price'], 
            quote_data['bid_size'],
            quote_data['ask_size'], 
            quote_data['last_price']
        ))
        
        if len(self.prices) > self.max_history:
            self.prices.pop(0)
            
        self.price_sma = sum(p.midpoint_price for p in self.prices) / len(self.prices)
        
        # Calculate trading range (highest ask - lowest bid)
        self.trading_range = max(p.ask_price for p in self.prices) - min(p.bid_price for p in self.prices)
        
        # Determine trend (at least 3 prices needed for meaningful trend)
        if len(self.prices) >= 3:
            # Simple trend detection based on recent price movement
            recent_prices = [p.midpoint_price for p in self.prices[-3:]]
            self.is_trending_up = recent_prices[-1] > recent_prices[0]
        else:
            self.is_trending_up = None

    def update_greeks(self, greek_data: Dict[str, Any]) -> None:
        """
        Update Greeks history with new data.
        
        Adds new Greeks data to history, trims excess history,
        and recalculates Greek statistics.
        
        Args:
            greek_data: Dictionary with volatility, delta, gamma, theta, rho, and vega.
        """
        self.greeks.append(Greeks(
            greek_data['volatility'], 
            greek_data['delta'],  
            greek_data['gamma'],
            greek_data['theta'], 
            greek_data['rho'], 
            greek_data['vega']
        ))
        
        if len(self.greeks) > self.max_history:
            self.greeks.pop(0)
            
        self.volatility_sma = sum(g.volatility for g in self.greeks) / len(self.greeks)
        self.delta_sma = sum(g.delta for g in self.greeks) / len(self.greeks)
