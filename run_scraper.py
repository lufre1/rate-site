#!/usr/bin/env python3
"""
Test script to verify English scraping functionality
"""
import sys
import os

# Add the backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from scraper import scrape_menus

if __name__ == "__main__":
    print("Starting full scraping process (German + English)...")
    scrape_menus()
    print("Scraping completed!")