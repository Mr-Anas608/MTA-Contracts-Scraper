"""
MTA Contracts Scraper - Extracts contract information from the MTA website.

This module provides functionality to scrape contract information from the MTA website.
It uses SeleniumBase for browser automation and implements a multi-threaded approach
for concurrent scraping of multiple contract numbers.
"""

from seleniumbase import SB
import time
import re
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from parsel import Selector
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from screeninfo import get_monitors
import traceback
from functools import wraps
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from logs.custom_logging import setup_logging



# Initialize logger
logger = setup_logging(console_level=logging.DEBUG)


# ==========================================
# DATA CLASSES FOR XPATH SELECTORS
# ==========================================

@dataclass
class XpathSelectors:
    """Stores XPath selectors for various elements on the MTA website."""
    
    # Navigation and UI Elements
    search_MTA_button: str = './/h3[contains(text(), "MWD/BE Utilization Plans Report")]/..//a'
    contract_iframe_tag: str = './/div[@class="modal active"]//iframe'
    contract_number_input: str = './/input[@name="ContractNumber"]'
    search_button: str = './/input[@id="ButtonSearch"]'
    page_model_iframe: str = './/iframe[@id="PageModaliFrame"]'
    final_form_tag: str = './/form[@name="PageForm"]'

    # Contract Information Selectors
    contract_description: str = './/td[contains(., "Contract Description")]/following-sibling::td[1]/strong/text()'
    contract_number: str = './/td[contains(., "Contract Number")]/following-sibling::td[1]/strong/text()'
    organization: str = './/td[contains(., "Contract Number")]/../following-sibling::tr[1]/td/strong/text()'
    status: str = './/td[contains(., "Status")]/following-sibling::td[1]/strong/text()'
    dates: str = './/td[contains(., "Dates")]/following-sibling::td[1]/strong/text()'
    prime_contractor: str = '//td[contains(., "Prime Contractor")]/following-sibling::td[1]/strong/text()'

    # Subcontractor Selectors
    name: str = './td[1]/table//td[2]//text()'
    tier: str = './/img[contains(@src, "/images/img_sub_tier_")]/@src'
    type_of_goal: str = './td[2]/img/@alt'
    contracted_amount: str = './td[3]/text()'  # Both amount & % included
    paid_amount: str = './td[4]/text()'


# ==========================================
# DATA CLASSES FOR STORING INFORMATION
# ==========================================

@dataclass
class ContractInformation:
    """Stores information about a contract."""
    contract_description: str = ''
    contract_number: str = ''
    organization: str = ''
    status: str = ''
    dates: str = ''
    prime_contractor: str = ''

    def to_dict(self) -> Dict[str, Any]:
        """Convert the dataclass instance to a dictionary."""
        return asdict(self)


@dataclass
class AwardSummary:
    """Stores award and payment summary information."""
    award: str = None
    award_percentage: Optional[str] = None
    payments: str = None
    payments_percentage: Optional[str]  = None
    difference: Optional[str]  = ''

    def to_dict(self) -> Dict[str, Any]:
        """Convert the dataclass instance to a dictionary."""
        return asdict(self)


@dataclass
class Subcontractors:
    """Stores information about a subcontractor."""
    name: str = ''
    tier: Optional[int] = None
    type_of_goal: str = ''
    included_in_goal: bool = False
    contracted_amount: Optional[str] = None
    paid_amount: Optional[str] = None
    # more_subcontractors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the dataclass instance to a dictionary."""
        return asdict(self)


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


