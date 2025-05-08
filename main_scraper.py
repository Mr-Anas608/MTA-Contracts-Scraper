from aiohttp import ClientSession, ClientError, ClientResponseError
from typing import Optional, Dict, List, Any, Tuple
from utils.helpers import HtmlParser, HtmlPageScraper
from utils.helpers import load_input, save_data
from logs.custom_logging import setup_logging
import logging, time, asyncio, random
import traceback


logger = setup_logging(console_level=logging.DEBUG)

class MySuperFastScraper:
    """
    Fast asynchronous scraper for contract information using aiohttp and reverse engineering techniques.
    
    Handles searching for contracts and retrieving their detailed information
    with proper error handling, retries, and rate limiting.
    """
    
    def __init__(self, search_terms: List[str], batch_size: int = 50, max_retries:int = 2):
        """
        Initialize the scraper with search terms and helper classes.
        
        Args:
            search_terms: List of contract terms to search for
        """
        self.html_page_scraper = HtmlPageScraper()
        self.html_parser = HtmlParser()
        self.search_terms = search_terms
        self.logger = logger
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.base_delay = 1.0
        self.max_delay = 3.0
        
    async def _fetch_with_retry(self, session: ClientSession, term: str = None, 
                              matched_contract: Dict[str, str] = None) -> Optional[str]:
        """
        Fetch HTML with retry logic and adaptive delays.
        
        Args:
            session: Active ClientSession
            term: Contract number to search for
            matched_contract: Contract details for final page
            
        Returns:
            HTML content as string or None if all retries failed
        """
        current_delay = self.base_delay
        retries = 0
        
        while retries < self.max_retries:
            try:
                # Add small random delay for initial requests to avoid detection
                delay = random.uniform(current_delay, current_delay + 1)
                await asyncio.sleep(delay)
                
                if term:
                    html_result = await self.html_page_scraper.request_html(session, contract_name=term)
                elif matched_contract:
                    html_result = await self.html_page_scraper.request_html(session, matched_contract=matched_contract)
                else:
                    self.logger.error("❌ No term or matched contract provided")
                    return None
                    
                if html_result:
                    return html_result
                    
                # If we got None but no exception, increase retry count
                retries += 1
                current_delay = min(current_delay * 2, self.max_delay)
                self.logger.warning(f"⚠️ Fetch attempt {retries} failed, retrying in {current_delay:.2f}s")
                
            except ClientResponseError as e:
                if e.status == 429:  # Too Many Requests
                    retries += 1
                    current_delay = min(current_delay * 3, self.max_delay * 2)  # More aggressive backoff
                    self.logger.warning(f"⚠️ Rate limited (429), retrying in {current_delay:.2f}s")
                    await asyncio.sleep(current_delay)
                else:
                    self.logger.error(f"❌ HTTP error {e.status}: {str(e)}")
                    retries += 1
                    current_delay = min(current_delay * 2, self.max_delay)
                    await asyncio.sleep(current_delay)
            except ClientError as e:
                self.logger.error(f"❌ Client error: {str(e)}")
                retries += 1
                current_delay = min(current_delay * 2, self.max_delay)
                await asyncio.sleep(current_delay)
            except Exception as e:
                self.logger.error(f"❌ Unexpected error during fetch: {str(e)}")
                self.logger.debug(traceback.format_exc())
                retries += 1
                current_delay = min(current_delay * 2, self.max_delay)
                await asyncio.sleep(current_delay)
                
        self.logger.error(f"❌ All {self.max_retries} fetch attempts failed")
        return None
        
    async def scrape_contract_matches(self) -> List[Dict[str, str]]:
        """
        Search for matches of all contract terms.
        
        Returns:
            List of matched contracts with their details
        """
        matched_contracts = []
        mismatched_contracts = []
        
        # Use a single session for all search requests
        async with ClientSession() as session:
            try:
                # Process search terms in batches to control concurrency
                batch_size = self.batch_size  # Adjust based on target site's limits
                for i in range(0, len(self.search_terms), batch_size):
                    batch = self.search_terms[i:i+batch_size]
                    batch_tasks = []
                    
                    # Create tasks for this batch
                    for term in batch:
                        task = asyncio.create_task(self._fetch_with_retry(session, term=term))
                        batch_tasks.append((term, task))
                    
                    # Process results from this batch
                    for term, task in batch_tasks:
                        try:
                            html_result = await task
                            if html_result:
                                match_contract = self.html_parser.search_page_parser(html_result, term)
                                if match_contract:
                                    self.logger.debug(f"Found match for contract: {term}")
                                    matched_contracts.append(match_contract)
                                else:
                                    self.logger.warning(f"⚠️  No match found for contract: {term}")
                                    mismatched_contracts.append({term: match_contract})
                            else:
                                self.logger.warning(f"⚠️ Failed to fetch search page for: {term}")
                        except Exception as e:
                            self.logger.error(f"❌ Error processing search for {term}: {str(e)}")
                            self.logger.debug(traceback.format_exc())
                    
                    # Small delay between batches to avoid overwhelming the server
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                
                self.logger.info(f"Found {len(matched_contracts)} matches from {len(self.search_terms)} terms")
                return matched_contracts, mismatched_contracts
                
            except Exception as e:
                self.logger.error(f"❌ Error during contract matching: {str(e)}")
                self.logger.debug(traceback.format_exc())
                return []
            
    async def scrape_contract_details(self, matched_contracts: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch and parse detailed information for matched contracts.
        
        Args:
            matched_contracts: List of matched contract dictionaries
            
        Returns:
            Dictionary mapping contract names to their parsed details
        """
        final_result = {}
        if not matched_contracts:
            self.logger.warning("No matched contracts to process")
            return final_result
            
        # Use a single session for all detail requests
        async with ClientSession() as session:
            # Process contracts in batches
            batch_size = self.batch_size  
            for i in range(0, len(matched_contracts), batch_size):
                batch = matched_contracts[i:i+batch_size]
                batch_tasks = []
                
                # Create tasks for this batch
                for matched_contract in batch:
                    contract_name = next(iter(matched_contract.keys()))
                    contract_cid = matched_contract[contract_name]
                    
                    # Format contract info for request_html method
                    contract_info = {
                        "contract_name": contract_name,
                        "contract_cid": contract_cid
                    }
                    
                    task = asyncio.create_task(self._fetch_with_retry(session, matched_contract=contract_info))
                    batch_tasks.append((contract_name, task))
                
                # Process results from this batch
                for contract_name, task in batch_tasks:
                    try:
                        html_result = await task
                        if html_result:

                            final_page_dict = self.html_parser.final_page_parser(html_result)
                            if final_page_dict:
                                self.logger.debug(f"Parsed details for: {contract_name}")
                                final_result[contract_name] = final_page_dict
                            else:
                                self.logger.warning(f"⚠️ Failed to parse details for: {contract_name}")
                        else:
                            self.logger.warning(f"⚠️ Failed to fetch details for: {contract_name}")
                    except Exception as e:
                        self.logger.error(f"❌ Error processing details for {contract_name}: {str(e)}")
                        self.logger.debug(traceback.format_exc())
                
                # Delay between batches
                await asyncio.sleep(random.uniform(1.0, 2.0))
                
        self.logger.info(f"Successfully processed {len(final_result)} of {len(matched_contracts)} contracts")
        return final_result
    
    async def scrape_contracts(self) -> Dict[str, Dict[str, Any]]:
        """
        Main entry point for the scraper. Searches for and fetches details for all contracts.
        
        Returns:
            Dictionary mapping contract names to their parsed details
        """
        start_time = time.perf_counter()
        self.logger.info(f"Starting scrape for {len(self.search_terms)} contract terms")
        
        try:
            # First get all the matches
            matched_contracts, mismatched_contracts = await self.scrape_contract_matches()
            
            if not matched_contracts:
                self.logger.warning("No matched contracts found")
                return {}
                
            # Then fetch details for all matches
            final_result = await self.scrape_contract_details(matched_contracts)
            
            # Calculate and log performance metrics
            end_time = time.perf_counter()
            duration = end_time - start_time
            success_rate = len(final_result) / len(self.search_terms) if self.search_terms else 0
            
            self.logger.info(f"✅ Scraping completed in {duration:.2f} seconds")
            self.logger.info(f"📊 Success rate: {success_rate:.2%} ({len(final_result)}/{len(self.search_terms)})")
            
            return final_result, mismatched_contracts
            
        except Exception as e:
            self.logger.error(f"❌ Error in main scrape_contracts method: {str(e)}")
            self.logger.debug(traceback.format_exc())
            return {}
        

async def main():
    search_terms = load_input()
    my_scraper = MySuperFastScraper(search_terms)
    final_results, mismatched_contracts = await my_scraper.scrape_contracts()
    save_data(final_results)

    if mismatched_contracts:
        import json
        with open("output_data/mismatched_contracts_debug.json", "w", encoding="utf-8") as f:
            json.dump(mismatched_contracts, f, indent=4, ensure_ascii=False)
            
if __name__ == "__main__":
    asyncio.run(main())