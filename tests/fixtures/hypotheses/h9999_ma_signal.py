"""Throwaway hypothesis-shaped signal module for CLI tests (not a real hypothesis)."""

from tests.fixture_signals import MovingAverageCrossover, TomorrowPeek


def make_signal(window: int, leaky: bool = False):
    return TomorrowPeek() if leaky else MovingAverageCrossover(window)
