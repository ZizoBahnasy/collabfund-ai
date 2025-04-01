# initial enrichment

from bs4 import BeautifulSoup
import json
import requests
import time
from urllib.parse import urlparse
import os

def clean_company_name(raw_name):
    if not raw_name:
        return None
        
    # Common separators and their replacements
    separators = [' | ', ' - ', ' – ', ' — ', ' • ', ': ', ' \u2022 ']
    
    # Take the last part if it's the company name, otherwise take the first part
    for sep in separators:
        if sep in raw_name:
            parts = [p.strip() for p in raw_name.split(sep)]
            # If the last part is a single word, it's likely the company name
            if len(parts[-1].split()) <= 2:
                return parts[-1]
            # Otherwise take the first part
            return parts[0]
    
    # Remove common suffixes
    suffixes = [
        'Home', 'Homepage', 'Official Site', 'Official Website',
        'Inc', 'LLC', 'Ltd', 'Limited', 'Corp', 'Corporation'
    ]
    name = raw_name
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-(len(suffix))].strip()
            
    return name.strip()

def get_company_info(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try to get company name from meta tags
        name = None
        description = None
        
        # Check meta tags
        og_title = soup.find('meta', property='og:title')
        twitter_title = soup.find('meta', property='twitter:title')
        meta_title = soup.find('meta', {'name': 'title'})
        
        if og_title:
            name = og_title.get('content')
        elif twitter_title:
            name = twitter_title.get('content')
        elif meta_title:
            name = meta_title.get('content')
        else:
            title = soup.find('title')
            if title:
                name = title.text.strip()
        
        # Get description
        og_desc = soup.find('meta', property='og:description')
        twitter_desc = soup.find('meta', property='twitter:description')
        meta_desc = soup.find('meta', {'name': 'description'})
        
        if og_desc:
            description = og_desc.get('content')
        elif twitter_desc:
            description = twitter_desc.get('content')
        elif meta_desc:
            description = meta_desc.get('content')
            
        return {
            'name': name,
            'description': description
        }
    except Exception as e:
        print(f"Error fetching {url}: {str(e)}")
        return None

def enrich_companies():
    # Define data path
    base_path = os.path.dirname(os.path.dirname(__file__))
    data_path = os.path.join(base_path, 'data')
    
    # Create data directory if it doesn't exist
    os.makedirs(data_path, exist_ok=True)
    
    # Define input and output paths
    input_path = os.path.join(data_path, 'portfolio_1_cf_extracted.json')
    output_path = os.path.join(data_path, 'portfolio_2_cf_enriched.json')
    
    try:
        with open(output_path, 'r') as f:  # Changed from enriched_path to output_path
            content = f.read().strip()
            if not content:
                existing_data = []
            else:
                try:
                    existing_data = json.loads(content)
                except json.JSONDecodeError:
                    print("Warning: Invalid JSON in portfolio_2_cf_enriched.json, starting fresh")
                    existing_data = []
    except FileNotFoundError:
        existing_data = []

    # Create set of already processed URLs
    processed_urls = {company['url'] for company in existing_data}

    # Load extracted companies data
    with open(input_path, 'r') as f:  # Changed from companies_path to input_path
        companies = json.load(f)

    new_count = 0
    for i, company in enumerate(companies):
        if company['url'] in processed_urls:
            print(f"Skipping {company['url']} - already processed")
            continue

        print(f"Processing {i+1}/{len(companies)}: {company['url']}")
        
        info = get_company_info(company['url'])
        if info:  # Only process if we got valid info
            enriched_company = company.copy()
            enriched_company['description'] = info.get('description')
            
            existing_data.append(enriched_company)
            new_count += 1
            
            # Save after each successful enrichment
            with open(output_path, 'w') as f:  # Changed from enriched_path to output_path
                json.dump(existing_data, f, indent=2)
        
        time.sleep(1)  # Rate limiting

    print(f"Processed {new_count} new companies, total {len(existing_data)} companies")

if __name__ == "__main__":
    enrich_companies()