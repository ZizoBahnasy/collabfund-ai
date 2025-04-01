import json
import openai
import os
from time import sleep
from dotenv import load_dotenv
from openai import OpenAI

# Load .env from agent directory
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'agent', '.env'))

# OpenAI model configuration
OPENAI_MODEL = "gpt-4o-2024-08-06"

# Add at the top with other imports
INDUSTRIES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'industry_domains.json')
# Change the portfolio path temporarily
PORTFOLIO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'portfolio_3_cf_analyzed.json')

# Add this function to load/save industry domains
def load_industry_domains():
    try:
        with open(INDUSTRIES_PATH, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        # Initialize with default domains from Collaborative FUnd's website
        default_domains = {
            "Food",
            "Money",
            "Health",
            "Climate"
        }
        save_industry_domains(default_domains)
        return default_domains

def save_industry_domains(domains):
    with open(INDUSTRIES_PATH, 'w') as f:
        json.dump(list(domains), f, indent=2)

# Modify analyze_company function to include industry analysis
def analyze_company(client, company_data, current_industries):
    try:
        # Only mark as inactive if both name and description are null, or if explicitly known to be inactive
        if company_data.get('name') is None:
            return {
                "name": "Unknown - Website Inactive",
                "status": "inactive",
                "investment_thesis": "Inactive Venture - Website no longer accessible",
                "unicorn_potential": None,
                "decacorn_potential": None,
                "venture_scale_probability": None,
                "collabfund_thesis_alignment": None,
                "zizo_thesis_alignment": None,
                "excitement": None,
                "entry_barriers": "Not applicable - inactive venture",
                "barrier_difficulty": None,
                "behavior_change_requirement": None,
                "technological_complexity": None,
                "operational_complexity": None,
                "capital_intensity": None,
                "deep_tech": None,
                "industry_domains": [],
                "notes": {
                    "market_size": {
                        "description": "Not applicable - inactive venture",
                        "opportunity": None
                    },
                    "defensibility": {
                        "description": "Not applicable - inactive venture",
                        "considerations": None
                    },
                    "venture_scale_returns": {
                        "description": "Not applicable - inactive venture",
                        "risks": None
                    }
                }
            }

        # If description is null but name exists, proceed with analysis using available information
        description = company_data.get('description', 'No description available - Using alternative sources')

        # Update the prompt to include industry analysis
        # Update the prompt to include specific market size and competition details
        # Update the prompt to include venture-scale probability
        prompt = f"""Analyze this company as a highly seasoned VC partner at the firm Collaborative Fund:

URL: {company_data['url']}
Current Name: {company_data['name']}
Description: {company_data.get('description', 'No description available')}

Collaborative Fund Thesis: We support companies that live at the intersection of for-profit & for-good and which make the world a better place through innovative consumer-centered business models and products.

Zizo Thesis: I want to back companies building fundamental breakthroughs that meet these criteria:
1. Billion-person impact potential: Can this meaningfully affect how a billion people live or work?
2. Economic paradigm shifts: Does this create entirely new markets or fundamentally transform existing ones?
3. Deep technical innovation: Is there significant technical differentiation that others can't easily replicate?
4. Novel experiences: Does this enable fundamentally new ways for humans to interact with technology or each other?
5. Time-travel test: Does this feel like it's pulled from 5+ years in the future?

Current industry domains in portfolio: {', '.join(sorted(current_industries))}

Please analyze:
1. Industry domains (up to 2) - choose from existing domains if applicable, or suggest new ones if needed
2. Unicorn potential (2 if already $1B+, 1 if has potential, 0 if unlikely)
3. Decacorn potential (2 if already $10B+, 1 if has potential, 0 if unlikely)
4. Venture-scale returns probability (1-10 scale, where 10 is highest probability)
5. Collaborative Fund thesis alignment (1-10 scale, based on category-defining potential, stage appropriateness, and technological innovation)
    - *Collaborative Fund thesis alignment score and detailed explanation of how or whether the company aligns with Collaborative Fund's investment focus*
6. Zizo thesis alignment (1-10 scale, based on billion-person impact potential, paradigm-shifting potential, and technical differentiation)
    - *Zizo thesis alignment score and detailed explanation of how or whether the company aligns with Zizo's investment criteria*
7. Investment excitement level (1-10 scale, considering overall potential and fit for seed-stage investment)
8. Market size estimates for the product area this company is building in:
   - Historical (2022)
   - Current (2024)
   - Future projection (2030)
   - Expected annual growth rate starting from 2024 onwards
9. Competitive landscape including:
   - Market saturation/fragmentation
   - Key competitors
   - Overall defensibility score (1-10, where 10 is strongest moats)
   - Detailed analysis of moats and competitive advantages
10. Deep Technology Assessment - Is this company building deep technology?

IMPORTANT: For the investment thesis, create a SPECIFIC thesis for THIS COMPANY ONLY. Do NOT use Collaborative Fund's general thesis statement. Instead, explain why THIS SPECIFIC COMPANY would be a good investment based on its unique value proposition, market opportunity, and alignment with Collaborative Fund's mission."""

        # Update the function parameters
        functions = [{
            "name": "analyze_investment",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Company's likely name based on the input, which might include other terms"},
                    "status": {"type": "string", "enum": ["active", "inactive"]},
                    "investment_thesis": {"type": "string", "description": "High-level investment thesis for this specific company based on Collaborative Fund's investing style"},
                    "industry_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1-2 industry domains this company operates in. Choose only the most relevant domains, don't force two if one is sufficient.",
                        "maxItems": 2,
                        "minItems": 1
                    },
                    "unicorn_potential": {"type": "integer", "enum": [0, 1, 2]},
                    "decacorn_potential": {"type": "integer", "enum": [0, 1, 2]},
                    "venture_scale_probability": {
                        "type": "integer",
                        "description": "Probability of achieving venture-scale returns on a 1-10 scale",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "collabfund_thesis_alignment": {
                        "type": "integer",
                        "description": "Alignment with Collaborative Fund's investment thesis on a 1-10 scale",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "zizo_thesis_alignment": {
                        "type": "integer",
                        "description": "Alignment with Zizo's investment thesis (2 points each: billion-person impact, economic paradigm shifts, deep technical innovation, novel experiences, future pull)",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "excitement": {
                        "type": "integer",
                        "description": "Overall excitement level for seed-stage investment on a 1-10 scale",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "entry_barriers": {
                        "type": "string",
                        "description": "Analysis of Day 1 moats: capital requirements, technical expertise needs, and significant operational/behavioral hurdles that make market entry difficult"
                    },
                    "barrier_difficulty": {
                        "type": "integer",
                        "description": "How difficult it is to overcome entry barriers and participate in this market (1-10, where 10 is extremely difficult)",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "behavior_change_requirement": {
                        "type": "integer",
                        "description": "How much success depends on changes in user behavior or market demand (1-10, where 10 requires significant behavior change)",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "technological_complexity": {
                        "type": "integer",
                        "description": "Level of technical complexity, R&D, and novel technological or scientific innovation required (1-10 scale)\nExamples:\n1: Simple CRUD app\n5: Complex ML model integration\n8: Novel cryptography implementation\n10: Quantum computing solutions, novel drug development, Nobel Prize-winning gene therapies",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "operational_complexity": {
                        "type": "integer",
                        "description": "Level of operational complexity to execute (1-10 scale)\nExamples:\n1: Pure software distribution\n5: Multi-party marketplace\n8: Healthcare provider network\n10: Autonomous vehicle fleet",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "capital_intensity": {
                        "type": "integer",
                        "description": "Level of capital required to reach meaningful scale (1-10 scale)\nExamples:\n1: Bootstrap-friendly SaaS\n5: Enterprise sales operation\n8: Semiconductor development\n10: Space launch company or home manufacturer",
                        "minimum": 1,
                        "maximum": 10
                    },
                    "deep_tech": {
                        "type": "boolean",
                        "description": "Whether the company is building deep technology based on technical complexity, R&D intensity, and novel technological or scientific innovation. Typically more than just software. This should be true if the above technological complexity field is 8 or higher."
                    },
                    "notes": {
                        "type": "object",
                        "properties": {
                            "market_size": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string", "description": "Market size analysis with specific numbers."},
                                    "opportunity": {"type": "string", "description": "Market opportunity analysis"},
                                    "2022_estimate": {
                                        "type": "number",
                                        "description": "Market size in billions USD. Must be between 0.1 and 1000. Example: use 6 for $6B, not 6000 or 6000000000",
                                        "minimum": 0.1,
                                        "maximum": 1000,
                                        "examples": [6, 10.5, 25.8]
                                    },
                                    "2024_estimate": {
                                        "type": "number",
                                        "description": "Market size in billions USD. Must be between 0.1 and 1000. Example: use 7.5 for $7.5B, not 7500 or 7500000000",
                                        "minimum": 0.1,
                                        "maximum": 1000,
                                        "examples": [7.5, 12.5, 30.2]
                                    },
                                    "2030_estimate": {
                                        "type": "number",
                                        "description": "Market size in billions USD. Must be between 0.1 and 2000. Example: use 12 for $12B, not 12000 or 12000000000",
                                        "minimum": 0.1,
                                        "maximum": 2000,
                                        "examples": [12, 25, 50.5]
                                    },
                                    "annual_growth_rate": {
                                        "type": "number",
                                        "description": "Expected annual growth rate as a percentage (e.g., 15.7 for 15.7%)",
                                        "minimum": 0,
                                        "maximum": 200,  # Allow for hypergrowth markets
                                        "examples": ["15.7", "25.4", "150.0"]
                                    }
                                },
                                "required": ["description", "opportunity", "2022_estimate", "2024_estimate", "2030_estimate", "annual_growth_rate"]
                            },
                            "defensibility": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string", "description": "Analysis of competitive advantages"},
                                    "considerations": {"type": "string", "description": "Key risks and considerations"},
                                    "market_saturation_analysis": {"type": "string", "description": "Detailed analysis of market saturation and fragmentation"},
                                    "market_saturation": {
                                        "type": "number",
                                        "description": "Market saturation percentage (0% = highly fragmented, 100% = fully saturated)",
                                        "minimum": 0,
                                        "maximum": 100
                                    },
                                    "competitors": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of key competitors in the space"
                                    }
                                 },
                                "required": ["description", "considerations", "market_saturation_analysis", "market_saturation", "competitors"]
                            },
                            "venture_scale_returns": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string", "description": "Analysis of return potential"},
                                    "risks": {"type": "string", "description": "Key risks to achieving venture scale"}
                                },
                                "required": ["description", "risks"]
                            }
                        },
                        "required": ["market_size", "defensibility", "venture_scale_returns"]
                    }, # Added missing comma
                    "required": ["name", "status", "investment_thesis", "notes", "unicorn_potential", "decacorn_potential", 
                               "venture_scale_probability", "collabfund_thesis_alignment", "zizo_thesis_alignment", "excitement",
                               "entry_barriers", "barrier_difficulty", "behavior_change_requirement", "technological_complexity",
                               "operational_complexity", "capital_intensity", "industry_domains", "deep_tech"]
                }
            }
        }]

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": """You are a senior partner at Collaborative Fund, a venture capital firm that invests at the intersection of for‑profit and for‑good.

