import time
import threading
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException


class TourvisorSearchTest:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.selected_operators = []
        self.all_operators_with_prices = []
        self.MONTHS_RU = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }

    def setup(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        self.driver = webdriver.Chrome(options=options)
        self.driver.maximize_window()
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.wait = WebDriverWait(self.driver, 15)

    def open_tourvisor(self):
        self.driver.get("https://tourvisor.ru/search.php")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    def _safe_click(self, element, description=""):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.3)
            element.click()
            return True
        except StaleElementReferenceException:
            return False
        except Exception as e:
            print(f"⚠️ Ошибка клика '{description}': {e}")
            return False

    def _wait_for_element(self, by, value, timeout=10, description=""):
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            print(f"❌ Таймаут: {description}")
            raise

    def _select_departure_city(self, city):
        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVDepartureFilter")
        self._safe_click(field)
        self._wait_for_element(By.CLASS_NAME, "TVDepartureTableBody")
        option = self._wait_for_element(By.XPATH, f"//div[contains(@class, 'TVDepartureTableBody')]//div[contains(text(), '{city}')][1]")
        self._safe_click(option)

    def _select_destination_country(self, country):
        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVCountryFilter")
        self._safe_click(field)
        self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVCountryAirportList') and not(contains(@class, 'TVHide'))]")
        option = self._wait_for_element(By.XPATH, f"//div[contains(@class, 'TVCountryAirportList')]//div[contains(@class, 'TVComplexListItem') and contains(text(), '{country}')][1]")
        self._safe_click(option)

    def _scroll_to_month(self, target_month_name, target_year):
        for attempt in range(12):
            try:
                month_el = self.driver.find_element(By.XPATH, "//div[contains(@class, 'TVCalendarTitleControlMonth')]")
                year_el = self.driver.find_element(By.XPATH, "//div[contains(@class, 'TVCalendarTitleControlYear')]")
                if month_el.text.strip().upper() == target_month_name.upper() and year_el.text.strip() == str(target_year):
                    return True
                next_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVCalendarSliderViewRightButton') and not(contains(@class, 'TVDisabled'))]")))
                self._safe_click(next_btn)
                time.sleep(0.4)
            except Exception as e:
                if attempt == 0:
                    print(f"⚠️ Прокрутка: {e}")
        raise RuntimeError(f"❌ Месяц {target_month_name} {target_year} не найден")

    def _click_calendar_day(self, date_obj):
        day = date_obj.day
        element = self._wait_for_element(By.XPATH, f"//t-td[@data-value='{day}' and not(contains(@class, 'TVCalendarDisabledCell'))]")
        self._safe_click(element)

    def _select_departure_dates(self, dep_str, ret_str=None):
        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVFlyDatesFilter")
        self._safe_click(field)
        self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVFlyDatesSelectTooltip')]")
        dep_date = datetime.strptime(dep_str, "%d.%m.%Y")
        self._scroll_to_month(self.MONTHS_RU[dep_date.month], dep_date.year)
        self._click_calendar_day(dep_date)
        time.sleep(0.5)
        if ret_str:
            ret_date = datetime.strptime(ret_str, "%d.%m.%Y")
            if dep_date.month != ret_date.month or dep_date.year != ret_date.year:
                self._scroll_to_month(self.MONTHS_RU[ret_date.month], ret_date.year)
            self._click_calendar_day(ret_date)
            time.sleep(0.3)
        try:
            self.driver.execute_script("document.elementFromPoint(10, 10).click();")
        except:
            try:
                self.driver.find_element(By.TAG_NAME, "body").click()
            except:
                pass

    def _select_nights(self, nights_range):
        field = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVNightsFilter')]")
        self._safe_click(field)
        self._wait_for_element(By.CLASS_NAME, "TVRangeTableContainer")
        min_night, max_night = map(int, nights_range.split("-"))
        min_cell = self._wait_for_element(By.XPATH, f"//div[contains(@class, 'TVRangeTableCell') and .//div[contains(@class, 'TVRangeCellLabel') and text()='{min_night}']]")
        self._safe_click(min_cell)
        max_cell = self._wait_for_element(By.XPATH, f"//div[contains(@class, 'TVRangeTableCell') and .//div[contains(@class, 'TVRangeCellLabel') and text()='{max_night}']]")
        self._safe_click(max_cell)

    def _select_tourists(self, tourists_str):
        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVTouristsFilter")
        self._safe_click(field)
        self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVTouristsSelectTooltip')]")
        match = re.search(r'(\d+)\s*взросл', tourists_str)
        if not match:
            raise ValueError(f"Не удалось извлечь число туристов из: {tourists_str}")
        target_count = int(match.group(1))
        current = self.driver.find_element(By.XPATH, "//div[contains(@class, 'TVTouristCount') and contains(@class, 'TVTouristAll')]")
        current_count = int(re.search(r'\d+', current.text).group())
        plus_btn = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVTouristActionPlus')]")
        minus_btn = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVTouristActionMinus')]")
        select_btn = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVButtonControl') and contains(text(), 'Выбрать')]")
        while current_count != target_count:
            btn = plus_btn if current_count < target_count else minus_btn
            self._safe_click(btn)
            current_count += 1 if current_count < target_count else -1
            time.sleep(0.2)
        self._safe_click(select_btn)
        expected = f"{target_count} взрослых"
        self.wait.until(EC.text_to_be_present_in_element((By.CSS_SELECTOR, "div.TVTouristsFilter"), expected))

    def _select_operators(self, operators_config):
        self.selected_operators = []
        if not operators_config or not any(operators_config.values()):
            return
        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVOperatorListFilter")
        self.driver.execute_script("arguments[0].click();", field)
        time.sleep(1.5)
        self._wait_for_element(By.CLASS_NAME, "TVOperatorsList")
        mapping = {
            'anex': 'Anex',
            'biblioglobus': 'Biblioglobus',
            'funsun': 'FUN&SUN (TUI)',
            'travelata': 'Travelata',
            'coral': 'Coral',
            'sunmar': 'Sunmar',
            'pegas': 'Pegas Touristik'
        }
        for key, flag in operators_config.items():
            if flag and key in mapping:
                name = mapping[key]
                try:
                    el = self.driver.find_element(By.XPATH, f"//div[contains(@class, 'TVCheckBox') and contains(text(), '{name}') and not(contains(@class, 'TVDisabled'))]")
                    if "TVChecked" not in el.get_attribute("class"):
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.4)
                    self.selected_operators.append(name)
                except Exception as e:
                    print(f"⚠️ Не удалось выбрать {name}: {e}")

    def _toggle_charter_checkbox(self, value):
        checkbox = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVCheckboxControl') and .//div[contains(text(), 'Только чартер')]]")
        is_checked = "TVChecked" in checkbox.get_attribute("class")
        if (value == 1 and not is_checked) or (value == 0 and is_checked):
            self._safe_click(checkbox)

    def click_search_button(self):
        btn = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVSearchButton') and contains(text(), 'Найти туры')]")
        self._safe_click(btn)

    def _wait_for_search_completion(self):
        start = time.time()
        while time.time() - start < 120:
            try:
                bars = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'TVProgressBar')]")
                visible = any(b.is_displayed() for b in bars if not b.find_elements(By.XPATH, "..//div[contains(@class, 'TVResultToolbar')]"))
                if not visible and not self.driver.find_elements(By.XPATH, "//div[contains(@class, 'TVResultToolbarProgress') and @style]"):
                    return True
                if time.time() - start > 30 and self.driver.find_elements(By.CSS_SELECTOR, ".TVResultItem"):
                    return True
                time.sleep(1.5)
            except:
                time.sleep(1.5)
        return True

    def _get_all_operators_with_prices(self):
        ops = []
        try:
            btn = self.driver.find_element(By.XPATH, "//div[contains(@class, 'TVResultToolbarOperators')]")
            self._safe_click(btn)
            time.sleep(1)
            items = self.driver.find_element(By.CLASS_NAME, "TVOperatorFilterColumnBody").find_elements(By.CSS_SELECTOR, ".TVOperatorFilterItemControl")
            for item in items:
                try:
                    name = item.find_element(By.CSS_SELECTOR, ".TVCheckBox").text.strip()
                    price = item.find_element(By.CSS_SELECTOR, ".TVOperatorFilterItemPriceValue").text.strip()
                    currency = item.find_element(By.CSS_SELECTOR, ".TVOperatorFilterItemPriceCurrency").text.strip()
                    if name and price:
                        ops.append({'name': name, 'price': f"{price} {currency}"})
                except:
                    continue
            self.driver.execute_script("document.elementFromPoint(100,100).click();")
            time.sleep(0.3)
        except:
            pass
        return ops

    def _extract_first_tour_info(self):
        tours = self.driver.find_elements(By.CSS_SELECTOR, ".TVResultItem")
        if not tours:
            return False
        if not self.selected_operators or len(self.selected_operators) >= 2:
            self.all_operators_with_prices = self._get_all_operators_with_prices()
        return True

    def verify_search_results(self):
        return self._wait_for_search_completion() and self._extract_first_tour_info()

    def fill_search_form(self, **data):
        self._select_departure_city(data["departure_city"])
        self._select_destination_country(data["destination_country"])
        self._select_departure_dates(data["departure_dates"][0], data["departure_dates"][1])
        self._select_nights(data["nights"])
        self._select_tourists(data["tourists"])
        self._select_operators(data.get("operators", {}))
        self._toggle_charter_checkbox(data.get("charter", 1))

    def run_test(self, test_data):
        print("\n🚀 ЗАПУСК ТЕСТА TOURVISOR\n" + "=" * 40)
        success = False
        search_start = None
        result_operators = []
        try:
            self.setup()
            self.open_tourvisor()
            self.fill_search_form(**test_data)
            self.click_search_button()
            search_start = time.time()  # ✅ Время отсчитывается отсюда
            success = self.verify_search_results()
        except Exception as e:
            print(f"\n💥 Ошибка Tourvisor: {e}")
        finally:
            duration = time.time() - (search_start or time.time())
            status = "🎉 УСПЕХ" if success else "💥 ПРОВАЛ"
            print(f"\n{status} — Tourvisor — {duration:.1f} сек")
            if success and (not self.selected_operators or len(self.selected_operators) >= 2):
                result_operators = [
                    {"name": op["name"], "price": op["price"]}
                    for op in self.all_operators_with_prices
                ]
            if self.driver:
                self.driver.quit()
        return {"success": success, "duration": duration, "operators": result_operators}


