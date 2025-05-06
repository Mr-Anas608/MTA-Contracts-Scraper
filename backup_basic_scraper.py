from seleniumbase import SB
import time, re
from dataclasses import dataclass 
from typing import Dict, List, Optional, Tuple
from parsel import Selector
from logs.custom_logging import setup_logging
import logging, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from screeninfo import get_monitors
logger = setup_logging(console_level=logging.DEBUG)


#===========================================(: Data classes for storing Xpath Selectors :)===========================================

@dataclass
class XpathSelectors:
    # --Buttons--
    search_MTA_button = './/h3[contains(text(), "MWD/BE Utilization Plans Report")]/..//a'
    contract_iframe_tag = './/div[@class="modal active"]//iframe'
    contract_number_input = './/input[@name="ContractNumber"]'
    search_button = './/input[@id="ButtonSearch"]'
    page_model_iframe = './/iframe[@id="PageModaliFrame"]'
    final_form_tag = './/form[@name="PageForm"]'


    # --Contract Information--

    contract_description = './/td[contains(., "Contract Description")]/following-sibling::td[1]/strong/text()'
    contract_number = './/td[contains(., "Contract Number")]/following-sibling::td[1]/strong/text()'
    organization = './/td[contains(., "Contract Number")]/../following-sibling::tr[1]/td/strong/text()'
    status = './/td[contains(., "Status")]/following-sibling::td[1]/strong/text()'
    dates = './/td[contains(., "Dates")]/following-sibling::td[1]/strong/text()'
    prime_contractor = '//td[contains(., "Prime Contractor")]/following-sibling::td[1]/strong/text()'

    # --Subcontractor--
    name = './td[1]/table//td[2]//text()'
    tier = './/img[contains(@src, "/images/img_sub_tier_")]/@src'
    type_of_goal = './td[2]/img/@alt'

     # Both amount & % included
    contracted_amount = './td[3]/text()'
    paid_amount = './td[4]/text()'



#==========================================(: Data classes for storing information :)==========================================


@dataclass
class ContractInformation:
    contract_description = ''
    contract_number = ''
    organization = ''
    status = ''
    dates = ''
    prime_contractor = ''

    def to_dict(self):
        return self.__dict__

@dataclass
class AwardSummary:
    award = None
    award_percentage = None
    payments = None
    payments_percentage = None
    difference = ''

    def to_dict(self):
        return self.__dict__
    
@dataclass
class Subcontractors:
    name = ''
    tier = None
    type_of_goal = ''
    included_in_goal: bool = False
    contracted_amount = None
    # contracted_percentage: float = None
    paid_amount = None
    # paid_percentage: float = None

    def to_dict(self):
        return self.__dict__


#=================================================(: Main Contracts Scraper :)=================================================


