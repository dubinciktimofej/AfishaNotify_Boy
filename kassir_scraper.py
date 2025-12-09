import json
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Dict

import requests
from bs4 import BeautifulSoup


# ================== Настройки ==================

# Только Ростов
CITY_SLUGS = ["rnd"]

CITY_BASE_URL: Dict[str, str] = {
    "rnd": "https://rnd.kassir.ru",
}

# Паузы между запросами (в секундах)
SLEEP_BETWEEN_EVENTS = 1.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ================== Модели ==================

@dataclass
class TicketInfo:
    name: str
    price: Optional[int]


@dataclass
class EventInfo:
    city_slug: str
    title: str
    venue: str
    url: str
    tickets: List[TicketInfo]
    date_iso: Optional[str]  # дата события в формате YYYY-MM-DD или None


# ================== Вспомогательные функции ==================

def sleep(seconds: float) -> None:
    time.sleep(seconds)


def fetch_page(url: str) -> str:
    print(f"GET {url}")
    resp = requests.get(url, headers=HEADERS, timeout=40)
    resp.raise_for_status()
    return resp.text


def make_absolute_url(base: str, link: str) -> str:
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return base.rstrip("/") + "/" + link.lstrip("/")


# ================== 1. Список событий Ростова ==================

def fetch_all_city_events(city_slug: str) -> List[str]:
    """
    Получаем список URL концертов для Ростова.
    Берём все ссылки, где href содержит '/koncert/'.
    """
    base = CITY_BASE_URL[city_slug]

    list_url = f"{base}/bilety-na-koncert"
    html = fetch_page(list_url)
    soup = BeautifulSoup(html, "html.parser")

    event_urls = set()

    # Ищем ссылки вида /koncert/...
    for a in soup.select('a[href*="/koncert/"]'):
        href = a.get("href")
        if not href:
            continue
        url = make_absolute_url(base, href)
        event_urls.add(url)

    print(f"Найдено событий: {len(event_urls)}")
    return list(event_urls)


# ================== 2. Разбор страницы одного концерта ==================

def parse_event_page(html: str, url: str, city_slug: str) -> EventInfo:
    soup = BeautifulSoup(html, "html.parser")

    # ----- Название концерта -----
    title_el = soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else "Без названия"

    # ----- Площадка -----
    venue = "Неизвестная площадка"
    venue_el = soup.select_one("a.truncate")
    if venue_el:
        txt = venue_el.get_text(strip=True)
        if txt:
            venue = txt

    tickets: List[TicketInfo] = []

    # ----- Минимальная цена из блока "2 000 – 7 500" -----
    min_price_value: Optional[int] = None
    price_block = soup.select_one("div.flex.items-center.leading-snug")
    if price_block:
        price_text = price_block.get_text(" ", strip=True)
        m = re.search(r"\d[\d\s]*", price_text)
        if m:
            digits = m.group(0).replace(" ", "")
            try:
                min_price_value = int(digits)
            except ValueError:
                min_price_value = None

    if min_price_value is not None:
        tickets.append(TicketInfo(name="Входной билет", price=min_price_value))

    # ----- Дата события -----
    date_iso: Optional[str] = None

    # 1) Пытаемся взять из URL вида ..._2026-02-16
    m = re.search(r"\d{4}-\d{2}-\d{2}", url)
    if m:
        date_iso = m.group(0)
    else:
        # 2) Если в URL нет даты — ищем в тексте страницы "12 июня 2026"
        full_text = soup.get_text(" ", strip=True)

        # русские месяцы в родительном падеже
        month_map = {
            "января": "01",
            "февраля": "02",
            "марта": "03",
            "апреля": "04",
            "мая": "05",
            "июня": "06",
            "июля": "07",
            "августа": "08",
            "сентября": "09",
            "октября": "10",
            "ноября": "11",
            "декабря": "12",
        }

        m2 = re.search(
            r"(\d{1,2})\s+("
            r"января|февраля|марта|апреля|мая|июня|июля|августа|"
            r"сентября|октября|ноября|декабря"
            r")\s+(\d{4})",
            full_text,
            flags=re.IGNORECASE,
        )

        if m2:
            day_str, month_word, year_str = m2.groups()
            day = int(day_str)
            month_word = month_word.lower()
            month = month_map.get(month_word)
            if month:
                # собираем YYYY-MM-DD
                date_iso = f"{year_str}-{month}-{day:02d}"

    return EventInfo(
        city_slug=city_slug,
        title=title,
        venue=venue,
        url=url,
        tickets=tickets,
        date_iso=date_iso,
    )



# ================== 3. Общий запуск ==================

def scrape_kassir_all_cities() -> List[EventInfo]:
    results: List[EventInfo] = []

    for city_slug in CITY_SLUGS:
        print(f"\n=== Город: {city_slug} ===")

        try:
            event_urls = fetch_all_city_events(city_slug)
        except Exception as e:
            print(f"Ошибка при загрузке списка событий для {city_slug}: {e}")
            continue

        for url in event_urls:
            try:
                html = fetch_page(url)
                event = parse_event_page(html, url, city_slug)
                results.append(event)
                print(f"OK: {event.title} @ {event.venue}")
            except Exception as e:
                print(f"Ошибка при парсинге события {url}: {e}")

            sleep(SLEEP_BETWEEN_EVENTS)

    return results


# ================== 4. Точка входа ==================

if __name__ == "__main__":
    all_events = scrape_kassir_all_cities()
    print(f"\nВсего собрано событий: {len(all_events)}")

    data = [
        {
            "city_slug": e.city_slug,
            "title": e.title,
            "venue": e.venue,
            "url": e.url,
            "date_iso": e.date_iso,
            "tickets": [
                {"name": t.name, "price": t.price}
                for t in e.tickets
            ],
        }
        for e in all_events
    ]

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Сохранено в events.json")
