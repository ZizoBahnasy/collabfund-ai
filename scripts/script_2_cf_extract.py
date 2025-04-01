from bs4 import BeautifulSoup
import json
import requests
import time
import os

def extract_companies():
    # Define data path
    base_path = os.path.dirname(os.path.dirname(__file__))
    data_path = os.path.join(base_path, 'data')
    
    # Create data directory if it doesn't exist
    os.makedirs(data_path, exist_ok=True)
    
    companies = []
    seen_urls = set()  # Track unique URLs to prevent duplicates
    
    # Collaborative Fund has a single portfolio page
    url = "https://collabfund.com/portfolio/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find all portfolio items - on Collaborative Fund they're in a grid with class "grid-item"
    portfolio_items = soup.find_all('div', class_='grid-item')
    
    if not portfolio_items:
        print("No portfolio items found. The website structure might have changed.")
        return
        
    print(f"Found {len(portfolio_items)} portfolio items")
    
    for item in portfolio_items:
        # Extract company name from the heading inside the title-block
        title_block = item.find('a', class_='title-block')
        if not title_block:
            continue
            
        name_element = title_block.find('h3')
        if not name_element:
            continue
            
        # Clean up the name (remove <em> tags)
        name = name_element.text.strip()
        
        # Extract URL
        company_url = title_block.get('href', "")
        
        # Skip if we've seen this URL before and it's not empty
        if company_url and company_url in seen_urls:
            continue
            
        if company_url:
            seen_urls.add(company_url)
        
        # Get category/sector
        category = ""
        pill_button = item.find('button', class_='pill')
        if pill_button:
            sector_label = pill_button.find('span', class_='sector-label--full')
            if sector_label:
                category = sector_label.text.strip()
        
        company = {
            'name': name,
            'url': company_url,
            'category': category
        }
        companies.append(company)
    
    print(f"Extracted {len(companies)} companies from Collaborative Fund")

    # Save to JSON file
    output_path = os.path.join(data_path, 'portfolio_1_cf_extracted.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(companies, f, indent=2)

    print(f"Extracted {len(companies)} unique companies to {output_path}")

if __name__ == "__main__":
    extract_companies()