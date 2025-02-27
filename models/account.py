from typing import List
from .position import Position


class Account:
    """
    Represents a trading account at a broker.

    Maintains a list of positions and provides methods for calculating
    account value and managing positions.

    Attributes:
        account_number (str): The account identifier.
        account_type (str): The type of account (e.g., 'Margin', 'Cash', 'IRA').
        positions (List[Position]): List of Position objects in this account.
    """

    def __init__(self, account_number: str, account_type: str) -> None:
        """
        Initialize an Account instance.

        Args:
            account_number: The account identifier.
            account_type: The type of account (e.g., 'Margin', 'Cash', 'IRA').
        """
        self.account_number = account_number
        self.account_type = account_type
        self.positions: List[Position] = []

    def add_position(self, position: Position) -> None:
        """
        Adds a Position object to the account.

        Args:
            position: The Position object to add to this account.
        """
        self.positions.append(position)

    def get_positions(self) -> List[Position]:
        """
        Returns the list of Position objects in this account.

        Returns:
            List[Position]: All positions currently held in this account.
        """
        return self.positions

    def get_account_value(self) -> float:
        """
        Calculates and returns the total value of the account.

        Sums the market value of all positions in the account.

        Returns:
            float: Total account value.
        """
        account_value = 0.0
        for position in self.positions:
            account_value += position.market_value
        return account_value

    def __repr__(self) -> str:
        """
        Returns a string representation of the Account object.

        Returns:
            str: String representation for debugging.
        """
        return f"Account(account_number='{self.account_number}', type='{self.account_type}', num_positions={len(self.positions)})count_number}', type='{self.account_type}', num_positions={len(self.positions)})"