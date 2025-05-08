"""
MTA Contracts Scraper - Extracts contract information from the MTA website.

This module provides functionality to scrape contract information from the MTA website.
It uses SeleniumBase for browser automation and implements a multi-threaded approach
for concurrent scraping of multiple contract numbers.
"""

from seleniumbase import SB
import time
from typing import Dict, List, Optional, Tuple, Any
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from screeninfo import get_monitors
import traceback
from functools import wraps
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from logs.custom_logging import setup_logging

from utils.helpers import HtmlParser, XpathSelectors
from utils.helpers import load_input, save_data


# Initialize logger
logger = setup_logging(console_level=logging.DEBUG)



# ==========================================
# UTILITY FUNCTIONS AND DECORATORS
# ==========================================

def log_execution_time(func):
    """Decorator to log the execution time of a function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.debug(f"Function {func.__name__} executed in {execution_time:.2f} seconds")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Function {func.__name__} failed after {execution_time:.2f} seconds: {str(e)}")
            raise
    return wrapper


# ==========================================
# MAIN CONTRACTS SCRAPER
# ==========================================

class ContractsScraper:
    """
    A class for scraping contract information from the MTA website.
    
    This class handles the browser automation and data extraction logic
    for retrieving contract details, award summaries, and subcontractor
    information.
    """
    
    def __init__(self, max_workers: int = 6, retry_attempts: int = 2):
        """
        Initialize the ContractsScraper.
        
        Args:
            max_workers: Maximum number of concurrent browser sessions
            retry_attempts: Number of retry attempts for browser operations
        """
        self.logger = logger
        self.url = "https://mta.newnycontracts.com/?TN=mta"
        self.max_workers = max_workers
        self.retry_attempts = retry_attempts
        self.html_parser = HtmlParser()
        self.xpath_selectors = XpathSelectors()

        # Configure window positioning
        self._configure_window_settings()
        
        # Track used positions for window placement
        self.used_positions = set()

    def _configure_window_settings(self):
        """Configure the window settings based on the screen size."""
        try:
            self.monitor = get_monitors()[0]
            self.SCREEN_WIDTH = self.monitor.width
            self.SCREEN_HEIGHT = self.monitor.height - 80
        except Exception as e:
            # Fallback to default values if screen info can't be retrieved
            self.logger.warning(f"⚠️ Could not get monitor info: {e}. Using default values.")
            self.SCREEN_WIDTH = 1920
            self.SCREEN_HEIGHT = 1080 - 80
            
        # Set window dimensions
        self.WINDOW_WIDTH = 600
        self.WINDOW_HEIGHT = 400
        self.WINDOW_PADDING = 10  # Space between windows

    def get_smart_random_position(self, index: int) -> Tuple[int, int]:
        """
        Get a window position that avoids overlapping with other windows.
        
        Args:
            index: The index of the browser window
            
        Returns:
            A tuple of (x, y) coordinates for window placement
        """
        screen_height = self.SCREEN_HEIGHT - 80
        cols = max(1, self.SCREEN_WIDTH // (self.WINDOW_WIDTH + self.WINDOW_PADDING))
        rows = max(1, screen_height // (self.WINDOW_HEIGHT + self.WINDOW_PADDING))
        max_slots = cols * rows

        # Use grid positioning for first set of windows
        if index < max_slots:
            row = index // cols
            col = index % cols
            x = col * (self.WINDOW_WIDTH + self.WINDOW_PADDING)
            y = row * (self.WINDOW_HEIGHT + self.WINDOW_PADDING)
        else:
            # For additional windows, find a random position that's not already used
            for _ in range(50):  # Try up to 50 times to find an unused position
                x = random.randint(50, self.SCREEN_WIDTH - self.WINDOW_WIDTH - 50)
                y = random.randint(50, screen_height - self.WINDOW_HEIGHT - 50)
                
                # Check if position is sufficiently far from existing windows
                if all((abs(x - pos_x) > 50 or abs(y - pos_y) > 50) 
                       for pos_x, pos_y in self.used_positions):
                    break
            
        self.used_positions.add((x, y))
        return x, y


    @retry(
        retry=retry_if_exception_type((Exception,)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def _find_and_switch_to_iframe(self, sb, iframe_selector: str, timeout: int = 30) -> None:
        """
        Find and switch to an iframe with retry logic.
        
        Args:
            sb: SeleniumBase instance
            iframe_selector: XPath selector for the iframe
            timeout: Maximum time to wait for the iframe
            
        Raises:
            Exception: If iframe cannot be found after retries
        """
        iframe = sb.wait_for_element_visible(iframe_selector, timeout=timeout)
        if not iframe:
            raise Exception(f"Iframe not found with selector: {iframe_selector}")
        sb.switch_to_frame(iframe_selector)


    @log_execution_time
    def launch_browser(self, search_term: str, index: int) -> Optional[str]:
        """
        Launch a browser and navigate to the contract page.
        
        Args:
            search_term: The contract number to search for
            index: The index of the browser window
            
        Returns:
            The HTML content of the contract page or None if navigation failed
        """
        # Get position for this browser window
        x, y = self.get_smart_random_position(index)
        
        try:
            with SB(
                    # uc=True, 
                    incognito=True
                    ) as sb:
                # Configure browser window
                sb.set_window_size(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
                sb.set_window_position(x, y)
                
                # Log the start of navigation
                self.logger.info(f"Searching for contract: {search_term}")
                
                # Navigate to MTA website
                sb.open(self.url)

                # Wait for and click the MTA search button
                sb.wait_for_element_visible(self.xpath_selectors.search_MTA_button, timeout=30).click()
                
                # Switch to contract iframe
                self._find_and_switch_to_iframe(sb, self.xpath_selectors.contract_iframe_tag)
                
                # Enter contract number and search
                sb.type(self.xpath_selectors.contract_number_input, search_term)
                sb.click(self.xpath_selectors.search_button)
                
                # Look for the matching contract link
                try:
                    sb.wait_for_element_visible('.//strong[contains(text(), "Search Results")]', timeout=30)
                    match_link = sb.is_element_visible(f'.//a[text() = "{search_term.upper()}"]')
            
                    if not match_link:
                        self.logger.warning(f"⚠️ No match found for contract: {search_term}")
                        return None
                except Exception as e:
                    self.logger.warning(f"⚠️ Error finding contract link for {search_term}: {e}")
                    return None
                
                # Click on the matching contract link
                sb.click(f'.//a[text() = "{search_term.upper()}"]')
                
                # Switch to page model iframe
                self._find_and_switch_to_iframe(sb, self.xpath_selectors.page_model_iframe)
                
                # Find and extract the form HTML
                body_html_tag = sb.find_element(self.xpath_selectors.final_form_tag, timeout=30)
                if body_html_tag:
                    sb.sleep(1)
                    sb.scroll_to_bottom()
                    sb.sleep(2)
                    body_html = body_html_tag.get_attribute("outerHTML")
                    self.logger.info(f"Successfully retrieved HTML for contract: {search_term}")
                    return body_html
                else:
                    self.logger.warning(f"⚠️ Form tag not found for contract: {search_term}")
                    return None

        except Exception as e:
            self.logger.error(f"Error in browser automation for {search_term}: {e}")
            self.logger.debug(traceback.format_exc())
            return None

    def _scrape_single(self, search_term: str, index: int) -> Optional[Dict[str, Any]]:
        """
        Scrape information for a single contract.
        
        Args:
            search_term: The contract number to search for
            index: The index of the browser window
            
        Returns:
            A dictionary containing contract information or None if scraping failed
        """
        # Try up to retry_attempts times
        for attempt in range(1, self.retry_attempts + 1):
            try:
                self.logger.info(f"Attempt {attempt} for contract {search_term}")
                form_html = self.launch_browser(search_term, index)
                
                if form_html:
                    result = self.html_parser.final_page_parser(form_html)
                    if result:
                        self.logger.info(f"Successfully scraped contract {search_term}")
                        return result
                    else:
                        self.logger.warning(f"⚠️ Data extraction failed for contract {search_term}")
                else:
                    self.logger.warning(f"⚠️ No HTML content retrieved for contract {search_term}")
                
            except Exception as e:
                self.logger.error(f"Attempt {attempt} failed for contract {search_term}: {e}")
                self.logger.debug(traceback.format_exc())
                
            # Wait before retrying, with increasing delay
            if attempt < self.retry_attempts:
                retry_delay = 2 ** attempt  # Exponential backoff
                self.logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                
        self.logger.error(f"All attempts failed for contract {search_term}")
        return {search_term: None}

    def scrape_contracts(self, search_terms: List[str]) -> List[Dict[str, Any]]:
        """
        Scrape information for multiple contracts concurrently.
        
        Args:
            search_terms: List of contract numbers to search for
            
        Returns:
            A list of dictionaries containing contract information
        """
        if not search_terms:
            self.logger.warning("No search terms provided")
            return []
            
        self.logger.info(f"Starting scraping for {len(search_terms)} contracts with {self.max_workers} workers")
        
        # Reset used positions for window placement
        self.used_positions = set()
        
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all jobs
            futures = {
                executor.submit(self._scrape_single, term, idx): term
                for idx, term in enumerate(search_terms)
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                term = futures[future]
                try:
                    result = future.result()
                    if result:
                        results[term] = result
                        self.logger.info(f"Added result for contract {term}")
                    else:
                        self.logger.warning(f"⚠️ No result for contract {term}")
                except Exception as e:
                    self.logger.error(f"Thread failed for contract {term}: {e}")
                    self.logger.debug(traceback.format_exc())
        
        self.logger.info(f"Completed scraping with {len(results)} successful results out of {len(search_terms)} contracts")
        return results



# ==========================================
# Example usage
# ==========================================

if __name__ == "__main__":
    # Sample contract numbers to scrape

    contract_searches = load_input()

    # Initialize scraper with 10 concurrent workers
    scraper = ContractsScraper(max_workers=10)
    
    # Scrape contracts
    results = scraper.scrape_contracts(contract_searches)
    
    save_data(results)