from datetime import datetime


class Price:
    """
    Represents price data for a financial instrument at a point in time.
    
    Attributes:
        datetime (datetime): Timestamp when this price data was recorded.
        bid_price (float): Current bid price.
        ask_price (float): Current ask price.
        midpoint_price (float): Calculated midpoint between bid and ask.
        bid_size (int): Size of the bid (number of contracts/shares).
        ask_size (int): Size of the ask (number of contracts/shares).
        last_price (float): Price of the most recent trade.
    """

    def __init__(
        self, 
        bid_price: float, 
        ask_price: float, 
        bid_size: int, 
        ask_size: int, 
        last_price: float
    ) -> None:
        """
        Initialize Price data.
        
        Args:
            bid_price: Current bid price.
            ask_price: Current ask price.
            bid_size: Size of the bid.
            ask_size: Size of the ask.
            last_price: Price of the most recent trade.
        """
        self.datetime = datetime.now()
        self.bid_price = bid_price
        self.ask_price = ask_price
        self.midpoint_price = (bid_price + ask_price) / 2.0
        self.bid_size = bid_size
        self.ask_size = ask_size
        self.last_price = last_price