Key aspects of your investment approach:
- You invest in early-stage companies that promise both scalable financial returns and transformative social impact.
- Your evaluation process employs a dual-filter system: first, determining if the venture’s success makes the world a better or more interesting place (Purposeful Impact), and second, assessing if a purely self‑interested investor (a “villain”) would also back it (Scalable Financial Model).
- You look for startups that disrupt or redefine market dynamics through innovative technology and business models (Market Disruption).
- You value exceptional leadership with visionary founders capable of executing transformative ideas (Exceptional Leadership).
- Your overarching thesis is encapsulated in one line: Invest in companies that seamlessly blend scalable financial returns with transformative social impact by harnessing disruptive innovation and visionary leadership.
When analyzing opportunities, evaluate:
1. Purposeful Impact: Does the venture deliver measurable positive social or environmental change?
2. Market Disruption: Does it redefine or create new market dynamics through innovation?
3. Scalable Financial Model: Is there robust potential for significant financial returns under strict, self‑interested evaluation?
4. Exceptional Leadership: Does the founding team possess the vision and capability to drive systemic change?"""},
                {"role": "user", "content": prompt}
            ],
            functions=[{
                "name": "analyze_investment",
                "description": "Analyze a potential investment opportunity",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Company's likely name based on the input, which might include other terms. Extract the core company name from the URL or description."
                        },
                        "status": {"type": "string", "enum": ["active", "inactive"]},
                        "investment_thesis": {"type": "string"},
                        "unicorn_potential": {"type": "integer", "enum": [0, 1, 2]},
                        "decacorn_potential": {"type": "integer", "enum": [0, 1, 2]},
                        "venture_scale_probability": {"type": "integer", "minimum": 1, "maximum": 10},
                        "collabfund_thesis_alignment": {
                            "type": "object",
                            "properties": {
                                "score": {"type": "integer", "minimum": 1, "maximum": 10},
                                "description": {"type": "string"}
                            },
                            "required": ["score", "description"]
                        },
                        "zizo_thesis_alignment": {
                            "type": "object",
                            "properties": {
                                "score": {"type": "integer", "minimum": 1, "maximum": 10},
                                "description": {"type": "string"}
                            },
                            "required": ["score", "description"]
                        },
                        "excitement": {"type": "integer", "minimum": 1, "maximum": 10},
                        "entry_barriers": {"type": "string"},
                        "barrier_difficulty": {"type": "integer", "minimum": 1, "maximum": 10},
                        "behavior_change_requirement": {"type": "integer", "minimum": 1, "maximum": 10},
                        "technological_complexity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "operational_complexity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "capital_intensity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "deep_tech": {"type": "boolean"},
                        "industry_domains": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 2,
                            "minItems": 1
                        },
                        "notes": {
                            "type": "object",
                            "properties": {
                                "market_size": {
                                    "type": "object",
                                    "properties": {
                                        "description": {"type": "string"},
                                        "opportunity": {"type": "string"},
                                        "2022_estimate": {
                                            "type": "number",
                                            "description": "TAM in billions USD (e.g., if market is $12B, enter 12.0). Do NOT enter full numbers like 12000000000.",
                                            "minimum": 0.1,
                                            "maximum": 1000,
                                            "examples": [12.0, 15.0, 30.0]
                                        },
                                        "2024_estimate": {
                                            "type": "number",
                                            "description": "TAM in billions USD (e.g., if market is $15B, enter 15.0). Do NOT enter full numbers like 15000000000.",
                                            "minimum": 0.1,
                                            "maximum": 1000,
                                            "examples": [15.0, 20.0, 40.0]
                                        },
                                        "2030_estimate": {
                                            "type": "number",
                                            "description": "TAM in billions USD (e.g., if market is $30B, enter 30.0). Do NOT enter full numbers like 30000000000.",
                                            "minimum": 0.1,
                                            "maximum": 2000,
                                            "examples": [30.0, 50.0, 100.0]
                                        }
                                    },
                                    "required": ["description", "opportunity", "2022_estimate", "2024_estimate", "2030_estimate", "annual_growth_rate"]
                                },
                                "defensibility": {
                                    "type": "object",
                                    "properties": {
                                        "description": {"type": "string"},
                                        "considerations": {"type": "string"},
                                        "market_saturation_analysis": {"type": "string"},
                                        "market_saturation": {"type": "number", "minimum": 0, "maximum": 100},
                                        "defensibility_score": {
                                            "type": "integer",
                                            "description": "Overall defensibility rating on a 1-10 scale relative to other seed-stage start-up opportunities, considering moats, network effects, and competitive advantages",
                                            "minimum": 1,
                                            "maximum": 10
                                        },
                                        "competitors": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["description", "considerations", "market_saturation_analysis", "market_saturation", "defensibility_score", "competitors"]
                                },
                                "venture_scale_returns": {
                                    "type": "object",
                                    "properties": {
                                        "description": {"type": "string"},
                                        "risks": {"type": "string"}
                                    },
                                    "required": ["description", "risks"]
                                }
                            },
                            "required": ["market_size", "defensibility", "venture_scale_returns"]
                        }
                    },
                    "required": ["name", "status", "investment_thesis", "notes", "unicorn_potential", "decacorn_potential", 
                               "venture_scale_probability", "collabfund_thesis_alignment", "zizo_thesis_alignment", "excitement",
                               "entry_barriers", "barrier_difficulty", "behavior_change_requirement", "technological_complexity",
                               "operational_complexity", "capital_intensity", "industry_domains", "deep_tech"]
                }
            }],
            function_call={"name": "analyze_investment"},
            temperature=0.7
        )

        analysis = json.loads(response.choices[0].message.function_call.arguments)
        
        # Remove the warning-based validation since these fields are now required in the schema
        if not all(field in analysis for field in ['technological_complexity', 'operational_complexity', 'capital_intensity', 'deep_tech']):
            raise ValueError(f"Missing required fields in LLM response for {company_data['url']}")

        # Ensure deep_tech is consistent with technological_complexity
        if analysis.get('technological_complexity') is not None:
            analysis['deep_tech'] = analysis['technological_complexity'] >= 8

        return analysis
    except Exception as e:  # Move this up to align with the try block
        print(f"Error analyzing {company_data['url']}: {e}")
        return {
            "name": company_data['name'],
            "status": "active",
            "investment_thesis": "Analysis failed",
            "industry_domains": [],
            "unicorn_potential": None,
            "decacorn_potential": None,
            "venture_scale_probability": None,
            "collabfund_thesis_alignment": {
                "score": None,
                "description": None
            },
            "zizo_thesis_alignment": {
                "score": None,
                "description": None
            },
            "excitement": None,
            "entry_barriers": "Analysis failed",
            "barrier_difficulty": None,
            "behavior_change_requirement": None,
            "technological_complexity": None,
            "operational_complexity": None,
            "capital_intensity": None,
            "deep_tech": None,
            "notes": {
                "market_size": {
                    "description": f"Error: {str(e)}",
                    "opportunity": None,
                    "2022_estimate": None,
                    "2024_estimate": None,
                    "2030_estimate": None,
                    "annual_growth_rate": None
                },
                "defensibility": {
                    "description": "Analysis failed",
                    "considerations": None,
                    "market_saturation_analysis": None,
                    "market_saturation": None,
                    "competitors": []
                },
                "venture_scale_returns": {
                    "description": "Analysis failed",
                    "risks": None
                }
            }
        }

# Update clean_companies function
def clean_companies():
    # Load environment variables
    load_dotenv()
    
    # Initialize OpenAI client
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Load or create final portfolio
    try:
        with open(PORTFOLIO_PATH, 'r') as f:
            content = f.read().strip()
            if not content:  # Handle empty file
                final_companies = []
                analyzed_urls = set()
            else:
                final_companies = json.loads(content)
                analyzed_urls = {company['url'] for company in final_companies}
    except (FileNotFoundError, json.JSONDecodeError):  # Handle missing file or invalid JSON
        final_companies = []
        analyzed_urls = set()
    
    # Load the enriched data
    enriched_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'portfolio_2_cf_enriched.json')
    with open(enriched_path, 'r') as f:
        companies = json.load(f)
    
    # Load industry domains
    industry_domains = load_industry_domains()
    
    for i, company in enumerate(companies):
        # Skip if already analyzed
        if company['url'] in analyzed_urls:
            print(f"Skipping {company['url']} - already in final portfolio")
            continue
            
        print(f"Analyzing {i+1}/{len(companies)}: {company['url']}")
        
        analyzed = company.copy()
        analysis = analyze_company(client, company, industry_domains)
        
        analyzed.update({
            'name': analysis['name'],
            'status': analysis['status'],
            'investment_thesis': analysis['investment_thesis'],  # Changed from BG_thesis
            'notes': analysis['notes'],
            'industry_domains': analysis['industry_domains'],
            'unicorn_potential': analysis['unicorn_potential'],
            'decacorn_potential': analysis['decacorn_potential'],
            'venture_scale_probability': analysis['venture_scale_probability'],
            'collabfund_thesis_alignment': analysis['collabfund_thesis_alignment'],  # Changed from thesis_alignment
            'zizo_thesis_alignment': analysis['zizo_thesis_alignment'],
            'excitement': analysis['excitement'],
            'entry_barriers': analysis['entry_barriers'],  # Added new fields
            'barrier_difficulty': analysis['barrier_difficulty'],
            'behavior_change_requirement': analysis['behavior_change_requirement'],
            'technological_complexity': analysis['technological_complexity'],
            'operational_complexity': analysis['operational_complexity'],
            'capital_intensity': analysis['capital_intensity'],
            'deep_tech': analysis['deep_tech']
        })
        
        # Update industry domains with any new ones
        industry_domains.update(analysis['industry_domains'])
        save_industry_domains(industry_domains)
        
        final_companies.append(analyzed)
        
        # Save after each analysis
        with open(PORTFOLIO_PATH, 'w') as f:
            json.dump(final_companies, f, indent=2)
        
        sleep(1)
    
    print(f"Analyzed {len(final_companies)} companies")

if __name__ == "__main__":
    clean_companies()