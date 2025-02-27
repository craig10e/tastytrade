from datetime import datetime


class Greeks:
    """
    Represents the Greek values for an options contract at a point in time.
    
    Attributes:
        datetime (datetime): Timestamp when this data was recorded.
        volatility (float): Implied volatility.
        delta (float): Rate of change of option price with respect to underlying price.
        gamma (float): Rate of change of delta with respect to underlying price.
        theta (float): Rate of change of option price with respect to time.
        rho (float): Rate of change of option price with respect to interest rate.
        vega (float): Rate of change of option price with respect to volatility.
    """

    def __init__(
        self, 
        volatility: float, 
        delta: float, 
        gamma: float, 
        theta: float, 
        rho: float, 
        vega: float
    ) -> None:
        """
        Initialize Greeks data.
        
        Args:
            volatility: Implied volatility.
            delta: Rate of change of option price with respect to underlying price.
            gamma: Rate of change of delta with respect to underlying price.
            theta: Rate of change of option price with respect to time.
            rho: Rate of change of option price with respect to interest rate.
            vega: Rate of change of option price with respect to volatility.
        """
        self.datetime = datetime.now()
        self.volatility = volatility
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.rho = rho
        self.vega = vega
