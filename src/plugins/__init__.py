"""
Plugins package for xLP hedge system

Contains optional plugins that extend functionality without affecting core operations.
"""

from .matsu_reporter import MatsuReporter

__all__ = ['MatsuReporter']
