"""Dedicated OpenSTA capacity pool, independent from RTL workers."""
from .admission import acquire_pool_slot, pool_capacity


def capacity():
    return pool_capacity('STA')


def acquire_slot():
    return acquire_pool_slot('STA')
