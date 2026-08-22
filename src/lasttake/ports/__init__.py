"""Ports. Interfaces the domain and the checks depend on, with no SDK behind them.

Every adapter in ``lasttake.adapters`` implements one of these. The offline
adapters are not test doubles bolted on afterwards, they are how the product
runs when there is no network on a location, which on a real set is often.
"""
