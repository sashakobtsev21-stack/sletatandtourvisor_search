import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class TourvisorSearchTest:
    def __init__(self):
        self.driver = None
        self.wait = None

    def setup(self):
        self.driver = webdriver.Chrome()
        self.driver.maximize_window()
        self.wait = WebDriverWait(self.driver, 15)

    def open_tourvisor(self):
        self.driver.get("https://tourvisor.ru/search.php")
        print("✅ Сайт Tourvisor открыт")

    # ================================
    # === МЕТОДЫ ВЫБОРА ПАРАМЕТРОВ ===
    # ================================

    def _select_departure_city(self, city):
        print(f"📍 Город вылета: {city}")
        time.sleep(1)
        field = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.TVDepartureFilter")))
        field.click()
        time.sleep(1)
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "TVDepartureTableBody")))
        option = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//div[contains(@class, 'TVDepartureTableBody')]//div[contains(text(), '{city}')][1]")
            )
        )
        option.click()
        print(f"✅ {city} выбран")

    def _select_destination_country(self, country):
        print(f"🌍 Страна: {country}")
        time.sleep(1)
        field = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.TVCountryFilter")))
        field.click()
        time.sleep(1)
        self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class, 'TVCountryAirportList') and not(contains(@class, 'TVHide'))]")
            )
        )
        option = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//div[contains(@class, 'TVCountryAirportList')]//div[contains(@class, 'TVComplexListItem') and contains(text(), '{country}')][1]")
            )
        )
        option.click()
        print(f"✅ {country} выбрана")

    def _scroll_to_month(self, target_month_name, target_year):
        print(f"🗓️ Прокрутка календаря к: {target_month_name} {target_year}")
        for attempt in range(15):
            try:
                month_el = self.driver.find_element(
                    By.XPATH, "//div[contains(@class, 'TVCalendarTitleControlMonth')]"
                )
                year_el = self.driver.find_element(
                    By.XPATH, "//div[contains(@class, 'TVCalendarTitleControlYear')]"
                )
                month_text = month_el.text.strip()
                year_text = year_el.text.strip()

                # ✅ Сравнение БЕЗ учёта регистра
                if month_text.upper() == target_month_name.upper() and year_text == str(target_year):
                    print(f"✅ Найден месяц: {month_text} {year_text}")
                    return

                print(f"🔍 Текущий: '{month_text}' ({len(month_text)}), '{year_text}'")

            except Exception as e:
                print(f"⚠️ Ошибка (попытка {attempt + 1}): {e}")

            try:
                next_btn = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH,
                                                "//div[contains(@class, 'TVCalendarSliderViewRightButton') and not(contains(@class, 'TVDisabled'))]"))
                )
                next_btn.click()
                time.sleep(0.7)
            except Exception as e:
                print(f"⚠️ Прокрутка завершена или кнопка заблокирована (попытка {attempt + 1})")
                break

        raise RuntimeError(f"❌ Месяц {target_month_name} {target_year} не найден")

    def _click_calendar_day(self, date_obj):
        day = date_obj.day
        time.sleep(1)
        el = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, f"//t-td[@data-value='{day}' and not(contains(@class, 'TVCalendarDisabledCell'))]"))
        )
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        el.click()

    def _select_departure_dates(self, dep_str, ret_str=None):
        print(f"🛫 Даты: {dep_str} → {ret_str or '—'}")
        time.sleep(1)
        field = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.TVFlyDatesFilter")))
        field.click()
        time.sleep(1)

        # ✅ Ждём, пока календарь ПОЛНОСТЬЮ загрузится
        self.wait.until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'TVFlyDatesSelectTooltip')]"))
        )

        MONTHS_RU = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }

        dep = datetime.strptime(dep_str, "%d.%m.%Y")
        self._scroll_to_month(MONTHS_RU[dep.month], dep.year)
        self._click_calendar_day(dep)

        if ret_str:
            ret = datetime.strptime(ret_str, "%d.%m.%Y")
            self._scroll_to_month(MONTHS_RU[ret.month], ret.year)
            self._click_calendar_day(ret)
            time.sleep(0.5)

        try:
            btn = self.driver.find_element(
                By.XPATH, "//div[contains(@class, 'TVFlyDatesSelectTooltipFooter')]//div[contains(text(), 'Выбрать')]"
            )
            time.sleep(1)
            btn.click()
        except:
            pass

        # Ждём закрытия календаря
        self.wait.until(
            EC.invisibility_of_element_located((By.XPATH, "//div[contains(@class, 'TVFlyDatesSelectTooltip')]"))
        )
        print("✅ Даты выбраны")

    def _select_nights(self, nights_range):
        print(f"🏨 Ночи: {nights_range}")
        time.sleep(1)
        field = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVNightsFilter')]")))
        field.click()
        time.sleep(1)
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "TVRangeTableContainer")))

        parts = nights_range.split("-")
        min_n, max_n = int(parts[0]), int(parts[1])

        # ✅ Клик по ячейке (TVRangeTableCell), а не по label
        min_cell = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//div[contains(@class, 'TVRangeTableCell') and .//div[contains(@class, 'TVRangeCellLabel') and text()='{min_n}']]")
            )
        )
        time.sleep(1)
        min_cell.click()
        time.sleep(0.2)

        max_cell = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, f"//div[contains(@class, 'TVRangeTableCell') and .//div[contains(@class, 'TVRangeCellLabel') and text()='{max_n}']]")
            )
        )
        time.sleep(1)
        max_cell.click()
        time.sleep(0.5)

        print(f"✅ Ночи {nights_range} выбраны")

    def _select_tourists(self, tourists_str):
        print(f"👥 Туристы: {tourists_str}")
        time.sleep(1)
        field = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div.TVTouristsFilter")))
        field.click()
        time.sleep(1)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'TVTouristsSelectTooltip')]")))

        match = re.search(r'(\d+)\s*взросл', tourists_str)
        if not match:
            raise ValueError(f"Не удалось извлечь число из: {tourists_str}")
        target = int(match.group(1))

        current_el = self.driver.find_element(
            By.XPATH, "//div[contains(@class, 'TVTouristCount') and contains(@class, 'TVTouristAll')]"
        )
        current = int(re.search(r'\d+', current_el.text).group())

        plus = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVTouristActionPlus')]")))
        minus = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVTouristActionMinus')]")))
        select_btn = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVButtonControl') and contains(text(), 'Выбрать')]"))
        )

        while current < target:
            time.sleep(1)
            plus.click(); current += 1; time.sleep(0.15)
        while current > target:
            time.sleep(1)
            minus.click(); current -= 1; time.sleep(0.15)

        time.sleep(1)
        select_btn.click()

        expected = f"{target} взрослых"
        self.wait.until(
            EC.text_to_be_present_in_element((By.CSS_SELECTOR, "div.TVTouristsFilter"), expected)
        )
        print(f"✅ {expected} установлены")

    # ✅ ГАЛКА «ТОЛЬКО ЧАРТЕР» — по TVChecked
    def _toggle_charter_checkbox(self, value):
        print(f"🔄 Управление галкой 'Только чартер': {value}")
        time.sleep(1)
        try:
            checkbox = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVCheckboxControl') and .//div[contains(text(), 'Только чартер')]]"))
            )
            is_checked = "TVChecked" in checkbox.get_attribute("class")

            if value == 1 and not is_checked:
                time.sleep(1)
                checkbox.click()
                print("✅ Галка поставлена")
            elif value == 0 and is_checked:
                time.sleep(1)
                checkbox.click()
                print("✅ Галка снята")
            else:
                state = "стоит" if is_checked else "снята"
                print(f"✅ Галка уже: {state}")

        except Exception as e:
            raise RuntimeError(f"❌ Ошибка с галкой 'Только чартер': {e}")

    def click_search_button(self):
        print("🔍 Нажатие 'Найти туры'")
        time.sleep(1)
        btn = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'TVSearchButton') and contains(text(), 'Найти туры')]"))
        )
        btn.click()

    def verify_search_results(self):
        """✅ Ждём полной загрузки: TVProgressBar исчез → туры или 'не найдено'"""
        print("⏳ Ожидание завершения поиска...")

        try:
            # Ждём исчезновения прогресс-бара
            WebDriverWait(self.driver, 30).until(
                EC.invisibility_of_element_located((By.XPATH, "//div[contains(@class, 'TVProgressBar')]"))
            )
            print("✅ Прогресс-бар исчез")

            # Есть ли туры?
            try:
                self.driver.find_element(By.CSS_SELECTOR, ".TVResultItem")
                print("✅ Туры найдены")
                return True
            except:
                pass

            # Или сообщение "не найдено"?
            try:
                self.driver.find_element(By.XPATH,
                    "//div[contains(text(), 'не найдены') or contains(text(), 'Ничего не найдено')]"
                )
                print("✅ 0 туров — поиск завершён")
                return True
            except:
                pass

            raise Exception("Ни туров, ни сообщения")

        except Exception as e:
            self.driver.save_screenshot("search_error.png")
            print(f"❌ Ошибка при проверке результатов: {e}")
            return False

    # ===================
    # === ОСНОВНОЙ СЦЕНАРИЙ ===
    # ===================

    def fill_search_form(self, **data):
        self._select_departure_city(data["departure_city"])
        self._select_destination_country(data["destination_country"])
        self._select_departure_dates(*data["departure_dates"])
        self._select_nights(data["nights"])
        self._select_tourists(data["tourists"])
        self._toggle_charter_checkbox(data.get("charter", 1))
        print("✅ Форма готова")

    def run_test(self, test_data):
        start = time.time()
        try:
            print("\n🚀 ЗАПУСК ТЕСТА\n" + "="*40)
            self.setup()
            self.open_tourvisor()
            self.fill_search_form(**test_data)
            self.click_search_button()
            success = self.verify_search_results()
            duration = time.time() - start
            print(f"\n{'🎉 УСПЕХ' if success else '⚠️ ЧАСТИЧНО'} — {duration:.1f} сек")
            return success
        except Exception as e:
            print(f"\n💥 КРИТИЧЕСКАЯ ОШИБКА: {e}")
            return False
        finally:
            if self.driver:
                self.driver.quit()


# ===================
# === ТЕСТОВЫЕ ДАННЫЕ ===
# ===================

test_data = {
    "departure_city": "Москва",
    "destination_country": "Китай",
    "departure_dates": ("26.10.2026", "28.10.2026"),
    "nights": "2-5",
    "tourists": "3 взрослых",
    "charter": 1  # 1 — галка стоит, 0 — снята
}


# ===================
# === ЗАПУСК ===
# ===================

if __name__ == "__main__":
    test = TourvisorSearchTest()
    test.run_test(test_data)