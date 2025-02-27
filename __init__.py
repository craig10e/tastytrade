# tastytrade/__init__.py
"""
Tastytrade Python API and Trading Library.

A comprehensive library for interacting with the Tastytrade trading platform,
including API access, order management, and market data streaming.
"""

from .api.tastytrade_api import TastytradeAPI
from .broker.tastytrade_broker import TastytradeBroker
from .models.account import Account
from .models.position import Position
from .models.order import Order
from .models.price import Price
from .models.greeks import Greeks
from .models.symbol import Symbol

__version__ = '0.1.0'


# tastytrade/api/__init__.py
"""
API client modules for interacting with the Tastytrade platform.
"""

from .tastytrade_api import TastytradeAPI


# tastytrade/models/__init__.py
"""
Data models for representing Tastytrade entities and market data.
"""

from .account import Account
from .position import Position
from .order import Order
from .price import Price
from .greeks import Greeks
from .symbol import Symbol


# tastytrade/broker/__init__.py
"""
Broker implementation for executing trades on the Tastytrade platform.
"""

from .tastytrade_broker import TastytradeBroker