class Contracts_Scraper:
    def __init__(self):
        self.logger = setup_logging(console_level=logging.DEBUG)
        self.url = "https://mta.newnycontracts.com/?TN=mta"
        self.xpath_selectors = XpathSelectors()
        self.max_workers = 20

        # Screen size & window size settings
        self.monitor = get_monitors()[0]
        self.SCREEN_WIDTH = self.monitor.width
        self.SCREEN_HEIGHT = self.monitor.height - 80
        self.WINDOW_WIDTH = 600
        self.WINDOW_HEIGHT = 400
        self.used_positions = set()

    def get_smart_random_position(self, index):
        padding = 10  # Space between windows

        
        screen_height = self.SCREEN_HEIGHT - 80 
        cols = self.SCREEN_WIDTH // (self.WINDOW_WIDTH + padding)
        rows = screen_height // (self.WINDOW_HEIGHT + padding)
        max_slots = cols * rows

        if index < max_slots:
            row = index // cols
            col = index % cols
            x = col * (self.WINDOW_WIDTH + padding)
            y = row * (self.WINDOW_HEIGHT + padding)
        else:
            tries = 0
            while tries < 50:

                x = random.randint(50, self.SCREEN_WIDTH - self.WINDOW_WIDTH - 50)
                y = random.randint(50, screen_height - self.WINDOW_HEIGHT - 50)
                if (x, y) not in self.used_positions:
                    break
                tries += 1

        self.used_positions.add((x, y))
        return x, y

        
    def organize_subcontractors(sel, temp_subcontractors_list: List[Tuple]):

        organized_subcontractors = []
        nesting_stack = []

        for tier_level, subcontractor_info in temp_subcontractors_list:
            # Create a new node combining subcontractor info and tier level
            current_node = {**subcontractor_info, "tier": tier_level}
        
            # Remove any nodes from the stack that are at the same or deeper level
            # We only want to keep a valid parent (i.e., one level above)
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

        # Return the final nested structure
        return organized_subcontractors


    def extract_data(self, form_html: str):
        selector = Selector(form_html)
        
        # --Storing ContractInformation--
        if True:
        # try: 
            store_contract_info = ContractInformation()

            store_contract_info.contract_description = str(re.sub(r'\s+', ' ', selector.xpath(self.xpath_selectors.contract_description).get())).strip()
            store_contract_info.contract_number =  str(re.sub(r'\s+', ' ', selector.xpath(self.xpath_selectors.contract_number).get())).strip()
            store_contract_info.organization =  str(re.sub(r'\s+', ' ', selector.xpath(self.xpath_selectors.organization).get())).strip()
            store_contract_info.status =  str(re.sub(r'\s+', ' ', selector.xpath(self.xpath_selectors.status).get())).strip()
            store_contract_info.dates =  str(re.sub(r'\s+', ' ', selector.xpath(self.xpath_selectors.dates).get())).strip()
            store_contract_info.prime_contractor =  str(re.sub(r'\s+', ' ', selector.xpath(self.xpath_selectors.prime_contractor).get())).strip()
    

            contract_info_result = store_contract_info.to_dict()

        # except Exception as e:
        #     self.logger.error(f"Error parsing data from contract_info: {e}")
        #     return None



        # --Extracting data for AwardSummary--
        award_summary_result = {}
        tr_tags = selector.xpath('.//table[contains(., "Award & Payment Summary")]/following-sibling::table[1]/tbody/tr')
        for tr_tag in tr_tags:
            td_tags_text = [re.sub(r'\s+', ' ', td_tag.xpath('string()').get()).strip() for td_tag in tr_tag.xpath('./td')]
            if not td_tags_text or not td_tags_text[0]: # if first key is empty then its mean td list is not have relevant values
                continue
            key_name = td_tags_text[0].lower().replace(' ', '_')
            
            try:
                store_award_summary = AwardSummary()

                store_award_summary.award=td_tags_text[1] if len(td_tags_text) > 1 else None
                store_award_summary.award_percentage=td_tags_text[2] if len(td_tags_text) > 2 else None
                store_award_summary.payments=td_tags_text[3] if len(td_tags_text) > 3 else None
                store_award_summary.payments_percentage=td_tags_text[4] if len(td_tags_text) > 4 else None
                store_award_summary.difference=td_tags_text[5] if len(td_tags_text) > 5 else ''
                
                award_summary_result[key_name] = store_award_summary.to_dict()
            
            except Exception as e:
                logger.error(f"Error parsing award row {td_tags_text}: {e}")



            # --Extracting data for Subcontractors--
            temp_subcontractors_list = []
            tr_tags = selector.xpath('.//table[contains(., "Subcontractors")]/following-sibling::table[1]/tbody/tr[position() > 1]')

            for tr_tag in tr_tags:
                
                try:
                    store_subcontractor = Subcontractors()

                    store_subcontractor.name =  ''.join(tr_tag.xpath(self.xpath_selectors.name).getall()).strip()
                    
                    tier = tr_tag.xpath(self.xpath_selectors.tier).re(r'_(\d+)\.') # Use src (EX: '/images/img_sub_tier_1.png') with re to find number only
                    store_subcontractor.tier = tier[0] if tier else 1

                    type_of_goal = tr_tag.xpath(self.xpath_selectors.type_of_goal).get()
                    store_subcontractor.type_of_goal = type_of_goal if type_of_goal else 'No'
                    store_subcontractor.included_in_goal = True if type_of_goal else False

                    contracted_amount = tr_tag.xpath(self.xpath_selectors.contracted_amount).getall()
                    store_subcontractor.contracted_amount = f"{contracted_amount[0].strip()} ({contracted_amount[1].strip()})" if contracted_amount and len(contracted_amount) == 2 else ''
    

                    paid_amount = tr_tag.xpath(self.xpath_selectors.paid_amount).getall()
                    store_subcontractor.paid_amount = f"{paid_amount[0].strip()} ({paid_amount[1].strip()})" if paid_amount and len(paid_amount) == 2 else ''
                    # store_subcontractor.paid_percentage =  paid_amount[1].strip() if len(paid_amount) > 1 else None

            
                    temp_subcontractors_list.append(
                        (int(store_subcontractor.tier), store_subcontractor.to_dict())
                    )
                    
                except Exception as e:
                    logger.error(f"Error parsing subcontractor tr_tag: {e}")
            
            subcontractors_results = self.organize_subcontractors(temp_subcontractors_list)

        return {
            "contract_info": contract_info_result,
            "award_summary": award_summary_result,
            "subcontractors": subcontractors_results
        }


    def launch_browser(self, search_term:str, index: int):
        try:
            x, y = self.get_smart_random_position(index)
            with SB(
                uc=True, 
                user_data_dir=r"D:\Web Scraping\Client Projects\yogi291\Bot for (newnycontracts)\source code\My Profile",
                incognito=True
            ) as sb:
                
                # sb.sleep(10)
                sb.set_window_size(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
                sb.set_window_position(x, y)
                
                # sb.open(self.url)
                sb.activate_cdp_mode(self.url)
                sb.wait_for_element_visible(self.xpath_selectors.search_MTA_button)
                sb.cdp.click(self.xpath_selectors.search_MTA_button)
                sb.wait_for_element_visible(self.xpath_selectors.contract_iframe_tag)
                sb.cdp.switch_to_frame(self.xpath_selectors.contract_iframe_tag)
                sb.cdp.type(self.xpath_selectors.contract_number_input, f"{search_term}")
                sb.cdp.click(self.xpath_selectors.search_button)

                try:
                    sb.cdp.wait_for_element_visible('.//strong[contains(text(), "Search Results")]', timeout=30)
                    match_link = sb.cdp.is_element_visible(f'.//a[text() = "{search_term.upper()}"]')
                    print(f"Match_link: {match_link}")
                    if not match_link:
                        self.logger.warning(f"No match found for contract: {search_term}")
                        return None
                except Exception as e:
                    self.logger.warning(f"Error finding contract link for {search_term}: {e}")
                    return None
                
                
                if match_link:
                    sb.cdp.click(f'.//a[text() = "{search_term.upper()}"]')
                    page_model_iframe = sb.cdp.wait_for_element_visible(self.xpath_selectors.page_model_iframe, timeout = 30)

                    sb.cdp.switch_to_frame(page_model_iframe)
                    body_html_tag = sb.cdp.find_element(self.xpath_selectors.final_form_tag, timeout = 30)
                    if body_html_tag:
                        body_html = body_html_tag.get_attribute("outerHTML")
                        return body_html
                    else:
                        self.logger.warning(f"No body_html_tag found for the search term: {search_term}")
                        return None
                else:
                    self.logger.warning(f"No match found for the search term: {search_term}")
                    return None

        except Exception as e:
                self.logger.error(f"Error in launch_browser: {e}")   
                return None
        
    def calculate_window_position(self, index, window_width, window_height, columns):
        row = index // columns
        col = index % columns
        x = col * window_width
        y = row * window_height
        return x, y

    def _scrape_single(self, search_term: str, index: int) -> Optional[Dict]:
        form_html = self.launch_browser(search_term, index)
        return self.extract_data(form_html) if form_html else None

    def scrape_contracts(self, search_terms: List[str]) -> Dict[str, Optional[Dict]]:
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._scrape_single, term, idx): term
                for idx, term in enumerate(search_terms)
            }
            for future in as_completed(futures):
                term = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                   self.logger.error(f"Thread failed for {term}: {e}")
        return results


if __name__ == '__main__':
  if __name__ == '__main__':
    search_terms = [
        "e30645", "p36719", #"ch058B" , "p36721", "1000144457",
        # "w32808", "c40838", "a37130", "tn87", "aw73"
    ]

    scraper = Contracts_Scraper()
    results = scraper.scrape_contracts(search_terms)
    
    # with open("debug.html", encoding="utf-8") as f:
    #     form_html = f.read()
    # results = scraper.extract_data(form_html)
    # import pprint
    # pprint.pprint(results)

    # Save results
    import json
    with open("basic_contracts_data.json", "w") as f:
        json.dump(results, f, indent=4)