class SletatSearchTest:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.test_data = None

    def setup(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        self.driver = webdriver.Chrome(options=options)
        self.driver.maximize_window()
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.wait = WebDriverWait(self.driver, 20)

    def open_sletat(self):
        self.driver.get("https://sletat.ru/b2b/")
        closeAD = WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".icon-remove")),message="Кнопка не найдена")
        closeAD.click()
        self._close_cookies()

    def _close_cookies(self):
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, "button[data-testid='layout.cookie-alert.accept-btn']")
            btn.click()
        except:
            pass

    def _select_departure_city(self, city: str):
        field = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.excludeClickOutside")))
        field.click()
        field.clear()
        field.send_keys(city)
        time.sleep(0.5)
        city_list = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.city-selector-list")))
        for option in city_list.find_elements(By.CSS_SELECTOR, "ul li button"):
            if city.lower() in option.text.strip().lower():
                option.click()
                return True
        raise Exception(f"Город '{city}' не найден")

    def _select_destination_country(self, country: str):
        field = self.wait.until(EC.element_to_be_clickable((By.ID, "ui-select-country-to")))
        field.click()
        time.sleep(0.5)
        country_list = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.uis-select__options_country-to")))
        for option in country_list.find_elements(By.CSS_SELECTOR, "li.uis-select__options-item"):
            try:
                span = option.find_element(By.CSS_SELECTOR, "span.slsf-country-to__select-text")
                if country.lower() in span.text.strip().lower():
                    option.click()
                    return True
            except:
                continue
        raise Exception(f"Страна '{country}' не найдена")

    def _select_departure_dates(self, dep: str, ret: str):
        container = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.containerTitle")))
        container.click()
        time.sleep(0.5)
        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.rdrDay")))
        self._navigate_to_date(dep)
        if not self._select_single_date(dep): raise Exception("Дата вылета не выбрана")
        if not self._select_single_date(ret): raise Exception("Дата возврата не выбрана")
        confirm = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.date-range-date-label")))
        confirm.click()

    def _navigate_to_date(self, date_str: str):
        dt = datetime.strptime(date_str, "%d.%m.%Y")
        target_month, target_year = dt.month, dt.year
        cur_month, cur_year = self._parse_month_year(self._get_current_month_year())
        diff = (target_year - cur_year) * 12 + (target_month - cur_month)
        for _ in range(abs(diff)):
            if diff > 0:
                self._click_next_month()
            else:
                self._click_prev_month()
            time.sleep(0.3)

    def _get_current_month_year(self):
        try:
            return self.driver.find_element(By.CSS_SELECTOR, ".rdrMonthName").text.strip()
        except:
            return "Январь 2025"

    def _parse_month_year(self, text: str):
        ru = {m: i + 1 for i, m in enumerate(['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'])}
        p = text.split()
        month = ru.get(p[0].lower(), 1)
        year = int(p[1]) if len(p) > 1 and p[1].isdigit() else datetime.now().year
        return month, year

    def _click_next_month(self):
        self.driver.find_element(By.CSS_SELECTOR, "button.navigatorSlideButton.nextButton").click()

    def _click_prev_month(self):
        els = self.driver.find_elements(By.CSS_SELECTOR, "button.navigatorSlideButton:not(.nextButton)")
        if els: els[0].click()

    def _select_single_date(self, date_str: str):
        day = str(datetime.strptime(date_str, "%d.%m.%Y").day)
        for el in self.driver.find_elements(By.CSS_SELECTOR, "button.rdrDay"):
            try:
                span = el.find_element(By.CSS_SELECTOR, "span.customDay > span:first-child")
                if span.text.strip() == day and "rdrDayDisabled" not in el.get_attribute("class"):
                    el.click()
                    return True
            except:
                continue
        return False

    def _select_nights_js(self, nights_range: str):
        mn, mx = map(int, nights_range.split("-"))
        self.driver.execute_script(f"""
            const min = document.getElementById('ui-select-nightsMin');
            const max = document.getElementById('ui-select-nightsMax');
            if (min && max) {{
                min.value = '{mn}'; max.value = '{mx}';
                [min, max].forEach(e => e.dispatchEvent(new Event('input')));
            }}
        """)
        time.sleep(0.5)

    def _select_tourists(self, count: int):
        container = self.wait.until(EC.presence_of_element_located((By.ID, "touristSelector")))
        current = container.find_element(By.CLASS_NAME, "tourist-current-select")
        current.click()
        plus = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@class='adult-counter-btn' and text()='+']")))
        cur = int(re.search(r'\d+', current.text).group())
        while cur < count:
            self.driver.execute_script("arguments[0].click();", plus)
            cur += 1
            time.sleep(0.2)
        self.driver.execute_script("arguments[0].click();", current)

    def _select_operators(self, op_dict):
        ops_to_select = [name for name, flag in op_dict.items() if flag == 1]
        if not ops_to_select:
            return
        sf = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".uis-text_tour-operator")))
        sf.click()
        try:
            all_checkbox = self.driver.find_element(By.CSS_SELECTOR, ".slsf-tour-operator__selected-block input")
            if self.driver.execute_script("return arguments[0].checked;", all_checkbox):
                self.driver.execute_script("arguments[0].click();", all_checkbox)
                time.sleep(0.4)
        except:
            pass
        def select_op(name):
            try:
                sf_el = self.driver.find_element(By.CSS_SELECTOR, ".uis-text_tour-operator")
                sf_el.clear()
                self.driver.execute_script("arguments[0].value = '';", sf_el)
                sf_el.click()
                time.sleep(0.2)
                sf_el.send_keys(name)
                time.sleep(0.5)
                label = self.driver.find_element(By.XPATH, f"//label[contains(@class, 'tour-operator') and .//span[@class='slsf-text-bold' and normalize-space(text())='{name}']]")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", label)
                checkbox = label.find_element(By.TAG_NAME, "input")
                if not self.driver.execute_script("return arguments[0].checked;", checkbox):
                    self.driver.execute_script("arguments[0].click();", label)
            except Exception as e:
                print(f"⚠️ {name}: {e}")
        for op in ops_to_select:
            select_op(op)
            time.sleep(0.2)

    def _toggle_charter(self, enable_charter):
        def set_flag(label_text, enable):
            if not enable: return
            try:
                label = self.driver.find_element(By.XPATH, f"//label[contains(@class, 'uis-checkbox__label_flight-info') and contains(., '{label_text}')]")
                checkbox = label.find_element(By.TAG_NAME, "input")
                if not self.driver.execute_script("return arguments[0].checked;", checkbox):
                    self.driver.execute_script("arguments[0].click();", checkbox)
            except:
                pass
        set_flag("Чартерные", bool(enable_charter))
        set_flag("Прямые", bool(self.test_data.get("direct", False)))

    def _click_search_button(self):
        self.driver.execute_script("""
            const btn = document.querySelector('[data-testid="b2b.search-form.search-btn"]');
            if (btn) btn.click();
        """)

    def _parse_results_after_search(self):
        try:
            WebDriverWait(self.driver, 3).until(EC.presence_of_element_located((By.CLASS_NAME, "tour-not-found-message")))
            return []
        except:
            pass
        try:
            status_div = WebDriverWait(self.driver, 90).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.search-status__tours-count")))
            count_span = status_div.find_element(By.CSS_SELECTOR, "span.search-status__text-bold:first-child")
            total_tours = int(count_span.text.replace(" ", ""))
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, ".blinchik__hide-button.blinchik__hide-button_closed")
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.4)
            except:
                pass
            ops = []
            try:
                container = self.driver.find_element(By.CSS_SELECTOR, ".blinchik__operator-container")
                for item in container.find_elements(By.CSS_SELECTOR, "li.blinchik__operator-item"):
                    try:
                        label = item.find_element(By.CSS_SELECTOR, "label")
                        name = self.driver.execute_script("return (arguments[0].childNodes[0].textContent || '').trim();", label)
                        disabled = "uis-checkbox__label_disabled" in label.get_attribute("class")
                        price_el = item.find_elements(By.CSS_SELECTOR, ".blinchik__price .sr-currency-rub")
                        if price_el and not disabled:
                            price = int(price_el[0].text.replace(" ", ""))
                            ops.append({"name": name, "price": f"{price} ₽"})
                    except:
                        continue
            except:
                pass
            return ops
        except:
            return []

    def run_test(self, test_data):
        self.test_data = test_data
        print("\n🚀 ЗАПУСК ТЕСТА SLETAT\n" + "=" * 40)
        result_operators = []
        search_start = None
        try:
            self.setup()
            self.open_sletat()
            self._select_departure_city(test_data["departure_city"])
            self._select_destination_country(test_data["destination_country"])
            self._select_departure_dates(*test_data["departure_dates"])
            self._select_nights_js(test_data["nights"])
            self._select_tourists(test_data["tourists"])
            ops = test_data["operators"]
            if any(ops.values()):
                self._select_operators(ops)
            self._toggle_charter(test_data.get("charter", False))
            self._click_search_button()
            search_start = time.time()
            result_operators = self._parse_results_after_search()
        except Exception as e:
            print(f"\n💥 Ошибка Sletat: {e}")
        finally:
            duration = time.time() - (search_start or time.time())
            status = "🎉 УСПЕХ" if result_operators else "⚠️ НЕТ ТУРОВ"
            print(f"\n{status} — Sletat — {duration:.1f} сек")
            if self.driver:
                self.driver.quit()
        return {"success": bool(result_operators), "duration": duration, "operators": result_operators}


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