def sanitize_text(text: Optional[str]) -> str:
    """Clean up text by removing excessive whitespace."""
    if text is None:
        return ''
    return re.sub(r'\s+', ' ', text).strip()


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
        self.xpath_selectors = XpathSelectors()
        self.max_workers = max_workers
        self.retry_attempts = retry_attempts

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
            self.logger.warning(f"Could not get monitor info: {e}. Using default values.")
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

    @staticmethod
    def organize_subcontractors(temp_subcontractors_list: List[Tuple[int, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Organize subcontractors into a hierarchical structure based on tier level.
        
        Args:
            temp_subcontractors_list: List of tuples containing tier level and subcontractor info
            
        Returns:
            A list of dictionaries with hierarchical subcontractor structure
        """
        organized_subcontractors = []
        nesting_stack = []

        for tier_level, subcontractor_info in temp_subcontractors_list:
            # Create a new node combining subcontractor info and tier level
            current_node = {**subcontractor_info, "tier": tier_level}
        
            # Remove any nodes from the stack that are at the same or deeper level
            while nesting_stack and nesting_stack[-1]["tier"] >= tier_level:
                nesting_stack.pop()

            if nesting_stack:
                # If there's a valid parent on the stack, add current node as a child
                parent_node = nesting_stack[-1] 

                if "more_subcontractors" not in parent_node:
                    parent_node["more_subcontractors"] = []

                parent_node["more_subcontractors"].append(current_node)
            else:
                # If no valid parent found, this is a top-level (tier 1) subcontractor
                organized_subcontractors.append(current_node)

            # Push current node onto the stack so it can be a parent to next tier
            nesting_stack.append(current_node)

        return organized_subcontractors

    def extract_data(self, form_html: str) -> Optional[Dict[str, Any]]:
        """
        Extract contract information from the HTML content.
        
        Args:
            form_html: The HTML content of the contract page
            
        Returns:
            A dictionary containing contract information, award summary, and subcontractors
            or None if extraction failed
        """
        if not form_html:
            self.logger.error("No HTML content provided for extraction")
            return None
            
        try:
            selector = Selector(form_html)
            
            # Extract contract information
            contract_info_result = self._extract_contract_info(selector)
            if not contract_info_result:
                return None
                
            # Extract award summary
            award_summary_result = self._extract_award_summary(selector)
                
            # Extract subcontractors
            subcontractors_results = self._extract_subcontractors(selector)
            
            return {
                "contract_info": contract_info_result,
                "award_summary": award_summary_result,
                "subcontractors": subcontractors_results
            }
            
        except Exception as e:
            self.logger.error(f"Error extracting data: {e}")
            self.logger.debug(traceback.format_exc())
            return None

    def _extract_contract_info(self, selector: Selector) -> Optional[Dict[str, Any]]:
        """
        Extract basic contract information.
        
        Args:
            selector: Parsel Selector object for the HTML content
            
        Returns:
            A dictionary containing contract information or None if extraction failed
        """
        try:
            store_contract_info = ContractInformation()

            # Extract each field with error handling
            for field, xpath in [
                ('contract_description', self.xpath_selectors.contract_description),
                ('contract_number', self.xpath_selectors.contract_number),
                ('organization', self.xpath_selectors.organization),
                ('status', self.xpath_selectors.status),
                ('dates', self.xpath_selectors.dates),
                ('prime_contractor', self.xpath_selectors.prime_contractor)
            ]:
                try:
                    value = selector.xpath(xpath).get()
                    setattr(store_contract_info, field, sanitize_text(value))
                except Exception as e:
                    self.logger.warning(f"Error extracting {field}: {e}")
                    setattr(store_contract_info, field, '')

            return store_contract_info.to_dict()

        except Exception as e:
            self.logger.error(f"Error parsing contract information: {e}")
            self.logger.debug(traceback.format_exc())
            return None

    def _extract_award_summary(self, selector: Selector) -> Dict[str, Dict[str, Any]]:
        """
        Extract award summary information.
        
        Args:
            selector: Parsel Selector object for the HTML content
            
        Returns:
            A dictionary mapping award categories to their details
        """
        award_summary_result = {}
        
        try:
            tr_tags = selector.xpath('.//table[contains(., "Award & Payment Summary")]/following-sibling::table[1]/tbody/tr')
            
            for tr_tag in tr_tags:
                td_tags_text = [sanitize_text(td_tag.xpath('string()').get()) 
                               for td_tag in tr_tag.xpath('./td')]
                
                # Skip empty rows or rows with no first column value
                if not td_tags_text or not td_tags_text[0]:
                    continue
                    
                key_name = td_tags_text[0].lower().replace(' ', '_')
                
                try:
                    store_award_summary = AwardSummary(
                        award=td_tags_text[1] if len(td_tags_text) > 1 else None,
                        award_percentage=td_tags_text[2] if len(td_tags_text) > 2 else None,
                        payments=td_tags_text[3] if len(td_tags_text) > 3 else None,
                        payments_percentage=td_tags_text[4] if len(td_tags_text) > 4 else None,
                        difference=td_tags_text[5] if len(td_tags_text) > 5 else ''
                    )
                    
                    award_summary_result[key_name] = store_award_summary.to_dict()
                
                except Exception as e:
                    self.logger.error(f"Error parsing award row {td_tags_text}: {e}")
        
        except Exception as e:
            self.logger.error(f"Error extracting award summary: {e}")
        
        return award_summary_result

    def _extract_subcontractors(self, selector: Selector) -> List[Dict[str, Any]]:
        """
        Extract subcontractor information.
        
        Args:
            selector: Parsel Selector object for the HTML content
            
        Returns:
            A list of dictionaries containing subcontractor information
        """
        temp_subcontractors_list = []
        
        try:
            # Get all tr tags except header
            tr_tags = selector.xpath('.//table[contains(., "Subcontractors")]/following-sibling::table[1]/tbody/tr[position() > 1]')

            for tr_tag in tr_tags:
            
                try:
                    store_subcontractor = Subcontractors()

                    # Extract name - join all text nodes and clean
                    name_texts = tr_tag.xpath(self.xpath_selectors.name).getall()
                    store_subcontractor.name = sanitize_text(''.join(name_texts))
                    
                    # Extract tier level from image src
                    tier = tr_tag.xpath(self.xpath_selectors.tier).re(r'_(\d+)\.')
                    store_subcontractor.tier = int(tier[0]) if tier else 1

                    # Extract type of goal from alt text
                    type_of_goal = tr_tag.xpath(self.xpath_selectors.type_of_goal).get()
                    store_subcontractor.type_of_goal = type_of_goal if type_of_goal else ''
                    store_subcontractor.included_in_goal = bool(type_of_goal)

                    # Extract contracted amount
                    contracted_amount = tr_tag.xpath(self.xpath_selectors.contracted_amount).getall()
                    if contracted_amount and len(contracted_amount) == 2:
                        store_subcontractor.contracted_amount = f"{sanitize_text(contracted_amount[0])} ({sanitize_text(contracted_amount[1])})"
                    
                    # Extract paid amount
                    paid_amount = tr_tag.xpath(self.xpath_selectors.paid_amount).getall()
                    if paid_amount and len(paid_amount) == 2:
                        store_subcontractor.paid_amount = f"{sanitize_text(paid_amount[0])} ({sanitize_text(paid_amount[1])})"

                    # Add to temporary list with tier level
                    temp_subcontractors_list.append(
                        (store_subcontractor.tier, store_subcontractor.to_dict())
                    )
                        
                except Exception as e:
                    self.logger.error(f"Error parsing subcontractor row: {e}")
                    self.logger.debug(traceback.format_exc())
            
            # Organize subcontractors into hierarchical structure
            return self.organize_subcontractors(temp_subcontractors_list)
            
        except Exception as e:
            self.logger.error(f"Error extracting subcontractors: {e}")
            self.logger.debug(traceback.format_exc())
            return []

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
                        self.logger.warning(f"No match found for contract: {search_term}")
                        return None
                except Exception as e:
                    self.logger.warning(f"Error finding contract link for {search_term}: {e}")
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
                    self.logger.warning(f"Form tag not found for contract: {search_term}")
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
                    result = self.extract_data(form_html)
                    if result:
                        self.logger.info(f"Successfully scraped contract {search_term}")
                        return {search_term: result}
                    else:
                        self.logger.warning(f"Data extraction failed for contract {search_term}")
                else:
                    self.logger.warning(f"No HTML content retrieved for contract {search_term}")
                
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
        
        results = []
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
                        results.append(result)
                        self.logger.info(f"Added result for contract {term}")
                    else:
                        self.logger.warning(f"No result for contract {term}")
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
    contract_numbers = [
        "e30645", 
        "p36719", 
        "ch058B" , 
        "p36721", 
        "1000144457",
        "w32808", 
        "c40838", 
        "a37130", 
        "tn87", 
        "aw73"
    ]
    
    # Initialize scraper with 10 concurrent workers
    scraper = ContractsScraper(max_workers=10)
    
    # Scrape contracts
    results = scraper.scrape_contracts(contract_numbers)
    with open("contracts_data.json", "w") as f:
        json.dump(results, f, indent=4)
    # Print results
    for result in results:
        for contract_number, data in result.items():
            if data:
                print(f"Contract {contract_number}: {data['contract_info']['contract_description']}")
            else:
                print(f"Failed to scrape contract {contract_number}")
    