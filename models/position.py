from typing import Optional


class Position:
    """
    Represents a single trading position.

    Tracks details about a financial instrument position including symbol,
    quantity, direction, and cost basis information.

    Attributes:
        symbol (str): The option or equity symbol.
        streamer_symbol (str): The symbol used by the streaming service.
        option_type (Optional[str]): Option type ('C' for call, 'P' for put, or None for non-options).
        underlying_symbol (str): The ticker symbol of the underlying asset.
        instrument_type (str): Type of instrument (e.g., 'EQUITY', 'OPTION').
        quantity (int): Number of contracts or shares.
        direction (str): Position direction ('LONG' or 'SHORT').
        cost_effect (str): Cost effect of the position.
        average_cost (float): Average cost basis per contract/share.
        market_value (float): Current market value of the position.
    """

    def __init__(
            self,
            symbol: str,
            streamer_symbol: str,
            underlying_symbol: str,
            instrument_type: str,
            quantity: int,
            direction: str,
            cost_effect: str,
            average_cost: float
    ) -> None:
        """
        Initialize a Position instance.

        Args:
            symbol: The option or equity symbol.
            streamer_symbol: The symbol used by the streaming service.
            underlying_symbol: The ticker symbol of the underlying asset.
            instrument_type: Type of instrument (e.g., 'EQUITY', 'OPTION').
            quantity: Number of contracts or shares.
            direction: Position direction ('LONG' or 'SHORT').
            cost_effect: Cost effect of the position.
            average_cost: Average cost basis per contract/share.
        """
        self.symbol = symbol
        self.streamer_symbol = streamer_symbol
        # Extract option type from symbol if it's an option
        # SPX   250321C06100000
        # 012345678901234567890
        if len(symbol) >= 15:
            self.option_type: Optional[str] = symbol[12]
        else:
            self.option_type = None
        self.underlying_symbol = underlying_symbol
        self.instrument_type = instrument_type
        self.quantity = quantity
        self.direction = direction
        self.cost_effect = cost_effect
        self.average_cost = average_cost
        self.market_value = 0.0  # Default value, to be updated later

    def __repr__(self) -> str:
        """
        Returns a string representation of the Position object.

        Returns:
            str: String representation for debugging.
        """
        return f"Position(symbol='{self.symbol}', type='{self.instrument_type}', quantity={self.quantity}, direction='{self.direction}')"
