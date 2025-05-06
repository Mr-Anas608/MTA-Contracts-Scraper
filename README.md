# MTA Contracts Scraper

A robust, multi-threaded web scraper designed to extract detailed contract information from the MTA (Metropolitan Transportation Authority) New NY Contracts database.

## 🚀 Overview

This tool helps you gather comprehensive contract data from the MTA website, including contract details, award summaries, and subcontractor information. Perfect for analysts, researchers, and organizations that need reliable MTA contract intelligence.

## ✨ Features

- **Multi-threaded Performance**: Scrape multiple contracts simultaneously for efficient data collection
- **Smart Window Management**: Automatic positioning of browser windows to avoid overlap
- **Robust Error Handling**: Multiple retry mechanisms and detailed logging
- **Structured Data Output**: Clean, organized JSON output with hierarchical subcontractor relationships
- **Comprehensive Data Extraction**: Captures all contract details, award summaries, and subcontractor information

## 📋 Data Extracted

For each contract, the scraper extracts:

- **Contract Information**: Description, number, organization, status, dates, prime contractor
- **Award Summary**: Contract awards and payments with percentage breakdowns
- **Subcontractor Details**: Complete subcontractor hierarchy with tier relationships, contracted amounts, and payment data

## 🛠️ Installation

1. Clone this repository:
   ```
   git clone https://github.com/Mr-Anas608/MTA-Contracts-Scraper.git
   cd MTA-Contracts-Scraper
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## 🔧 Usage

### Basic Usage

```python
from scraper import ContractsScraper

# Initialize the scraper
scraper = ContractsScraper(max_workers=6)

# Define the contract numbers to scrape
contract_numbers = ["e30645", "p36719", "ch058B"]

# Run the scraper
results = scraper.scrape_contracts(contract_numbers)

# Save the results to a JSON file
import json
with open("contracts_data.json", "w") as f:
    json.dump(results, f, indent=4)
```

### Advanced Configuration

You can customize the scraper behavior:

```python
# Initialize with custom settings
scraper = ContractsScraper(
    max_workers=10,  # Number of concurrent browser sessions
    retry_attempts=3  # Number of retry attempts for failed operations
)
```

## 📊 Sample Output

```json
[
    {
        "e30645": {
            "contract_info": {
                "contract_description": "Design and Construction Services for Escalator Replacements in Manhattan and Queens",
                "contract_number": "E30645",
                "organization": "MTA Construction & Development",
                "status": "Open",
                "dates": "12/29/2022 to 8/22/2025",
                "prime_contractor": "J-Track LLC"
            },
            "award_summary": {
                "prime_contract": {
                    "award": "$48,394,000",
                    "award_percentage": "",
                    "payments": "$38,795,897",
                    "payments_percentage": "",
                    "difference": ""
                },
                "for_credit": {
                    "award": "$10,646,680",
                    "award_percentage": "22.0%",
                    "payments": "$7,081,574",
                    "payments_percentage": "18.3%",
                    "difference": "3.7% below goal"
                },
                "for_credit_to_mbe_goal": {
                    "award": "$4,839,400",
                    "award_percentage": "10.0%",
                    "payments": "$5,508,970",
                    "payments_percentage": "14.2%",
                    "difference": "4.2% above goal"
                },
                "for_credit_to_sdvob_goal": {
                    "award": "$967,880",
                    "award_percentage": "2.0%",
                    "payments": "$0",
                    "payments_percentage": "0.0%",
                    "difference": "2.0% below goal"
                },
                "for_credit_to_wbe_goal": {
                    "award": "$4,839,400",
                    "award_percentage": "10.0%",
                    "payments": "$1,572,604",
                    "payments_percentage": "4.1%",
                    "difference": "5.9% below goal"
                }
            },
            "subcontractors": [
                {
                    "name": "AI ENGINEERS, INC DBA N/A",
                    "tier": 1,
                    "type_of_goal": "Yes",
                    "included_in_goal": true,
                    "contracted_amount": "$625,000 (1.3%)",
                    "paid_amount": "$566,203 (1.5%)"
                },
                {
                    "name": "All Points Communications, Inc.",
                    "tier": 1,
                    "type_of_goal": "Yes",
                    "included_in_goal": true,
                    "contracted_amount": "$366,623 (0.8%)",
                    "paid_amount": "$252,101 (0.6%)"
                },
                {
                    "name": "APC Specialist, LLC",
                    "tier": 1,
                    "type_of_goal": "Yes",
                    "included_in_goal": true,
                    "contracted_amount": "$117,000 (0.2%)",
                    "paid_amount": "$143,800 (0.4%)"
                }
            ]
        }
    }
]
        
```

## 📝 Requirements

- Python 3.7+
- SeleniumBase
- Parsel
- Tenacity
- screeninfo


## 📞 Contact

If you have any questions or need assistance with this tool, please reach out to [muhammad.anas.yaseen.s608@gmail.com].

---

*This tool is not affiliated with, endorsed by, or in any way officially connected with the Metropolitan Transportation Authority (MTA).*