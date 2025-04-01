import json
import os
from time import sleep
from dotenv import load_dotenv
from openai import OpenAI
import subprocess
from datetime import datetime, timedelta  # Added timedelta

# OpenAI model configuration
OPENAI_MODEL = "gpt-4o-2024-08-06"

def get_fundraising_news(company_name):
    try:
        print(f"\nSearching news for: {company_name}")
        
        # Create Node.js script for google-news-scraper
        script = f'''
const googleNewsScraper = require('google-news-scraper');

(async () => {{
    console.log("Starting search for: {company_name}");
    const searchTerm = '{company_name} fundraise valuation';  // Added quotes around company name
    console.log("Search term:", searchTerm);
    
    try {{
        const articles = await googleNewsScraper({{
            searchTerm: searchTerm,
            prettyURLs: false,
            timeframe: "3y",
            puppeteerArgs: ['--no-sandbox']
        }});
        console.log("Articles found:", articles.length);
        console.log(JSON.stringify(articles));
    }} catch (error) {{
        console.error("Error during scraping:", error);
    }}
}})();
'''
        print("Creating temporary script...")
        # Write temporary Node.js script
        with open('temp_scraper.js', 'w') as f:
            f.write(script)

        print("Executing Node.js script...")
        result = subprocess.run(['node', 'temp_scraper.js'], 
                              capture_output=True, 
                              text=True)
        
        # Clean up temporary file
        os.remove('temp_scraper.js')
        
        if result.stdout:
            try:
                # Find the JSON array in the output
                start_idx = result.stdout.find('[')
                end_idx = result.stdout.rfind(']') + 1
                
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = result.stdout[start_idx:end_idx]
                    articles = json.loads(json_str)
                    print(f"Successfully parsed {len(articles)} articles")
                    return articles
                else:
                    print("No JSON array found in output")
                    return []
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {e}")
                print("Raw output:", result.stdout[:200] + "...") # Show first 200 chars
                return []
        return []
    except Exception as e:
        print(f"Error scraping news for {company_name}: {e}")
        return []

