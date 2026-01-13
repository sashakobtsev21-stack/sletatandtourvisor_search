# Sletat.ru and Tourvisor — Search Module Autotests

Automated tests for tour search and comparison on Sletat.ru and Tourvisor platforms.  
**Tech stack**: Python, pytest, Selenium WebDriver  
**Validates**: filter accuracy, results loading, error handling  
**Outputs**: number of tours, minimum price, execution time


test_data = {
    "departure_city": "Москва",
    "destination_country": "Турция",
    "departure_dates": ("26.06.2026", "28.06.2026"),
    "nights": "3-5",
    "tourists": "3 взрослых",
    "charter": 0,
    "operators": {"anex": 0, "biblioglobus": 0, "funsun": 0, "travelata": 0, "coral": 0, "sunmar": 0, "pegas": 0},
    "direct": 0,
}
