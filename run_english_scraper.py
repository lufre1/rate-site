#!/usr/bin/env python3
"""
Run the scraper. German and English content are now scraped together and merged
into a single row per dish, so there is no separate English-only pass.
"""
import sys
import os

# Add the backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from scraper import scrape_menus

if __name__ == "__main__":
    print("Starting scraping (German + English merged)...")
    scrape_menus()
    print("Scraping completed!")
