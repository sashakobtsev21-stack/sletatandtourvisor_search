"""toursearch — сравнение поиска туров на нескольких онлайн-площадках."""

from toursearch.models import (
    ComparisonReport,
    HotelOffer,
    Offer,
    ProviderResult,
    SearchParams,
)

__all__ = [
    "SearchParams",
    "Offer",
    "HotelOffer",
    "ProviderResult",
    "ComparisonReport",
]

__version__ = "0.1.0"
