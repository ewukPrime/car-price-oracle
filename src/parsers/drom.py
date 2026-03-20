import httpx
from bs4 import BeautifulSoup
import time
from loguru import logger
import random
from pathlib import Path
import re
import csv
from src.models import CarItem
from datetime import datetime, timedelta
import dateparser


class DromParser:
    def __init__(self):
        data_dir = Path('data/logs')
        logger.add(data_dir / 'parsing.log', rotation='1 MB', level='DEBUG', encoding='utf-8')

        logger.info('Сессия httpx начата')

        self.client = httpx.Client(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}, timeout=10.0, follow_redirects=True)


    def get_html(self, url):
        pause = random.uniform(1, 2)
        logger.debug(f"Запрос к {url} с паузой {pause:.2f} сек.")
        time.sleep(pause)

        try:
            resp = self.client.get(url)
            if 'https://auto.drom.ru/spec/' in str(resp.url): return None
            resp.raise_for_status()
            return resp.text

        except Exception as e:
            logger.error(f"Ошибка при запросе к {url}: {e}")
            return None



    def _parse_base_info(self, card, car_data):
        title_link = card.find('a', attrs={'data-ftid': 'bull_title'})

        try:
                img_cont = card.find('img')
                img_url = img_cont.get('srcset').split(' 1x')[0] 
                car_data.update({'img_url': img_url})

                inf1 = img_cont.get('alt').split(',')
                match = re.search(rf'(.*?) ({re.escape(car_data['brand'])}) (.*?) (\d{{4}})', inf1[0])

                car_data.update({
                    'city': inf1[2].strip(),
                    'price': inf1[1].strip().split(' ')[0],
                    'body_type': match.group(1),
                    'model': match.group(3),
                    'year': match.group(4)
                })
        except:
                self._parse_base_info2(card, car_data, title_link)
        
        car_data['url'] = title_link.get('href')
        car_data['spec'] = subtitle_data.text if (subtitle_data := card.find('div', attrs={'data-ftid': 'bull_subtitle'})) else None

    def _parse_base_info2(self, card, car_data, title_link):
        title_data = title_link.find('h3').text.split(',')

        car_data.update({
        'city': card.find('span', attrs={'data-ftid': 'bull_location'}).text,
        'price': card.find('span', attrs={'data-ftid': 'bull_price'}).text.replace('\xa0', ''),
        'body_type': None,
        'model': title_data[0].replace(car_data['brand']+' ', ''),
        'year': title_data[1]
        })

    def _parse_tech_info(self, card, car_data):
        main_link = card.find('div', attrs={'data-ftid': 'component_inline-bull-description'})
        descriptions = main_link.find_all('span', attrs={'data-ftid': 'bull_description-item'})

        for i in range(len(descriptions)):
                description = descriptions[i].text.replace(',', '')

                if 'л.с.' in descriptions[i].text:
                    if '(' in descriptions[i].text:
                        car_data['eng_vol'] = description.split()[0]
                        car_data['eng_hp'] = description.split('(')[1].split()[0]
                    else:
                        car_data['eng_vol'] = None
                        car_data['eng_hp'] = description.split()[0]

                elif description in ['бензин', 'дизель', "электро", "гибрид", "ГБО"]:
                    car_data['fuel'] = description
                elif description in ["автомат", "АКПП", "робот", "вариатор", "механика"]:
                    car_data['gearbox'] = description
                elif description in ["4WD", "передний", "задний"]:
                    car_data['drive'] = description
                elif 'км' in description:
                    car_data['mileage'] = descriptions[i].text[:-3].replace(' ', '')



    def _parse_status(self, card, car_data):
        car_data['is_owner'] = True if card.find('div', attrs={'data-ftid': 'bull_label_owner'}) else False
        car_data['needs_repair'] = True if card.find('div', attrs={'data-ftid': 'bull_label_broken'}) else False
        car_data['has_issues'] = True if card.find('div', attrs={'data-ftid': 'bull_label_nodocs'}) else False
        car_data['is_active'] = False if card.find('div', attrs={'data-ftid': 'bull_sold'}) else True



    def _parse_date_info(self, card, car_data):
        car_data['parse_date'] = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now()
        
        raw_date = card.find('div', attrs={'data-ftid': 'bull_date'}).text

        if 'минут' in raw_date:
            mins = 1 if raw_date.split()[0] == 'минуту' else int(raw_date.split()[0])
            car_data['posted_date'] = (now - timedelta(minutes=mins)).strftime('%Y-%m-%d')
        elif 'час' in raw_date:
            hours = int(raw_date.split()[0])
            car_data['posted_date'] = (now - timedelta(hours=hours)).strftime('%Y-%m-%d')
        else:
            car_data['posted_date'] = dateparser.parse(raw_date, languages=['ru'], settings={'PREFER_DATES_FROM': 'past'}).strftime('%Y-%m-%d')



    def parse_html(self, url, brand) -> list[dict]:
        html = self.get_html(url)
        cars = []
        if not html: return []
        
        soup = BeautifulSoup(html, 'html.parser')
        catalog = soup.find('div', attrs={'data-bulletin-list': 'true'})

        if catalog:
            cards = catalog.find_all('div', attrs={'data-ftid': 'bulls-list_bull'})
            logger.success(f"Найден католог и в нём {len(cards)} карточек")
        else:
            logger.warning("Нету объявлений по данной моделе")
            return []
        
        for i, card in enumerate(cards, 1):
            try:
                car_data = {'brand': brand}
                self._parse_base_info(card, car_data)
                self._parse_tech_info(card, car_data)
                self._parse_status(card, car_data)
                self._parse_date_info(card, car_data)

                if all(item not in car_data['url'] for item in ['loader', 'excavator']):
                    car = CarItem(**car_data)
                    cars += [car]

            except Exception as e:
                logger.error(f"Ошибка в карточке №{i}: {e}")

        return cars



    def save_to_csv(self, cars: list, brand_url: str):
        if not cars:
            logger.warning("Список машин пуст.")
            return
        
        try:
            file_name = brand_url
            file_path = Path(f"data/raw/{file_name}.csv")

            field = list(CarItem.model_fields.keys())
            file_exists = file_path.exists() and file_path.stat().st_size > 0

            with open(file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=field)

                if not file_exists:
                    writer.writeheader()

                for car in cars:
                    writer.writerow(car.model_dump())

        except Exception as e:
            logger.error(f"Ошибка при записи данных csv-таблицу: {e}")



    def get_brands(self) -> dict[str]:
        url = "https://www.drom.ru/catalog/"
        html = self.get_html(url)
        if not html: return []

        try:
            soup = BeautifulSoup(html, 'html.parser')
            brand_list = soup.find('div', attrs={'data-ftid': 'component_cars-list'})
            
            raw_popular_brands = brand_list.find_all('a', attrs={'data-ftid': 'component_cars-list-item_hidden-link'})
            if not raw_popular_brands: logger.error('Ошбка')
            pbs = {pb.get_text(): pb.get('href').split('/')[-2] for pb in raw_popular_brands}

            unpopular_brand_list = brand_list.find('noscript')
            raw_unpopular_brands = unpopular_brand_list.find_all('a', href=True)
            ubs = {ub.get_text(): ub.get('href').split('/')[-2] for ub in raw_unpopular_brands}
            
            return dict(sorted((pbs | ubs).items()))
        
        except Exception as e:
            logger.error(f"Ошибка при анализе брендов для {url}: {e}")



    def get_splited_brands(self):
        brands = self.get_brands()
        splited_brands = {}
        found = False

        for k, v in brands.items():
            if found:
                splited_brands[k] = v
            if k == 'Волга':
                found = True
        return splited_brands



    def get_models_url(self, brand_url) -> list[str]:
        url = f"https://www.drom.ru/catalog/{brand_url}/"
        html = self.get_html(url)
        if not html: return []

        try:
            soup = BeautifulSoup(html, 'html.parser')
            model_list = soup.find('div', attrs={'data-ftid': 'component_cars-list'})
            raw_models = model_list.find_all('a', attrs={'data-ga-stats-name': 'model_from_list'})
            models = [model.get('href').split('/')[-2] for model in raw_models]
            
            return models
        
        except Exception as e:
            logger.error(f"Ошибка при анализе моделей для {url}: {e}")
            return []



    def get_listings_count(self, brand_url: str, model_url='', start=None, end=None, min_p=0, max_p=1_000_000_000) -> int:
        url = f"https://auto.drom.ru/{brand_url}/{model_url}/?minyear={start}&maxyear={end}&minprice={min_p}&maxprice={max_p}"
        html = self.get_html(url)
        if not html: return 0

        try:
            soup = BeautifulSoup(html, 'html.parser')
            up_panel = soup.find('div', attrs={'data-ga-stats-name': 'bulls_counter'})
            if not up_panel: return 0
            

            if raw_total_count := up_panel.find('a', attrs={'data-ga-stats-name': 'tabs_group_by_models'}):
                raw_total_count = raw_total_count.text
            else:
                raw_total_count = up_panel.text
            

            total_count = int(''.join(filter(str.isdigit, raw_total_count)))

            return total_count
        
        except Exception as e:
            logger.error(f"Ошибка при получении количества для {url}: {e}")


    def split_by_year(self, brand_url: str, model_url: str, start=1940, end=2026, min_p=0, max_p=1_000_000_000) -> list[list[int]]:
        total = self.get_listings_count(brand_url, model_url, start, end)

        if total <= 2000:
            return [[start, end, total, None, None]]
        
        if end == start:
            return self.split_by_price(brand_url, model_url, start)
        
        mid = (start + end) // 2

        left_ranges = self.split_by_year(brand_url, model_url, start, mid)
        right_ranges = self.split_by_year(brand_url, model_url, mid+1, end)

        return left_ranges + right_ranges



    def _get_first_car_price(self, url: str) -> int:
        logger.warning(f"По ссылке: {url} - более 2000 машин")

        html = self.get_html(url)
        if not html: return 1_500_000

        soup = BeautifulSoup(html, 'html.parser')
        raw_price = soup.find('span', attrs={'data-ftid': 'bull_price'})
        if raw_price: return int(''.join(filter(str.isdigit, raw_price.text)))
        return 1_500_000



    def split_by_price(self, brand_url: str, model_url: str, year: int, min_p=0, max_p=1_000_000_000) -> list[list[int]]:
        url = f"https://auto.drom.ru/{brand_url}/{model_url}/?minyear={year}&maxyear={year}&minprice={min_p}&maxprice={max_p}"
        total = self.get_listings_count(brand_url, model_url, year, year, min_p, max_p)

        if total <= 2000 or (max_p - min_p) < 1000:
            return [[year, year, total, min_p, max_p]]
        
        price_first_car = self._get_first_car_price(url)

        if price_first_car <= min_p or price_first_car >= max_p:
            price_first_car = (min_p + max_p) // 2

        return self.split_by_price(brand_url, model_url, year, min_p, price_first_car) + self.split_by_price(brand_url, model_url, year, price_first_car + 1, max_p)




    def parse_one_brand(self, brand: str, brand_url: str):
        model_urls = self.get_models_url(brand_url)

        for model_url in model_urls:
            ranges = self.split_by_year(brand_url, model_url)
            for start, end, total, min_p, max_p in ranges:
                pages = (total + 19) // 20

                for i in range(1, min(pages, 100) + 1):
                    page_url = '' if i == 1 else f'page{i}/'
                    price_filter = f"&minprice={min_p}&maxprice={max_p}" if min_p != None else ''
                    url = f"https://auto.drom.ru/{brand_url}/{model_url}/{page_url}?minyear={start}&maxyear={end}{price_filter}"
                    cars = p.parse_html(url, brand)
                    self.save_to_csv(cars, brand_url)

        logger.success(f"Модель: {model_url} - полностью запаршена")



    def parse_all_brands(self):
        all_brands = self.get_splited_brands()
        for brand, brand_url in all_brands.items():
            self.parse_one_brand(brand, brand_url)
            logger.success(f"Марка: {brand} - полностью запаршена")



    def fixed_card(self):
        all_errors = []
        folder_logs_path = Path("error_logs/")
        
        for file_log_path in folder_logs_path.glob('*.log'):
            with open(file_log_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    if 'error' in line.lower():
                        all_errors.append(lines[i-2].split(' ')[-5])
        return [item if 'https://auto.drom.ru' in item else None  for item in all_errors]

    

    def count_card(self) -> int:
        count = 0
        folder_data_path = Path("data/raw/")

        for file_data_path in folder_data_path.glob("*.csv"):
            with open(file_data_path, 'r',  encoding='utf-8-sig') as f:
                lines = f.readlines()
                count += len(lines) - 1
        return count



if __name__ == '__main__':
    p = DromParser()
    # p.parse_all_brands()
    logger.success(p.count_card())
    # logger.debug(p.parse_html('https://auto.drom.ru/gaz/avrora/', 'ГАЗ'))
    # logger.success(p.get_splited_brands())