def run_tourvisor(test_data):
    data = test_data.copy()
    if data["departure_city"] == "Санкт-Петербург":
        data["departure_city"] = "С.Петербург"
    if isinstance(data["tourists"], int):
        data["tourists"] = f"{data['tourists']} взрослых"
    return TourvisorSearchTest().run_test(data)

def run_sletat(test_data):
    data = test_data.copy()
    if isinstance(data["tourists"], str):
        match = re.search(r'^(\d+)', data["tourists"])
        data["tourists"] = int(match.group(1)) if match else 1
    return SletatSearchTest().run_test(data)


if __name__ == "__main__":
    print("🏁 Запуск тестов на Tourvisor и Sletat...")
    results = {"tourvisor": None, "sletat": None}

    def target_tv():
        results["tourvisor"] = run_tourvisor(test_data)

    def target_sl():
        results["sletat"] = run_sletat(test_data)

    t1 = threading.Thread(target=target_tv, name="TourvisorThread")
    t2 = threading.Thread(target=target_sl, name="SletatThread")

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    tv = results["tourvisor"]
    sl = results["sletat"]

    print("\n" + "=" * 80)
    print("📊 СРАВНЕНИЕ РЕЗУЛЬТАТОВ")
    print("=" * 80)
    print(f"{'Sletat':<40} | {'Tourvisor':<40}")
    print("-" * 80)
    sletat_time = f"⏱️ {sl['duration']:.1f} сек" if sl else "—"
    tourvisor_time = f"⏱️ {tv['duration']:.1f} сек" if tv else "—"
    print(f"{sletat_time:<40} | {tourvisor_time:<40}")
    print()

    if sl and sl["operators"]:
        print("✅ Операторы Sletat:")
        for op in sl["operators"]:
            print(f"   • {op['name']} — {op['price']}")
    else:
        print("❌ Sletat: операторов с турами не найдено")

    if tv and tv["operators"]:
        print("\n✅ Операторы Tourvisor:")
        for op in tv["operators"]:
            print(f"   • {op['name']} — {op['price']}")
    else:
        print("\n❌ Tourvisor: операторов с турами не найдено")

    print("\n🏁 Все тесты завершены.")