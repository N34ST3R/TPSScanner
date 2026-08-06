from src.toptraders.adapters.base import BaseAdapter


class TwitterAdapter(BaseAdapter):
    """Deferred: requires paid API credentials (academic/basic tier)."""

    source = "twitter"

    async def fetch_profiles(self):
        raise NotImplementedError(
            "Twitter adapter deferred — requires paid API credentials"
        )

    async def fetch_calls(self, accounts: list):
        raise NotImplementedError(
            "Twitter adapter deferred — requires paid API credentials"
        )