def analyze_fundraising_news(client, articles, company_name):
    if not articles:
        print(f"No articles found for {company_name}")
        return {
            "recent_raise": None,
            "valuation": None,
            "analysis_date": datetime.now().isoformat(),
            "announcement_date": None,
            "source_article": None,
            "source_publisher": None
        }
    
    # Print the first few articles for debugging
    print(f"\nFound {len(articles)} articles for {company_name}:")
    for i, article in enumerate(articles[:3]):
        print(f"\nArticle {i+1}:")
        print(f"Title: {article.get('title', 'No title')}")
        print(f"Date: {article.get('time', 'No date')}")
        print(f"Source: {article.get('source', 'No source')}")
    
    articles_text = "\n".join([f"Title: {a['title']}\nLink: {a['link']}\nPublished: {a.get('time', 'No date')}\n" for a in articles[:5]])
    
    prompt = f"""Analyze these news articles about {company_name} and extract the most recent fundraising information:

{articles_text}

Guidelines for accepting fundraising information:
1. MOST IMPORTANT: Sort articles by date and focus on the most recent fundraising event first
2. Only use older articles if they provide additional context about the most recent round
3. Prioritize articles from major tech/business publications (e.g., TechCrunch, Bloomberg, Reuters)
4. For the most recent round:
   - Accept fundraising numbers if reported by reliable sources
   - For valuation, use the most recently reported number
   - If a range is given, use the confirmed final number or the lower end
    - Extract and store the exact URL of the article whose numbers you ultimately use
5. Ignore older fundraising rounds entirely, even if they have more complete information

For each article, evaluate in this order:
1. Date: Is this the most recent coverage?
2. Source reliability: Is it a major publication?
3. Specificity: Does it provide concrete numbers?
4. Confirmation: Are the numbers verified by other sources?"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": """You are a balanced financial data analyzer focused on startup fundraising news.
Your primary goal is to find the MOST RECENT fundraising information:
- Sort articles chronologically and start with the newest
- Only return numbers from the most recent fundraising round
- Ignore older rounds completely
- Format dates as 'Month Day, Year' (e.g., 'April 18, 2024')
Return null only if you cannot find reliable information about the most recent round."""},
            {"role": "user", "content": prompt}
        ],
        functions=[{
            "name": "extract_fundraising_data",
            "description": "Extract confirmed fundraising data from news articles",
            "parameters": {
                "type": "object",
                "properties": {
                    "recent_raise": {
                        "type": ["number", "null"],
                        "description": "Most recent fundraising amount in millions USD"
                    },
                    "valuation": {
                        "type": ["number", "null"],
                        "description": "Latest company valuation in millions USD"
                    },
                    "announcement_date": {
                        "type": ["string", "null"],
                        "description": "Date when the fundraising was announced (format: 'Month Day, Year')"
                    },
                    "source_article": {
                        "type": ["string", "null"],
                        "description": "Title of the article reporting the fundraising"
                    },
                                        "source_publisher": {
                        "type": ["string", "null"],
                        "description": "Name of the publication that reported the fundraising"
                    },
                    "source_url": {
                        "type": ["string", "null"],
                        "description": "URL of the article reporting the fundraising"
                    },
                    "analysis_date": {
                        "type": "string",
                        "description": "Date when this analysis was performed"
                    }
                },
                "required": ["recent_raise", "valuation", "announcement_date", "source_article", "source_publisher", "analysis_date"]
            }
        }],
        function_call={"name": "extract_fundraising_data"},
        temperature=0.7
    )

    return json.loads(response.choices[0].message.function_call.arguments)

def main():
    load_dotenv()
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Setup paths
    base_path = os.path.dirname(os.path.dirname(__file__))
    data_path = os.path.join(base_path, 'data')
    final_portfolio_path = os.path.join(data_path, 'portfolio_3_cf_analyzed.json')
    valuation_path = os.path.join(data_path, 'portfolio_4_cf_valuations.json')
    news_path = os.path.join(data_path, 'news.json')
    
    # Ensure data directory exists
    os.makedirs(data_path, exist_ok=True)
    
    # Load existing valuation data
    try:
        with open(valuation_path, 'r') as f:
            companies_with_valuation = json.load(f)
            # Create lookup dictionary
            existing_data = {c['name']: c for c in companies_with_valuation}
    except (FileNotFoundError, json.JSONDecodeError):
        companies_with_valuation = []  # Initialize empty list
        existing_data = {}
    
    # Load portfolio data
    try:
        with open(final_portfolio_path, 'r') as f:
            companies = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading portfolio data: {e}")
        return

    # Load existing news data
    try:
        with open(news_path, 'r') as f:
            news_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        news_data = {}

    # Create a set of existing company names for quick lookup
    existing_company_names = {company['name'] for company in companies_with_valuation}
    
    # Process each company
    for i, company in enumerate(companies):
        company_name = company['name']
        
        # Check if company exists and needs update (not updated in last 7 days)
        needs_update = True
        if company_name in existing_company_names:
            existing_company = existing_data[company_name]
            last_updated = existing_company.get('fundraising_data_updated')
            
            if last_updated:
                try:
                    last_updated_date = datetime.fromisoformat(last_updated).date()
                    today = datetime.now().date()
                    if today == last_updated_date:
                        print(f"Skipping {company_name} - already updated today")
                        needs_update = False
                    elif (today - last_updated_date).days < 7:
                        print(f"Skipping {company_name} - updated recently on {last_updated_date}")
                        needs_update = False
                except ValueError:
                    pass
        else:
            print(f"New company found: {company_name}")

        if needs_update:
            try:
                # Get and analyze news
                articles = get_fundraising_news(company_name)
                print(f"Found {len(articles)} articles for {company_name}")
                
                # Update news data for this company
                news_data[company_name] = {
                    'articles': articles,
                    'updated_at': datetime.now().isoformat()
                }
                
                # Save news data after each company
                with open(news_path, 'w') as f:
                    json.dump(news_data, f, indent=2)
                
                # Analyze articles
                fundraising_data = analyze_fundraising_news(client, articles, company_name)
                print(f"Analysis complete for {company_name}: {fundraising_data}")
                
                # Update company data
                company_with_valuation = existing_data.get(company_name, company.copy())
                company_with_valuation.update({
                    'recent_raise': fundraising_data.get('recent_raise'),
                    'valuation': fundraising_data.get('valuation'),
                    'fundraising_announcement_date': fundraising_data.get('announcement_date'),
                    'fundraising_source_article': fundraising_data.get('source_article'),
                    'fundraising_source_publisher': fundraising_data.get('source_publisher'),
                    'fundraising_source_url': fundraising_data.get('source_url'),
                    'fundraising_data_updated': datetime.now().isoformat()
                })
                
                # Update in the existing data dictionary
                existing_data[company_name] = company_with_valuation
                
                # Save the entire data after each update
                with open(valuation_path, 'w') as f:
                    json.dump(list(existing_data.values()), f, indent=2)
                    
            except Exception as e:
                print(f"Error processing {company_name}: {e}")
            
            sleep(2)  # Rate limiting
        
    print(f"Processing complete:")
    print(f"- Updated fundraising data where needed")
    print(f"- Saved news articles to: {news_path}")
    print(f"- Saved valuation data to: {valuation_path}")

if __name__ == "__main__":
    main()