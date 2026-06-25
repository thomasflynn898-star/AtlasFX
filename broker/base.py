from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class AccountInfo:
    account_id: str
    balance: float
    nav: float
    unrealised_pnl: float
    margin_used: float
    margin_available: float
    currency: str
    open_trade_count: int

@dataclass
class Price:
    instrument: str
    bid: float
    ask: float
    timestamp: datetime
    @property
    def mid(self): return round((self.bid + self.ask) / 2, 5)
    @property
    def spread(self): return round(self.ask - self.bid, 5)

@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    trade_id: Optional[str]
    instrument: str
    direction: str
    units: float
    entry_price: float
    stop_loss: float
    take_profit: float
    error_message: Optional[str] = None

@dataclass
class OpenTrade:
    trade_id: str
    instrument: str
    direction: str
    units: float
    entry_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    unrealised_pnl: float
    open_time: datetime

class BaseBroker(ABC):
    @abstractmethod
    def get_account(self) -> AccountInfo: ...
    @abstractmethod
    def get_price(self, instrument: str) -> Price: ...
    @abstractmethod
    def get_open_trades(self) -> list[OpenTrade]: ...
    @abstractmethod
    def submit_market_order(self, instrument, direction, units, stop_loss, take_profit) -> OrderResult: ...
    @abstractmethod
    def close_trade(self, trade_id: str) -> bool: ...
    @abstractmethod
    def modify_trade(self, trade_id, stop_loss=None, take_profit=None) -> bool: ...
    @abstractmethod
    def get_candles(self, instrument, granularity, count) -> list[dict]: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    @property
    @abstractmethod
    def name(self) -> str: ...
