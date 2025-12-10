"""
This module contains the class to scrape articles from the "Welt" newspaper (https://www.welt.de/).
The class inherits from the NewspaperManager class and needs an implementation of the abstract methods.
With a similar implementation, it is possible to scrape articles from other news websites.
"""
import re
import datetime as dt

import requests
from bs4 import BeautifulSoup
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from selenium.common.exceptions import NoSuchElementException

from ..utils.logger import log
from ..scraper import NewspaperManager


class DeWelt(NewspaperManager):
    """
    This class inherits from the NewspaperManager class and implements the newspaper specific methods.
    These methods are:
        - _get_articles_by_date: Index articles published on a given day and return the urls and publication dates.
        - _soup_get_html: Determine if an article is premium content and scrape the html if it is not. Uses
            beautifulsoup.
        - _selenium_login: Login to the newspaper website to allow scraping of premium content after the login. Uses
            selenium.
    """

    def __init__(self, db_file: str = 'articles.db'):
        super().__init__(db_file)

    def _get_articles_by_date(self, day: dt.date):
        """
        Index articles published on a given day and return the urls and publication dates.

        Args:
            day (dt.date): Date of the articles to index.

        Returns:
            [str]: List of urls of the articles published on the given day.
            [dt.datetime]: List of publication dates of the articles published on the given day. Needs timezone
                information.
        """
        # print(day.strftime())
        url = f'https://www.welt.de/schlagzeilen/nachrichten-vom-{day.strftime("%d-%m-%Y")}.html'
        # print(url)
        html = self._request(url)
        

        # if html is None:
        #     return [], []

        soup = BeautifulSoup(html, "html.parser")
        # print(soup)

        ###### OLD
        # # Get list of article elements
        # articles = soup.find_all("article", {"class": "c-teaser c-teaser--archive"})

        # # Get articles urls
        # urls = ['https://www.welt.de' + article.find('h4').find('a')['href'] for article in articles]

        # # Get articles publication dates
        # time_regex = re.compile(r'\d{2}\.\d{2}\.\d{4}\s\|\s\d{2}:\d{2}')
        # pub_dates = [pd.to_datetime(f'{article.find(string=time_regex)}', format='%d.%m.%Y | %H:%M')
        #              for article in articles]
        # # Add timezone Europe/Berlin to pub_dates
        # pub_dates = [pub_date.tz_localize('UTC') for pub_date in pub_dates]


        ##### NEW
        # articles = soup.select('li.c-teaser__item article')
        # articles = soup.select('is-link c-teaser__headline-link is-teaser-link')
        # articles = soup.find_all(article, _class='c-teaser c-teaser--archive')
        articles = soup.find_all("article", {"class": "c-teaser c-teaser--archive"})

        # print(articles)

        if not articles:
            print(f"[INFO] No articles found for {day.strftime('%d-%m-%Y')}")
            return ([], [])   # <---- still return two empty lists

        # Get article URLs
        # urls = ['https://www.welt.de' + art.find('a')['href'] for art in articles if art.find('a')]
        urls = [('https://www.welt.de' + a['href'] if not a['href'].startswith('http') else a['href']) for a in soup.select('a.c-teaser__headline-link')]
        # print(urls)

        # Get publication dates (prefer datetime attribute if present)    
        pub_dates = []
        for art in articles:
            time_tag = art.find('span', {'class':'c-teaser__date'})
            text = None
            if time_tag:
                # Priority: try machine-readable datetime attribute
                if time_tag.has_attr('datetime'):
                    dt = pd.to_datetime(time_tag['datetime'], errors='coerce', utc=True)
                    pub_dates.append(dt)
                    continue
                else:
                    text = time_tag.get_text(strip=True)
            else:
                # Fallback: sometimes date is not in <time> but in plain text
                text = art.get_text(" ", strip=True)
            
            if not text:
                pub_dates.append(pd.NaT)
                continue

            # Normalize separators
            text = text.replace('Uhr', '').replace(',', '').strip()

            # Try multiple known formats
            parsed = pd.NaT
            for fmt in ('%d.%m.%Y | %H:%M', '%d.%m.%Y %H:%M', '%B %d %Y | %I:%M %p', '%B %d %Y %I:%M %p'):
                try:
                    parsed = pd.to_datetime(text, format=fmt, utc=True)
                    break
                except Exception:
                    continue

            # Last resort: let pandas infer (slow but flexible)
            if pd.isna(parsed):
                parsed = pd.to_datetime(text, errors='coerce', utc=True)

            pub_dates.append(parsed)

        df = pd.DataFrame({"url": urls, "pub_date": pub_dates})
        df = df.drop_duplicates(subset="url").reset_index(drop=True)

        # ---- Ensure timezone ----
        df["pub_date"] = pd.to_datetime(df["pub_date"], errors="coerce")

        return df["url"].tolist(), df["pub_date"].tolist()        
        # return urls, pub_dates

    def _soup_get_html(self, url: str):
        """
        For a single article, determine if it is premium content and scrape the html if it is not.

        Args:
            url (str): Url of the article to scrape.

        Returns:
            str: Html of the article. If the article is premium content, None is returned.
            bool: True if the article is premium content, False otherwise.
        """
        html = self._request(url)
        if not html:
            return None, False
        soup = BeautifulSoup(html, "html.parser")
        # print(url)
        try:
            premium_icon = soup.find("header", {"class": "r-header r-header--default"}). \
                find('a', {"class": "is-link c-article-header__premium"})
            return html, not bool(premium_icon)
        except AttributeError:
            log.warning(f'Could not identify if article is premium: {url}.')
            return None, False

    def _selenium_login(self, username: str, password: str):
        """
        Using selenium, login to the newspaper website to allow scraping of premium content after the login.
        Args:
            username (str): Username to login to the newspaper website.
            password (str): Password to login to the newspaper website.

        Returns:
            bool: True if login was successful, False otherwise.
        """
        # Login
        self.selenium_driver.get('https://lo.la.welt.de/login')
        WebDriverWait(self.selenium_driver, 10).until(
            ec.presence_of_element_located((By.NAME, 'username')))
        self.selenium_driver.find_element(By.NAME, 'username').send_keys(username)
        self.selenium_driver.find_element(By.NAME, 'password').send_keys(password)
        self.selenium_driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()

        # Go to main page and accept cookies
        self.selenium_driver.get('https://www.welt.de/')
        privacy_frame = WebDriverWait(self.selenium_driver, 10).until(
            ec.presence_of_element_located((By.XPATH, '//iframe[@title="SP Consent Message"]'))
        )
        self.selenium_driver.switch_to.frame(privacy_frame)
        WebDriverWait(self.selenium_driver, 10).until(
            ec.presence_of_element_located((By.CSS_SELECTOR, 'button[title="Alle akzeptieren"]')))
        self.selenium_driver.find_element(By.CSS_SELECTOR, 'button[title="Alle akzeptieren"]').click()

        # Check if login was successful
        try:
            self.selenium_driver.get('https://www.welt.de/meinewelt/')
            WebDriverWait(self.selenium_driver, 10).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, 'div[data-component-name="home"]')))
            _elem = self.selenium_driver.find_element(By.CSS_SELECTOR, 'div[data-component-name="home"]')
            WebDriverWait(_elem, 10).until(ec.presence_of_element_located((By.CSS_SELECTOR, 'div[name="greeting"]')))
            self.selenium_driver.get('https://www.welt.de')
            log.info('Logged in to Welt Plus.')
            return True
        except NoSuchElementException:
            log.warning('Login to Welt Plus failed.')
            return False
