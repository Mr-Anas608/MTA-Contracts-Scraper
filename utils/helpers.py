import os, sys
# Ensure the project's root directory is in the Python path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import re, time, json
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from parsel import Selector
from dataclasses import dataclass, field, asdict
from logs.custom_logging import setup_logging
import aiohttp, logging

# Setup
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
# Html Parser to extract structured data
# ==========================================


class HtmlParser:
    def __init__(self):
        self.logger = logger
        self.xpath_selectors = XpathSelectors()

    def normalize_whitespace(self, text: Optional[str]) -> str:
        """Clean up text by removing excessive whitespace."""
        if text is None:
            return ''
        return re.sub(r'\s+', ' ', text).strip()


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
    
    def search_page_parser(self, html_str: str, search_term: str) -> Optional[Dict[str, str]]:
        """
        Parse search results page to find matching contracts.
        
        Args:
            html_str: The HTML content of the search results page
            search_term: The term to search for in contract names
            
        Returns:
            A dictionary mapping contract name to contract ID, or None if no match found
        """
        try:
            selector = Selector(html_str)
            td_tags = selector.xpath('.//a[contains(@href, "javascript: ViewDetail")]/..')
            
            for td_tag in td_tags:
                try:
                    contract_name = self.normalize_whitespace(td_tag.xpath('.//text()').get())
                    contract_cid = self.normalize_whitespace(td_tag.xpath('.//a/@href').re(r"\(\s*[\'\"]([A-Fa-f0-9]+)[\'\"]\s*\)")[0])
                    
                    if search_term.upper() == contract_name.upper():
                        return {contract_name : contract_cid}
                    else: None

                except Exception as e:
                    self.logger.warning(f"⚠️ Error processing search result: {e}")
                    continue

            return None
        
        except Exception as e:
            self.logger.error(f"❌ Error parsing search page: {e}")
            self.logger.debug(traceback.format_exc())
            return None

    def final_page_parser(self, html_str: str) -> Optional[Dict[str, Any]]:
        """
        Extract contract information from the HTML content.
        
        Args:
            form_html: The HTML content of the contract page
            
        Returns:
            A dictionary containing contract information, award summary, and subcontractors
            or None if extraction failed
        """
        if not html_str:
            self.logger.error("❌ No HTML content provided for extraction")
            return None
            
        try:
            selector = Selector(html_str)
            form_html = selector.xpath(self.xpath_selectors.final_form_tag)
            
            # Extract contract information
            contract_info_result = self._extract_contract_info(form_html)
            if not contract_info_result:
                return None
                
            # Extract award summary
            award_summary_result = self._extract_award_summary(form_html)
                
            # Extract subcontractors
            subcontractors_results = self._extract_subcontractors(form_html)
            
            return {
                "contract_info": contract_info_result,
                "award_summary": award_summary_result,
                "subcontractors": subcontractors_results
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error parsing final page: {e}")
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
                    setattr(store_contract_info, field, self.normalize_whitespace(value))
                except Exception as e:
                    self.logger.warning(f"⚠️ Error extracting {field}: {e}")
                    setattr(store_contract_info, field, '')

            return store_contract_info.to_dict()

        except Exception as e:
            self.logger.error(f"❌ Error parsing contract information: {e}")
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
            tr_tags = selector.xpath('.//table[contains(., "Award & Payment Summary")]/following-sibling::table[1]/tr[position() > 1]')

            for tr_tag in tr_tags:
                td_tags_text = [self.normalize_whitespace(td_tag.xpath('string()').get()) 
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
                    self.logger.error(f"❌ Error parsing award row {td_tags_text}: {e}")

            return award_summary_result    
        except Exception as e:
            self.logger.error(f"❌ Error extracting award summary: {e}")
            self.logger.debug(traceback.format_exc())
            return []

        

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
            tr_tags = selector.xpath('.//table[contains(., "Subcontractors")]/following-sibling::table[1]/tr[position() > 1]')

            for tr_tag in tr_tags:
            
                try:
                    store_subcontractor = Subcontractors()

                    # Extract name - join all text nodes and clean
                    name_texts = tr_tag.xpath(self.xpath_selectors.name).getall()
                    store_subcontractor.name = self.normalize_whitespace(''.join(name_texts))
                    
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
                        store_subcontractor.contracted_amount = f"{self.normalize_whitespace(contracted_amount[0])} ({self.normalize_whitespace(contracted_amount[1])})"
                    
                    # Extract paid amount
                    paid_amount = tr_tag.xpath(self.xpath_selectors.paid_amount).getall()
                    if paid_amount and len(paid_amount) == 2:
                        store_subcontractor.paid_amount = f"{self.normalize_whitespace(paid_amount[0])} ({self.normalize_whitespace(paid_amount[1])})"

                    # Add to temporary list with tier level
                    temp_subcontractors_list.append(
                        (store_subcontractor.tier, store_subcontractor.to_dict())
                    )
                        
                except Exception as e:
                    self.logger.error(f"❌ Error parsing subcontractor row: {e}")
                    self.logger.debug(traceback.format_exc())
            
            # Organize subcontractors into hierarchical structure
            return self.organize_subcontractors(temp_subcontractors_list)
            
        except Exception as e:
            self.logger.error(f"❌ Error extracting subcontractors: {e}")
            self.logger.debug(traceback.format_exc())
            return []



# ========================================================================
# Html Page Scraper class for requesting html using reverse engineering.
# ========================================================================
class HtmlPageScraper:
    """Class for making HTTP requests to fetch contract information from the website."""
    
    def __init__(self):
        """Initialize the HtmlPageScraper with necessary URLs, headers and request parameters."""
        self.logger = logger
        self.search_api = "https://mta.newnycontracts.com/FrontEnd/ContractSearchPublic.asp"
        self.base_url = "https://mta.newnycontracts.com/FrontEnd/ContractSearchPublicDetail.asp?XID=788&TN=mta&CID="
        self.form_data = {
            'Submit': 'Search',
            'DiversityID': '30000183',
            'OrganizationID': '30000183',
            'TemplateName': 'mta',
            'PageNumber': '1',
            'ContractNumber': None,
            'ContractStatus': '1',
        }
        self.params = {
            'XID': '5421',
            'TN': 'mta',
        }
        
        self.get_req_header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Sec-GPC': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Priority': 'u=0, i',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
        self.post_req_header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://mta.newnycontracts.com/FrontEnd/ContractSearchPublic.asp?TN=mta&XID=2353',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://mta.newnycontracts.com',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'iframe',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'DNT': '1',
            'Sec-GPC': '1',
            'Priority': 'u=4',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
        
    async def request_html(self, session: aiohttp.ClientSession, contract_name: str = None, 
                          matched_contract: Dict[str, str] = None) -> Optional[str]:
        """
        Request HTML content for either a contract search or specific contract detail.
        
        Args:
            session: aiohttp ClientSession object for making HTTP requests
            contract_name: Name of the contract to search for
            matched_contract: Dictionary containing contract name and CID for detail page
            
        Returns:
            HTML content as string or None if request failed
        """
        try:
            start_time = time.perf_counter()
            
            if contract_name:
                # Handle search request
                self.form_data['ContractNumber'] = contract_name
                self.logger.info(f'Fetching search page html for search "{contract_name}"')
                
                response = await session.post(
                    self.search_api, 
                    headers=self.post_req_header, 
                    params=self.params, 
                    data=self.form_data
                )
                html_content = await response.text()
                
            elif matched_contract:
                # Handle contract detail request
                contract_name = matched_contract.get("contract_name")
                contract_cid_key = matched_contract.get("contract_cid")
                
                if contract_cid_key and contract_name:
                    final_url = self.base_url + contract_cid_key

                    self.logger.info(f'Fetching final page html for "{contract_name}"')
                    
                    response = await session.get(final_url, headers=self.get_req_header)
                    html_content = await response.text()
                else:
                    self.logger.error("❌ Missing contract name or CID in matched_contract dictionary")
                    return None
            else:
                self.logger.error("❌ No contract number or matched contract provided")
                return None
                
            # Calculate and log performance metrics
            end_time = time.perf_counter()
            duration = end_time - start_time
            if response.status == 200:
                self.logger.info(
                    f"Page for '{contract_name}' fetched successfully - Status: {response.status}, "
                    f"Length: {len(html_content)}, Time taken: {duration:.4f} seconds"
                )
                return html_content
            else:
                self.logger.error(
                    f"Page fetched with issues - Status: {response.status}, "
                    f"Length: {len(html_content)}, Time taken: {duration:.4f} seconds"
                )
                return None
        
        except aiohttp.ClientError as e:
            self.logger.error(f"❌ HTTP client error during fetching: {e}")
            self.logger.debug(traceback.format_exc())
            return None
        except Exception as e:
            self.logger.error(f"❌ Unexpected error during fetching: {e}")
            self.logger.debug(traceback.format_exc())
            return None


# ==================================================
# Input/Output Functions for saving & loading data
# ==================================================



def save_data(new_data: Dict[str, Dict[str, Any]], filename: str = "contracts_data.json") -> None:
    """
    Save new scraped contract data to a JSON file.
    If a key (search term) already exists, its data will be updated.
    
    Args:
        new_data: Dictionary with search_term as key and its contract data as value
        filename: Name of the file to save data into
    """
    base_dir = "output_data"
    file_path = Path(base_dir) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data if file exists
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            logger.warning("File exists but is not valid JSON. Starting with empty data.")
            existing_data = {}
    else:
        existing_data = {}

    # Merge new data
    for search_term, data in new_data.items():
        existing_data[search_term] = data  # Overwrite or add

    if new_data:
        # Save updated data
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=4, ensure_ascii=False)
            logger.info(f"✅ Data saved successfully to '{file_path}'")
        except Exception as e:
            logger.error(f"❌ Error saving data to {file_path}: {e}")
            logger.debug(traceback.format_exc())
    else:
        logger.warning("No new data found for saving!")

def load_input(filename: str = "input.json") -> Optional[List[str]]:
    """
    Load input search terms from a JSON file.

    Args:
        filename: Name of the JSON file inside the 'input_data' folder.

    Returns:
        A list of contract numbers to scrape, or None if loading fails.
    """
    base_dir = "input_data"
    file_path = Path(base_dir) / filename

    # Check if file exists
    if not file_path.exists():
        logger.error(f"Input file not found: {file_path}")
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("[]", encoding="utf-8")
            logger.info(f"A new empty file was created at: {file_path}")
            logger.warning("Please open this file and add your list of contract numbers before running the scraper.")
        except Exception as e:
            logger.critical(f"Failed to create input file or directory: {e}")
            logger.debug(traceback.format_exc())
        return None

    # Try reading and validating content
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            input_data = json.load(f)

        if not isinstance(input_data, list):
            logger.error(f'Invalid format in input file: Expected a list but got {type(input_data).__name__}')
            logger.warning('Make sure your file contains a JSON list, e.g. ["e30645", "p36719"..]')
            return None

        if not input_data:
            logger.warning("The input file is empty. Please add contract numbers to scrape.")
            return None

        return input_data

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in input file.")
        logger.warning("Please make sure the file contains valid JSON syntax.")
        logger.debug(traceback.format_exc())
    except Exception as e:
        logger.error(f"Unexpected error while loading input data: {e}")
        logger.debug(traceback.format_exc())

    return None


if __name__ == "__main__":
    # Debug 
    import pprint
    html_parser = HtmlParser()
    with open("debug.html") as f:
        html_content = f.read()

    result = html_parser.final_page_parser(html_content) 

    pprint.pprint(result)