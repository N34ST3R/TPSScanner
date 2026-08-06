from dataclasses import dataclass


@dataclass
class AccountDraft:
    handle: str
    source: str
    display_name: str = ""


@dataclass
class CallDraft:
    account_handle: str
    source: str
    symbol: str
    direction: str
    entry_price: float
    entry_time: float
    source_call_id: str


class BaseAdapter:
    source = "base"

    async def fetch_profiles(self) -> list[AccountDraft]:
        raise NotImplementedError

    async def fetch_calls(self, accounts: list) -> list[CallDraft]:
        raise NotImplementedError
