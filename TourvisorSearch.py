import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException


class TourvisorSearchTest:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.selected_operators = []  # Храним выбранных операторов
        self.all_operators_with_prices = []  # Храним всех операторов с ценами
        self.MONTHS_RU = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }

    def setup(self):
        """Инициализация драйвера с оптимизированными настройками"""
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(options=options)
        self.driver.maximize_window()
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        self.wait = WebDriverWait(self.driver, 15)

    def open_tourvisor(self):
        """Открытие сайта с проверкой успешной загрузки"""
        self.driver.get("https://tourvisor.ru/search.php")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        print("✅ Сайт Tourvisor открыт")

    def _safe_click(self, element, description=""):
        """Безопасный клик с обработкой исключений"""
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", element)
            time.sleep(0.3)
            element.click()
            if description:
                print(f"✅ {description}")
            return True
        except StaleElementReferenceException:
            print(f"⚠️ Stale element при клике: {description}, повторная попытка...")
            return False
        except Exception as e:
            print(f"❌ Ошибка при клике {description}: {e}")
            return False

    def _wait_for_element(self, by, value, timeout=10, description=""):
        """Ожидание элемента с улучшенной обработкой ошибок"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            raise TimeoutException(f"Элемент не найден: {description} ({value})")

    def _select_departure_city(self, city):
        """Выбор города вылета"""
        print(f"📍 Город вылета: {city}")

        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVDepartureFilter", description="Поле выбора города")
        self._safe_click(field, "Открыт выбор города")

        self._wait_for_element(By.CLASS_NAME, "TVDepartureTableBody", description="Список городов")

        option = self._wait_for_element(
            By.XPATH,
            f"//div[contains(@class, 'TVDepartureTableBody')]//div[contains(text(), '{city}')][1]",
            description=f"Город {city}"
        )
        self._safe_click(option, f"Выбран город {city}")

    def _select_destination_country(self, country):
        """Выбор страны назначения"""
        print(f"🌍 Страна: {country}")

        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVCountryFilter", description="Поле выбора страны")
        self._safe_click(field, "Открыт выбор страны")

        self._wait_for_element(
            By.XPATH,
            "//div[contains(@class, 'TVCountryAirportList') and not(contains(@class, 'TVHide'))]",
            description="Список стран"
        )

        option = self._wait_for_element(
            By.XPATH,
            f"//div[contains(@class, 'TVCountryAirportList')]//div[contains(@class, 'TVComplexListItem') and contains(text(), '{country}')][1]",
            description=f"Страна {country}"
        )
        self._safe_click(option, f"Выбрана страна {country}")

    def _scroll_to_month(self, target_month_name, target_year):
        """Прокрутка календаря к нужному месяцу"""
        print(f"🗓️ Прокрутка календаря к: {target_month_name} {target_year}")

        for attempt in range(12):
            try:
                month_el = self.driver.find_element(By.XPATH, "//div[contains(@class, 'TVCalendarTitleControlMonth')]")
                year_el = self.driver.find_element(By.XPATH, "//div[contains(@class, 'TVCalendarTitleControlYear')]")

                current_month = month_el.text.strip().upper()
                current_year = year_el.text.strip()

                if current_month == target_month_name.upper() and current_year == str(target_year):
                    print(f"✅ Найден месяц: {month_el.text} {year_el.text}")
                    return True

                print(f"🔍 Текущий: '{month_el.text}' ({current_month}), '{current_year}'")

                next_btn = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH,
                                                "//div[contains(@class, 'TVCalendarSliderViewRightButton') and not(contains(@class, 'TVDisabled'))]"))
                )
                self._safe_click(next_btn, "Прокрутка календаря")
                time.sleep(0.5)

            except Exception as e:
                if attempt == 0:
                    print(f"⚠️ Ошибка при прокрутке: {e}")
                continue

        raise RuntimeError(f"❌ Месяц {target_month_name} {target_year} не найден после 12 попыток")

    def _click_calendar_day(self, date_obj):
        """Клик по дню в календаре"""
        day = date_obj.day
        element = self._wait_for_element(
            By.XPATH,
            f"//t-td[@data-value='{day}' and not(contains(@class, 'TVCalendarDisabledCell'))]",
            description=f"День {day}"
        )
        self._safe_click(element, f"Выбран день {day}")

    def _select_departure_dates(self, dep_str, ret_str=None):
        """Выбор дат вылета и возвращения - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ"""
        print(f"🛫 Даты: {dep_str} → {ret_str or '—'}")

        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVFlyDatesFilter", description="Поле выбора дат")
        self._safe_click(field, "Открыт календарь")

        self._wait_for_element(
            By.XPATH,
            "//div[contains(@class, 'TVFlyDatesSelectTooltip')]",
            description="Календарь"
        )

        # Выбираем дату вылета
        dep_date = datetime.strptime(dep_str, "%d.%m.%Y")
        self._scroll_to_month(self.MONTHS_RU[dep_date.month], dep_date.year)
        self._click_calendar_day(dep_date)

        # Уменьшенная задержка после выбора первой даты
        time.sleep(0.5)

        # Если указана дата возвращения, выбираем ее
        if ret_str:
            ret_date = datetime.strptime(ret_str, "%d.%m.%Y")

            # Прокручиваем к месяцу возвращения только если это необходимо
            if dep_date.month != ret_date.month or dep_date.year != ret_date.year:
                self._scroll_to_month(self.MONTHS_RU[ret_date.month], ret_date.year)

            # Выбираем дату возвращения
            self._click_calendar_day(ret_date)

            # Минимальная задержка после выбора второй даты
            time.sleep(0.3)

        # Быстрое закрытие календаря через JavaScript
        try:
            self.driver.execute_script("""
                var elements = document.elementsFromPoint(10, 10);
                for (var i = 0; i < elements.length; i++) {
                    if (!elements[i].closest('.TVFlyDatesSelectTooltip')) {
                        elements[i].click();
                        break;
                    }
                }
            """)
        except:
            # Резервный способ закрытия
            try:
                body = self.driver.find_element(By.TAG_NAME, "body")
                body.click()
            except:
                pass

        print("✅ Даты выбраны")

    def _select_nights(self, nights_range):
        """Выбор диапазона ночей"""
        print(f"🏨 Ночи: {nights_range}")

        field = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVNightsFilter')]",
                                       description="Поле выбора ночей")
        self._safe_click(field, "Открыт выбор ночей")

        self._wait_for_element(By.CLASS_NAME, "TVRangeTableContainer", description="Таблица диапазона ночей")

        min_night, max_night = map(int, nights_range.split("-"))

        min_cell = self._wait_for_element(
            By.XPATH,
            f"//div[contains(@class, 'TVRangeTableCell') and .//div[contains(@class, 'TVRangeCellLabel') and text()='{min_night}']]",
            description=f"Ячейка {min_night} ночей"
        )
        self._safe_click(min_cell, f"Выбрано минимум {min_night} ночей")

        max_cell = self._wait_for_element(
            By.XPATH,
            f"//div[contains(@class, 'TVRangeTableCell') and .//div[contains(@class, 'TVRangeCellLabel') and text()='{max_night}']]",
            description=f"Ячейка {max_night} ночей"
        )
        self._safe_click(max_cell, f"Выбрано максимум {max_night} ночей")

    def _select_tourists(self, tourists_str):
        """Выбор количества туристов"""
        print(f"👥 Туристы: {tourists_str}")

        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVTouristsFilter", description="Поле выбора туристов")
        self._safe_click(field, "Открыт выбор туристов")

        self._wait_for_element(
            By.XPATH,
            "//div[contains(@class, 'TVTouristsSelectTooltip')]",
            description="Окно выбора туристов"
        )

        match = re.search(r'(\d+)\s*взросл', tourists_str)
        if not match:
            raise ValueError(f"Не удалось извлечь число туристов из: {tourists_str}")

        target_count = int(match.group(1))

        current_element = self.driver.find_element(
            By.XPATH,
            "//div[contains(@class, 'TVTouristCount') and contains(@class, 'TVTouristAll')]"
        )
        current_count = int(re.search(r'\d+', current_element.text).group())

        plus_btn = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVTouristActionPlus')]",
                                          description="Кнопка '+'")
        minus_btn = self._wait_for_element(By.XPATH, "//div[contains(@class, 'TVTouristActionMinus')]",
                                           description="Кнопка '-'")
        select_btn = self._wait_for_element(
            By.XPATH,
            "//div[contains(@class, 'TVButtonControl') and contains(text(), 'Выбрать')]",
            description="Кнопка выбора"
        )

        while current_count != target_count:
            if current_count < target_count:
                self._safe_click(plus_btn, "Увеличение количества туристов")
                current_count += 1
            else:
                self._safe_click(minus_btn, "Уменьшение количества туристов")
                current_count -= 1
            time.sleep(0.2)

        self._safe_click(select_btn, "Подтвержден выбор туристов")

        expected_text = f"{target_count} взрослых"
        self.wait.until(
            EC.text_to_be_present_in_element((By.CSS_SELECTOR, "div.TVTouristsFilter"), expected_text)
        )
        print(f"✅ {expected_text} установлены")

    def _select_operators(self, operators_config):
        """Выбор туроператоров - исправленная версия"""
        print("🏢 Выбор туроператоров...")

        # Сбрасываем список выбранных операторов
        self.selected_operators = []

        # Если не указаны операторы или все значения 0 - оставляем "Все туроператоры"
        if not operators_config or not any(operators_config.values()):
            print("✅ Оставлены все туроператоры по умолчанию")
            return

        # Открываем выбор операторов
        field = self._wait_for_element(By.CSS_SELECTOR, "div.TVOperatorListFilter",
                                       description="Поле выбора туроператоров")

        # Используем JavaScript для безопасного открытия
        self.driver.execute_script("arguments[0].click();", field)
        time.sleep(2)

        # Ждем появления списка операторов
        self._wait_for_element(By.CLASS_NAME, "TVOperatorsList", description="Список туроператоров")

        # Маппинг названий операторов для поиска
        operator_mapping = {
            'anex': 'Anex',
            'biblioglobus': 'Biblioglobus',
            'funsun': 'FUN&SUN (TUI)',
            'tourvisor': 'Tourvisor',
            'coral': 'Coral',
            'sunmar': 'Sunmar',
            'pegas': 'Pegas Touristik'
        }

        # Выбираем только тех операторов, которые указаны с значением 1
        for operator_key, should_select in operators_config.items():
            if should_select and operator_key in operator_mapping:
                operator_name = operator_mapping[operator_key]
                try:
                    operator_element = self.driver.find_element(
                        By.XPATH,
                        f"//div[contains(@class, 'TVCheckBox') and contains(text(), '{operator_name}') and not(contains(@class, 'TVDisabled'))]"
                    )

                    if "TVChecked" not in operator_element.get_attribute("class"):
                        print(f"🔧 Выбираем оператора: {operator_name}")
                        self.driver.execute_script("arguments[0].click();", operator_element)
                        self.selected_operators.append(operator_name)
                        time.sleep(0.5)
                    else:
                        print(f"✅ Оператор {operator_name} уже выбран")
                        self.selected_operators.append(operator_name)

                except Exception as e:
                    print(f"⚠️ Не удалось выбрать оператора {operator_name}: {e}")

        print(f"✅ Выбраны туроператоры: {', '.join(self.selected_operators) if self.selected_operators else 'нет'}")

        # Закрываем выбор операторов (кликаем в безопасное место)
        try:
            # Кликаем в заголовок страницы
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            # Кликаем в любое место вне выпадающего списка
            self.driver.execute_script("document.elementFromPoint(10, 10).click();")
            time.sleep(1)
        except:
            pass

    def _toggle_charter_checkbox(self, value):
        """Управление чекбоксом 'Только чартер'"""
        print(f"🔄 Управление галкой 'Только чартер': {value}")

        checkbox = self._wait_for_element(
            By.XPATH,
            "//div[contains(@class, 'TVCheckboxControl') and .//div[contains(text(), 'Только чартер')]]",
            description="Чекбокс 'Только чартер'"
        )

        is_checked = "TVChecked" in checkbox.get_attribute("class")

        if (value == 1 and not is_checked) or (value == 0 and is_checked):
            self._safe_click(checkbox, f"Галка {'установлена' if value == 1 else 'снята'}")
        else:
            state = "установлена" if is_checked else "снята"
            print(f"✅ Галка уже: {state}")

    def click_search_button(self):
        """Нажатие кнопки поиска"""
        print("🔍 Нажатие 'Найти туры'")

        search_btn = self._wait_for_element(
            By.XPATH,
            "//div[contains(@class, 'TVSearchButton') and contains(text(), 'Найти туры')]",
            description="Кнопка поиска туров"
        )
        self._safe_click(search_btn, "Запущен поиск туров")

    def _wait_for_search_completion(self):
        """Ожидание полного завершения поиска"""
        print("⏳ Ожидание завершения поиска...")
        start_time = time.time()

        # Ждем исчезновения основного прогресс-бара
        while time.time() - start_time < 120:
            try:
                # Основной прогресс-бар (глобальный)
                main_progress_bars = self.driver.find_elements(By.XPATH,
                                                               "//div[contains(@class, 'TVProgressBar') and not(ancestor::div[contains(@class, 'TVResultToolbar')])]")
                visible_main_progress = any(bar.is_displayed() for bar in main_progress_bars)

                # Прогресс-бар в тулбаре результатов (локальный)
                toolbar_progress = self.driver.find_elements(By.XPATH,
                                                             "//div[contains(@class, 'TVResultToolbarProgress')]")
                visible_toolbar_progress = any(bar.is_displayed() for bar in toolbar_progress)

                if not visible_main_progress and not visible_toolbar_progress:
                    print("✅ Все прогресс-бары исчезли")
                    return True

                # Если прошло больше 30 секунд и есть результаты - считаем завершенным
                if time.time() - start_time > 30:
                    try:
                        results = self.driver.find_elements(By.CSS_SELECTOR, ".TVResultItem")
                        if results:
                            print("✅ Есть результаты, поиск считаем завершенным")
                            return True
                    except:
                        pass

                time.sleep(2)

            except Exception as e:
                print(f"⚠️ Ошибка при проверке прогресс-баров: {e}")
                time.sleep(2)

        print("⚠️ Прогресс-бары не исчезли за 2 минуты, продолжаем...")
        return True

    def _get_all_operators_with_prices(self):
        """Получение списка всех туроператоров с минимальными ценами"""
        print("📊 Получение списка всех туроператоров с ценами...")

        operators_with_prices = []

        try:
            # Находим кнопку "Туроператоры" в тулбаре результатов
            operators_button = self._wait_for_element(
                By.XPATH,
                "//div[contains(@class, 'TVResultToolbarOperators') and contains(@class, 'TVResultToolbarButton')]",
                description="Кнопка 'Туроператоры'",
                timeout=10
            )

            # Кликаем на кнопку для открытия списка операторов
            self._safe_click(operators_button, "Открыт список туроператоров")
            time.sleep(2)

            # Ждем появления списка операторов
            operators_list = self._wait_for_element(
                By.CLASS_NAME,
                "TVOperatorFilterColumnBody",
                description="Список операторов с ценами",
                timeout=10
            )

            # Извлекаем все элементы операторов
            operator_items = operators_list.find_elements(
                By.CSS_SELECTOR,
                ".TVOperatorFilterItemControl"
            )

            print(f"🔍 Найдено операторов: {len(operator_items)}")

            for item in operator_items:
                try:
                    # Извлекаем название оператора
                    operator_name_element = item.find_element(By.CSS_SELECTOR, ".TVCheckBox")
                    operator_name = operator_name_element.text.strip()

                    # Извлекаем цену
                    price_element = item.find_element(By.CSS_SELECTOR, ".TVOperatorFilterItemPriceValue")
                    price = price_element.text.strip()

                    # Извлекаем валюту
                    currency_element = item.find_element(By.CSS_SELECTOR, ".TVOperatorFilterItemPriceCurrency")
                    currency = currency_element.text.strip()

                    if operator_name and price:
                        full_price = f"{price} {currency}"
                        operators_with_prices.append({
                            'operator': operator_name,
                            'min_price': full_price
                        })

                except Exception as e:
                    print(f"⚠️ Ошибка при извлечении данных оператора: {e}")
                    continue

            # Закрываем список операторов (кликаем вне его)
            try:
                self.driver.execute_script("document.elementFromPoint(100, 100).click();")
                time.sleep(1)
            except:
                pass

        except Exception as e:
            print(f"⚠️ Не удалось получить список операторов: {e}")

        return operators_with_prices

    def _extract_first_tour_info(self):
        """Извлечение информации о первом туре - ОБНОВЛЕННАЯ ВЕРСИЯ С НОВЫМ ШАБЛОНОМ"""
        print("🔍 Извлечение информации о первом туре...")

        try:
            # Ищем все элементы с турами
            tour_elements = self.driver.find_elements(By.CSS_SELECTOR, ".TVResultItem")

            if not tour_elements:
                print("❌ Туры не найдены")
                return None

            # Берем первый тур
            first_tour = tour_elements[0]

            # Извлекаем информацию только для случая одного оператора
            hotel_name = None
            price = "Не удалось извлечь цену"

            if len(self.selected_operators) == 1:
                # Для одного оператора извлекаем отель и цену
                try:
                    hotel_element = first_tour.find_element(By.CSS_SELECTOR, ".TVResultItemTitle a")
                    hotel_name = hotel_element.text.strip()
                except Exception as e:
                    print(f"⚠️ Ошибка при извлечении названия отеля: {e}")

                try:
                    price_element = first_tour.find_element(By.CSS_SELECTOR, ".TVResultItemPriceValue")
                    price_text = price_element.text.strip()
                    if price_text:
                        price = f"{price_text} ₽"
                except Exception as e:
                    print(f"⚠️ Ошибка при извлечении цены: {e}")

            # Получаем список всех операторов с ценами для случаев: все операторы или несколько операторов
            if not self.selected_operators or len(self.selected_operators) >= 2:
                self.all_operators_with_prices = self._get_all_operators_with_prices()

            # ВЫВОД РЕЗУЛЬТАТОВ ПО НОВОМУ ШАБЛОНУ
            print("=" * 60)
            print("🎯 РЕЗУЛЬТАТЫ ПОИСКА:")
            print("=" * 60)

            # ШАБЛОН 1: Для одного выбранного оператора
            if len(self.selected_operators) == 1:
                operators_text = self.selected_operators[0]
                print(f"🏢 Туроператор: {operators_text}")
                if hotel_name:
                    print(f"🏨 Отель: {hotel_name}")
                print(f"💰 Цена: {price}")

            # ШАБЛОН 2: Для всех операторов или нескольких операторов
            else:
                if self.selected_operators:
                    # Несколько выбранных операторов
                    operators_text = ", ".join(self.selected_operators)
                    print(f"🏢 Туроператоры: {operators_text}")
                else:
                    # Все операторы по умолчанию
                    print("🏢 Все туроператоры")

                # Выводим минимальные цены по операторам
                if self.all_operators_with_prices:
                    print("\n📊 Минимальные цены по туроператорам:")
                    for op in self.all_operators_with_prices:
                        print(f"   • {op['operator']}: {op['min_price']}")
                else:
                    print("   ❌ Не удалось получить цены по операторам")

            print("=" * 60)

            return {
                "hotel_name": hotel_name,
                "price": price,
                "operators": self.selected_operators if self.selected_operators else self.all_operators_with_prices
            }

        except Exception as e:
            print(f"❌ Ошибка при извлечении информации о туре: {e}")
            return None

    def verify_search_results(self):
        """Проверка результатов поиска"""
        print("\n🎯 Проверка результатов поиска")

        # Ждем завершения поиска
        search_completed = self._wait_for_search_completion()

        if search_completed:
            # Извлекаем информацию о первом туре
            tour_info = self._extract_first_tour_info()

            if tour_info:
                print("✅ Поиск завершен успешно, информация о первом туре получена")
                return True
            else:
                print("⚠️ Поиск завершен, но не удалось извлечь информацию о турах")
                return True
        else:
            print("❌ Поиск не завершился")
            return False

    def fill_search_form(self, **data):
        """Заполнение формы поиска"""
        methods = [
            (self._select_departure_city, data["departure_city"]),
            (self._select_destination_country, data["destination_country"]),
            (self._select_departure_dates, data["departure_dates"][0], data["departure_dates"][1]),
            (self._select_nights, data["nights"]),
            (self._select_tourists, data["tourists"]),
            (self._select_operators, data.get("operators", {})),
        ]

        for method, *args in methods:
            method(*args)

        self._toggle_charter_checkbox(data.get("charter", 1))
        print("✅ Форма полностью заполнена")

    def run_test(self, test_data):
        """Запуск теста"""
        start_time = time.time()
        success = False

        try:
            print("\n🚀 ЗАПУСК ТЕСТА\n" + "=" * 40)
            self.setup()
            self.open_tourvisor()
            self.fill_search_form(**test_data)
            self.click_search_button()
            success = self.verify_search_results()

        except Exception as e:
            print(f"\n💥 КРИТИЧЕСКАЯ ОШИБКА: {e}")
            success = False
        finally:
            duration = time.time() - start_time
            status = "🎉 УСПЕХ" if success else "💥 ПРОВАЛ"
            print(f"\n{status} — {duration:.1f} сек")

            if self.driver:
                self.driver.quit()

        return success


# Тестовые данные
test_data = {
    "departure_city": "Москва",
    "destination_country": "Турция",
    "departure_dates": ("26.05.2026", "28.05.2026"),
    "nights": "3-5",
    "tourists": "3 взрослых",
    "charter": 1,
    "operators": {
        "anex": 0,  # Anex - 1 выбрать, 0 не выбирать
        "biblioglobus": 0,  # Biblioglobus
        "funsun": 0,  # FUN&SUN (TUI)
        "tourvisor": 0,  # Tourvisor
        "coral": 0,  # Coral
        "sunmar": 0,  # Sunmar
        "pegas": 1  # Pegas Touristik
    }
}

if __name__ == "__main__":
    test = TourvisorSearchTest()
    test.run_test(test_data)