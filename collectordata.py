import requests
import pandas as pd
import json
import time
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Dict, Optional, Set
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse, quote
import csv
from datetime import datetime, timedelta
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import signal
import sys
from dataclasses import dataclass, asdict
import schedule
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import scholarly
from pylatexenc.latex2text import LatexNodes2Text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('journal_collector.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class JournalEntry:
    
    title: str = ""
    abstract: str = ""
    authors: List[str] = None
    keywords: List[str] = None
    journal_name: str = ""
    year: int = 0
    doi: str = ""
    url: str = ""
    pdf_url: str = ""
    citations: int = 0
    pages: str = ""
    volume: str = ""
    issue: str = ""
    publisher: str = ""
    affiliation: str = ""
    subject_area: str = ""
    language: str = "id"
    source: str = ""
    collected_date: str = ""
    full_text: str = ""
    reference_list: List[str] = None
    
    def __post_init__(self):
        if self.authors is None:
            self.authors = []
        if self.keywords is None:
            self.keywords = []
        if self.reference_list is None:
            self.reference_list = []
        if not self.collected_date:
            self.collected_date = datetime.now().isoformat()

class AdvancedJournalCollector:
    
    def __init__(self, output_dir: str = "journal_data_collection"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        
        self.sources_dir = self.output_dir / "sources"
        self.sources_dir.mkdir(exist_ok=True)
        
        
        self.db_path = self.output_dir / "journals.db"
        self.init_database()
        
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
    
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
        ]
        
        
        self.stats = {
            'total_collected': 0,
            'by_source': {},
            'start_time': datetime.now(),
            'last_collection': None
        }
        
        
        self.running = True
        self.collection_thread = None
        
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        
        self.driver = None
        
        
        self.indonesian_keywords = [
            "indonesia", "indonesian", "bahasa indonesia", "pendidikan", "ekonomi",
            "teknologi", "kesehatan", "lingkungan", "sosial", "budaya", "hukum",
            "pertanian", "perikanan", "kehutanan", "industri", "manajemen",
            "akuntansi", "psikologi", "komunikasi", "sejarah", "geografi",
            "matematika", "fisika", "kimia", "biologi", "teknik", "informatika",
            "kedokteran", "farmasi", "keperawatan", "politik", "administrasi"
        ]
        
    def init_database(self):
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS journals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title_hash TEXT UNIQUE,
                title TEXT NOT NULL,
                abstract TEXT,
                authors TEXT,
                keywords TEXT,
                journal_name TEXT,
                year INTEGER,
                doi TEXT,
                url TEXT,
                pdf_url TEXT,
                citations INTEGER DEFAULT 0,
                pages TEXT,
                volume TEXT,
                issue TEXT,
                publisher TEXT,
                affiliation TEXT,
                subject_area TEXT,
                language TEXT DEFAULT 'id',
                source TEXT,
                collected_date TEXT,
                full_text TEXT,
                reference_list TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collection_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                count INTEGER,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def signal_handler(self, signum, frame):
        
        logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
        self.running = False
        self.save_final_report()
        sys.exit(0)
        
    def get_random_headers(self):
        
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
    def calculate_title_hash(self, title: str) -> str:
        
        normalized_title = re.sub(r'[^\w\s]', '', title.lower().strip())
        return hashlib.md5(normalized_title.encode()).hexdigest()
        
    def save_journal_to_db(self, journal: JournalEntry) -> bool:
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            title_hash = self.calculate_title_hash(journal.title)
            
            
            cursor.execute("SELECT id FROM journals WHERE title_hash = ?", (title_hash,))
            if cursor.fetchone():
                conn.close()
                return False
                
            # Insert new journal
            cursor.execute('''
                INSERT INTO journals (
                    title_hash, title, abstract, authors, keywords, journal_name,
                    year, doi, url, pdf_url, citations, pages, volume, issue,
                    publisher, affiliation, subject_area, language, source,
                    collected_date, full_text, reference_list
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                title_hash, journal.title, journal.abstract,
                json.dumps(journal.authors, ensure_ascii=False),
                json.dumps(journal.keywords, ensure_ascii=False),
                journal.journal_name, journal.year, journal.doi, journal.url,
                journal.pdf_url, journal.citations, journal.pages, journal.volume,
                journal.issue, journal.publisher, journal.affiliation,
                journal.subject_area, journal.language, journal.source,
                journal.collected_date, journal.full_text,
                json.dumps(journal.reference_list, ensure_ascii=False)
            ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error saving journal to database: {e}")
            return False
            
    def collect_from_google_scholar(self, query: str, max_results: int = 100) -> List[JournalEntry]:
        
        journals = []
        
        try:
            logger.info(f"Collecting from Google Scholar: {query}")
            
            search_query = scholarly.search_pubs(query)
            count = 0
            
            for pub in search_query:
                if count >= max_results or not self.running:
                    break
                    
                try:
                    
                    filled_pub = scholarly.fill(pub)
                    
                    
                    authors = []
                    if 'author' in filled_pub['bib']:
                        authors = [str(author) for author in filled_pub['bib']['author']]
                    
                    journal = JournalEntry(
                        title=filled_pub['bib'].get('title', ''),
                        abstract=filled_pub['bib'].get('abstract', ''),
                        authors=authors,
                        journal_name=filled_pub['bib'].get('venue', ''),
                        year=int(filled_pub['bib'].get('pub_year', 0)) if filled_pub['bib'].get('pub_year') else 0,
                        url=filled_pub.get('pub_url', ''),
                        citations=filled_pub.get('num_citations', 0),
                        publisher=filled_pub['bib'].get('publisher', ''),
                        source='google_scholar'
                    )
                    
                    if journal.title and len(journal.title) > 10:
                        journals.append(journal)
                        count += 1
                        
                    time.sleep(random.uniform(2, 5))  
                    
                except Exception as e:
                    logger.error(f"Error processing Google Scholar result: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error collecting from Google Scholar: {e}")
            
        logger.info(f"Collected {len(journals)} journals from Google Scholar")
        return journals
        
    def collect_from_sinta(self, max_results: int = 500) -> List[JournalEntry]:
        
        journals = []
        base_url = "https://sinta.kemdikbud.go.id"
        
        try:
            
            for keyword in self.indonesian_keywords[:10]:  
                if not self.running:
                    break
                    
                logger.info(f"Searching SINTA for: {keyword}")
                
                search_url = f"{base_url}/journals/search"
                params = {'q': keyword}
                
                response = self.session.get(search_url, params=params, 
                                          headers=self.get_random_headers(), timeout=30)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Parse journal entries (this is a simplified example)
                    journal_items = soup.find_all('div', class_='journal-item')
                    
                    for item in journal_items:
                        try:
                            title_elem = item.find('h3') or item.find('h4')
                            title = title_elem.get_text(strip=True) if title_elem else ""
                            
                            if title and len(title) > 10:
                                journal = JournalEntry(
                                    title=title,
                                    source='sinta',
                                    language='id'
                                )
                                journals.append(journal)
                                
                        except Exception as e:
                            logger.error(f"Error parsing SINTA item: {e}")
                            continue
                            
                time.sleep(random.uniform(3, 6))
                
        except Exception as e:
            logger.error(f"Error collecting from SINTA: {e}")
            
        return journals
        
    def collect_from_garuda(self, max_results: int = 500) -> List[JournalEntry]:
        
        journals = []
        base_url = "https://garuda.kemdikbud.go.id"
        
        try:
            for keyword in self.indonesian_keywords[:15]:
                if not self.running:
                    break
                    
                logger.info(f"Searching Portal Garuda for: {keyword}")
                
                search_url = f"{base_url}/search_articles"
                params = {'search': keyword}
                
                response = self.session.get(search_url, params=params,
                                          headers=self.get_random_headers(), timeout=30)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    
                    articles = soup.find_all('div', class_='article-item')
                    
                    for article in articles:
                        try:
                            title = article.find('h3').get_text(strip=True) if article.find('h3') else ""
                            abstract = article.find('div', class_='abstract').get_text(strip=True) if article.find('div', class_='abstract') else ""
                            authors_elem = article.find('div', class_='authors')
                            authors = [a.get_text(strip=True) for a in authors_elem.find_all('a')] if authors_elem else []
                            
                            if title and len(title) > 10:
                                journal = JournalEntry(
                                    title=title,
                                    abstract=abstract,
                                    authors=authors,
                                    source='portal_garuda',
                                    language='id'
                                )
                                journals.append(journal)
                                
                        except Exception as e:
                            logger.error(f"Error parsing Garuda article: {e}")
                            continue
                            
                time.sleep(random.uniform(2, 4))
                
        except Exception as e:
            logger.error(f"Error collecting from Portal Garuda: {e}")
            
        return journals
        
    def collect_from_doaj_advanced(self, max_results: int = 1000) -> List[JournalEntry]:
        
        journals = []
        base_url = "https://doaj.org/api/v3/search/articles/"
        
        try:
            for keyword in self.indonesian_keywords:
                if not self.running or len(journals) >= max_results:
                    break
                    
                page = 1
                while len(journals) < max_results and self.running:
                    params = {
                        'q': f'"{keyword}" OR indonesia',
                        'page': page,
                        'pageSize': 50
                    }
                    
                    logger.info(f"Fetching DOAJ page {page} for keyword: {keyword}")
                    response = self.session.get(base_url, params=params, timeout=30)
                    
                    if response.status_code != 200:
                        break
                        
                    data = response.json()
                    results = data.get('results', [])
                    
                    if not results:
                        break
                        
                    for article in results:
                        bibjson = article.get('bibjson', {})
                        
                        
                        authors = []
                        for author in bibjson.get('author', []):
                            name = author.get('name', '')
                            affiliation = author.get('affiliation', '')
                            if name:
                                authors.append(f"{name} ({affiliation})" if affiliation else name)
                        
                        
                        abstract = ''
                        if bibjson.get('abstract'):
                            if isinstance(bibjson['abstract'], list):
                                abstract = ' '.join([abs_item.get('text', '') for abs_item in bibjson['abstract']])
                            else:
                                abstract = str(bibjson['abstract'])
                        
                        journal = JournalEntry(
                            title=bibjson.get('title', ''),
                            abstract=abstract,
                            authors=authors,
                            keywords=bibjson.get('keywords', []),
                            journal_name=bibjson.get('journal', {}).get('title', ''),
                            year=int(bibjson.get('year', 0)) if bibjson.get('year') else 0,
                            doi=next(iter([id_item['id'] for id_item in bibjson.get('identifier', []) if id_item.get('type') == 'doi']), ''),
                            pages=f"{bibjson.get('start_page', '')}-{bibjson.get('end_page', '')}".strip('-'),
                            volume=str(bibjson.get('volume', '')),
                            issue=str(bibjson.get('number', '')),
                            publisher=bibjson.get('journal', {}).get('publisher', ''),
                            language=bibjson.get('language', [''])[0] if bibjson.get('language') else 'unknown',
                            source='doaj_advanced'
                        )
                        
                        if journal.title and len(journal.title) > 10:
                            journals.append(journal)
                            
                    page += 1
                    time.sleep(1)
                    
        except Exception as e:
            logger.error(f"Error in advanced DOAJ collection: {e}")
            
        return journals
        
    def collect_from_arxiv(self, max_results: int = 200) -> List[JournalEntry]:
        
        journals = []
        base_url = "http://export.arxiv.org/api/query"
        
        try:
            search_queries = [
                'all:indonesia',
                'all:indonesian',
                'all:"indonesian university"',
                'all:"universitas indonesia"'
            ]
            
            for query in search_queries:
                if not self.running:
                    break
                    
                params = {
                    'search_query': query,
                    'start': 0,
                    'max_results': max_results // len(search_queries)
                }
                
                logger.info(f"Searching arXiv: {query}")
                response = self.session.get(base_url, params=params, timeout=30)
                
                if response.status_code == 200:
                    
                    root = ET.fromstring(response.content)
                    
                    for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
                        try:
                            title = entry.find('{http://www.w3.org/2005/Atom}title').text.strip()
                            summary = entry.find('{http://www.w3.org/2005/Atom}summary').text.strip()
                            
                            
                            authors = []
                            for author in entry.findall('{http://www.w3.org/2005/Atom}author'):
                                name = author.find('{http://www.w3.org/2005/Atom}name').text
                                authors.append(name)
                                
                            
                            published = entry.find('{http://www.w3.org/2005/Atom}published').text
                            year = int(published[:4])
                            
                            
                            doi = ""
                            doi_elem = entry.find('{http://arxiv.org/schemas/atom}doi')
                            if doi_elem is not None:
                                doi = doi_elem.text
                                
                            journal = JournalEntry(
                                title=title,
                                abstract=summary,
                                authors=authors,
                                year=year,
                                doi=doi,
                                url=entry.find('{http://www.w3.org/2005/Atom}id').text,
                                source='arxiv',
                                language='en'
                            )
                            
                            if len(title) > 10:
                                journals.append(journal)
                                
                        except Exception as e:
                            logger.error(f"Error parsing arXiv entry: {e}")
                            continue
                            
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error collecting from arXiv: {e}")
            
        return journals
        
    def collect_from_pubmed(self, max_results: int = 300) -> List[JournalEntry]:
        
        journals = []
        base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        
        try:
            search_terms = [
                "indonesia[Affiliation]",
                "indonesian[Title/Abstract]",
                '"indonesian journal"[Journal]'
            ]
            
            for term in search_terms:
                if not self.running:
                    break

                search_url = f"{base_url}esearch.fcgi"
                search_params = {
                    'db': 'pubmed',
                    'term': term,
                    'retmax': max_results // len(search_terms),
                    'retmode': 'xml'
                }
                
                logger.info(f"Searching PubMed: {term}")
                response = self.session.get(search_url, params=search_params, timeout=30)
                
                if response.status_code == 200:
                    search_root = ET.fromstring(response.content)
                    pmids = [id_elem.text for id_elem in search_root.findall('.//Id')]
                    
                    if pmids:
                        fetch_url = f"{base_url}efetch.fcgi"
                        fetch_params = {
                            'db': 'pubmed',
                            'id': ','.join(pmids[:50]),  
                            'retmode': 'xml'
                        }
                        
                        detail_response = self.session.get(fetch_url, params=fetch_params, timeout=30)
                        
                        if detail_response.status_code == 200:
                            detail_root = ET.fromstring(detail_response.content)
                            
                            for article in detail_root.findall('.//PubmedArticle'):
                                try:
                                    medline = article.find('.//MedlineCitation')
                                    article_elem = medline.find('.//Article')
                                    
                                    title = article_elem.find('.//ArticleTitle').text if article_elem.find('.//ArticleTitle') is not None else ""
                                    
                                    abstract = ""
                                    abstract_elem = article_elem.find('.//Abstract/AbstractText')
                                    if abstract_elem is not None:
                                        abstract = abstract_elem.text or ""
                                    

                                    authors = []
                                    for author in article_elem.findall('.//Author'):
                                        lastname = author.find('.//LastName')
                                        forename = author.find('.//ForeName')
                                        if lastname is not None and forename is not None:
                                            authors.append(f"{forename.text} {lastname.text}")

                                    journal_elem = article_elem.find('.//Journal')
                                    journal_name = journal_elem.find('.//Title').text if journal_elem.find('.//Title') is not None else ""

                                    year = 0
                                    year_elem = medline.find('.//PubDate/Year')
                                    if year_elem is not None:
                                        year = int(year_elem.text)
                                        
                                    journal = JournalEntry(
                                        title=title,
                                        abstract=abstract,
                                        authors=authors,
                                        journal_name=journal_name,
                                        year=year,
                                        source='pubmed',
                                        subject_area='Medical/Health',
                                        language='en'
                                    )
                                    
                                    if title and len(title) > 10:
                                        journals.append(journal)
                                        
                                except Exception as e:
                                    logger.error(f"Error parsing PubMed article: {e}")
                                    continue
                                    
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error collecting from PubMed: {e}")
            
        return journals
        
    def save_source_data(self, journals: List[JournalEntry], source_name: str):
        if not journals:
            return
            
        source_file = self.sources_dir / f"{source_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            journal_dicts = [asdict(journal) for journal in journals]
            
            with open(source_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'source': source_name,
                    'collection_date': datetime.now().isoformat(),
                    'count': len(journals),
                    'journals': journal_dicts
                }, f, ensure_ascii=False, indent=2)
                
            logger.info(f"Saved {len(journals)} journals from {source_name} to {source_file}")
            
        except Exception as e:
            logger.error(f"Error saving {source_name} data: {e}")
            
    def update_stats(self, source: str, count: int):
        self.stats['total_collected'] += count
        self.stats['by_source'][source] = self.stats['by_source'].get(source, 0) + count
        self.stats['last_collection'] = datetime.now()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO collection_stats (source, count, last_updated)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (source, self.stats['by_source'][source]))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error updating stats: {e}")
            
    def continuous_collection_cycle(self):
        logger.info("Starting collection cycle...")
        

        sources_methods = [
            ('google_scholar', lambda: self.collect_from_google_scholar("indonesia OR indonesian", 50)),
            ('doaj_advanced', lambda: self.collect_from_doaj_advanced(200)),
            ('arxiv', lambda: self.collect_from_arxiv(100)),
            ('pubmed', lambda: self.collect_from_pubmed(150)),
            ('sinta', lambda: self.collect_from_sinta(100)),
            ('garuda', lambda: self.collect_from_garuda(100))
        ]
        
        for source_name, collect_method in sources_methods:
            if not self.running:
                break
                
            try:
                logger.info(f"Collecting from {source_name}...")
                journals = collect_method()
                
                if journals:
                    saved_count = 0
                    for journal in journals:
                        if self.save_journal_to_db(journal):
                            saved_count += 1
                            
                    self.save_source_data(journals, source_name)
                    
                    self.update_stats(source_name, saved_count)
                    
                    logger.info(f"Saved {saved_count} new journals from {source_name}")
                else:
                    logger.info(f"No new journals collected from {source_name}")
                    
            except Exception as e:
                logger.error(f"Error collecting from {source_name}: {e}")
                
            if self.running:
                time.sleep(random.uniform(10, 30))
                
    def start_continuous_collection(self, cycle_interval_minutes: int = 60):
        def collection_worker():
            while self.running:
                try:
                    self.continuous_collection_cycle()
                    
                    if self.running:
                        logger.info(f"Collection cycle completed. Waiting {cycle_interval_minutes} minutes for next cycle...")
                        for _ in range(cycle_interval_minutes * 60):
                            if not self.running:
                                break
                            time.sleep(1)
                            
                except Exception as e:
                    logger.error(f"Error in collection worker: {e}")
                    time.sleep(300)  
                    
        self.collection_thread = threading.Thread(target=collection_worker, daemon=True)
        self.collection_thread.start()
        logger.info("Continuous collection started. Press Ctrl+C to stop.")
        
    def get_collection_summary(self) -> Dict:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM journals")
            total_count = cursor.fetchone()[0]

            cursor.execute("SELECT source, COUNT(*) FROM journals GROUP BY source")
            by_source = dict(cursor.fetchall())

            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            cursor.execute("SELECT COUNT(*) FROM journals WHERE collected_date > ?", (yesterday,))
            recent_count = cursor.fetchone()[0]

            cursor.execute("SELECT year, COUNT(*) FROM journals WHERE year > 0 GROUP BY year ORDER BY year DESC LIMIT 10")
            by_year = dict(cursor.fetchall())
            
            conn.close()
            
            runtime = datetime.now() - self.stats['start_time']
            
            return {
                'total_journals': total_count,
                'by_source': by_source,
                'recent_24h': recent_count,
                'by_year': by_year,
                'runtime': str(runtime),
                'last_collection': self.stats['last_collection'].isoformat() if self.stats['last_collection'] else None
            }
            
        except Exception as e:
            logger.error(f"Error getting collection summary: {e}")
            return {}
            
    def export_data(self, format_type: str = 'json', filter_criteria: Dict = None) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            
            query = "SELECT * FROM journals WHERE 1=1"
            params = []
            
            if filter_criteria:
                if filter_criteria.get('year_from'):
                    query += " AND year >= ?"
                    params.append(filter_criteria['year_from'])
                if filter_criteria.get('year_to'):
                    query += " AND year <= ?"
                    params.append(filter_criteria['year_to'])
                if filter_criteria.get('source'):
                    query += " AND source = ?"
                    params.append(filter_criteria['source'])
                if filter_criteria.get('language'):
                    query += " AND language = ?"
                    params.append(filter_criteria['language'])
                    
            df = pd.read_sql_query(query, conn, params=params)
            conn.close()
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if format_type.lower() == 'csv':
                filename = self.output_dir / f"journals_export_{timestamp}.csv"
                df.to_csv(filename, index=False, encoding='utf-8')
            elif format_type.lower() == 'excel':
                filename = self.output_dir / f"journals_export_{timestamp}.xlsx"
                df.to_excel(filename, index=False, engine='openpyxl')
            else:  
                filename = self.output_dir / f"journals_export_{timestamp}.json"
                df.to_json(filename, orient='records', force_ascii=False, indent=2)
                
            logger.info(f"Exported {len(df)} journals to {filename}")
            return str(filename)
            
        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            return ""
            
    def search_journals(self, query: str, fields: List[str] = None) -> List[Dict]:
        if fields is None:
            fields = ['title', 'abstract', 'keywords']
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            for field in fields:
                conditions.append(f"{field} LIKE ?")
                params.append(f"%{query}%")
                
            where_clause = " OR ".join(conditions)
            
            cursor.execute(f"""
                SELECT title, abstract, authors, journal_name, year, source, url
                FROM journals 
                WHERE {where_clause}
                ORDER BY year DESC
                LIMIT 100
            """, params)
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'title': row[0],
                    'abstract': row[1],
                    'authors': row[2],
                    'journal_name': row[3],
                    'year': row[4],
                    'source': row[5],
                    'url': row[6]
                })
                
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error searching journals: {e}")
            return []
            
    def generate_collection_report(self) -> str:
        summary = self.get_collection_summary()
        
        report = f"""
=== LAPORAN PENGUMPULAN JURNAL INDONESIA ===
Tanggal Laporan: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Waktu Berjalan: {summary.get('runtime', 'N/A')}

STATISTIK UMUM:
- Total Jurnal Terkumpul: {summary.get('total_journals', 0):,}
- Jurnal Baru (24 jam terakhir): {summary.get('recent_24h', 0):,}
- Terakhir Mengumpulkan: {summary.get('last_collection', 'Belum ada')}

DISTRIBUSI BERDASARKAN SUMBER:
"""
        
        for source, count in summary.get('by_source', {}).items():
            percentage = (count / summary.get('total_journals', 1)) * 100
            report += f"- {source.upper()}: {count:,} jurnal ({percentage:.1f}%)\n"
            
        report += "\nDISTRIBUSI BERDASARKAN TAHUN:\n"
        for year, count in summary.get('by_year', {}).items():
            report += f"- {year}: {count:,} jurnal\n"
            
        report_file = self.output_dir / f"collection_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Collection report saved to {report_file}")
        except Exception as e:
            logger.error(f"Error saving report: {e}")
            
        return report
        
    def save_final_report(self):
        logger.info("Generating final collection report...")
        report = self.generate_collection_report()
        print("\n" + "="*50)
        print("LAPORAN AKHIR PENGUMPULAN JURNAL")
        print("="*50)
        print(report)
        
        final_export = self.export_data('json')
        if final_export:
            print(f"\nData akhir diekspor ke: {final_export}")
            
    def cleanup(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
                
        self.session.close()
        
    def collect_from_semantic_scholar(self, query: str, max_results: int = 200) -> List[JournalEntry]:
        journals = []
        base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        
        try:
            headers = self.get_random_headers()
            
            params = {
                'query': f"{query} indonesia",
                'limit': min(100, max_results),
                'fields': 'title,abstract,authors,venue,year,citationCount,url,reference_list'
            }
            
            logger.info(f"Searching Semantic Scholar for: {query}")
            response = self.session.get(base_url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                papers = data.get('data', [])
                
                for paper in papers:
                    try:
                        authors = []
                        for author in paper.get('authors', []):
                            authors.append(author.get('name', ''))
                            
                        reference_list = []
                        for ref in paper.get('reference_list', [])[:10]: 
                            if ref.get('title'):
                                reference_list.append(ref['title'])
                                
                        journal = JournalEntry(
                            title=paper.get('title', ''),
                            abstract=paper.get('abstract', ''),
                            authors=authors,
                            journal_name=paper.get('venue', ''),
                            year=paper.get('year', 0),
                            citations=paper.get('citationCount', 0),
                            url=paper.get('url', ''),
                            reference_list=reference_list,
                            source='semantic_scholar'
                        )
                        
                        if journal.title and len(journal.title) > 10:
                            journals.append(journal)
                            
                    except Exception as e:
                        logger.error(f"Error parsing Semantic Scholar paper: {e}")
                        continue
                        
            time.sleep(2) 
            
        except Exception as e:
            logger.error(f"Error collecting from Semantic Scholar: {e}")
            
        return journals
        
    def collect_from_indonesian_universities(self, max_results: int = 300) -> List[JournalEntry]:
        journals = []
        
        universities = {
            'ui': 'http://lib.ui.ac.id',
            'itb': 'https://digilib.itb.ac.id',
            'ugm': 'https://etd.repository.ugm.ac.id',
            'unair': 'http://repository.unair.ac.id',
            'its': 'https://repository.its.ac.id'
        }
        
        for univ_code, base_url in universities.items():
            if not self.running or len(journals) >= max_results:
                break
                
            try:
                logger.info(f"Collecting from {univ_code.upper()} repository...")
                search_params = {
                    'q': 'jurnal',
                    'format': 'json'
                }
                
                response = self.session.get(f"{base_url}/search", 
                                          params=search_params, 
                                          headers=self.get_random_headers(),
                                          timeout=30)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    articles = soup.find_all('div', class_=['article', 'paper', 'thesis'])
                    
                    for article in articles[:50]:  # Limit per university
                        try:
                            title_elem = article.find(['h2', 'h3', 'h4'])
                            title = title_elem.get_text(strip=True) if title_elem else ""
                            
                            if title and len(title) > 10:
                                journal = JournalEntry(
                                    title=title,
                                    source=f'repository_{univ_code}',
                                    affiliation=univ_code.upper(),
                                    language='id'
                                )
                                journals.append(journal)
                                
                        except Exception as e:
                            logger.error(f"Error parsing {univ_code} article: {e}")
                            continue
                            
                time.sleep(random.uniform(3, 6))
                
            except Exception as e:
                logger.error(f"Error collecting from {univ_code}: {e}")
                
        return journals

def main():
    collector = AdvancedJournalCollector()
    
    print("=== ADVANCED INDONESIAN JOURNAL COLLECTOR ===")
    print("Sistem pengumpulan jurnal Indonesia yang powerful dan berkelanjutan")
    print("Tekan Ctrl+C untuk menghentikan secara aman")
    print("="*60)
    
    try:
        collector.start_continuous_collection(cycle_interval_minutes=30)
        while collector.running:
            time.sleep(300) 
            
            summary = collector.get_collection_summary()
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Status: {summary.get('total_journals', 0)} jurnal terkumpul")
            
            for source, count in summary.get('by_source', {}).items():
                print(f"  - {source}: {count}")
                
    except KeyboardInterrupt:
        print("\nMenerima sinyal penghentian...")
        collector.running = False
        
    finally:
        if collector.collection_thread and collector.collection_thread.is_alive():
            print("Menunggu proses pengumpulan selesai...")
            collector.collection_thread.join(timeout=30)
            
        collector.save_final_report()
        collector.cleanup()
        print("Sistem telah dihentikan dengan aman.")

if __name__ == "__main__":
    main()