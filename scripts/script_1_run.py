#!/usr/bin/env python3
import subprocess
import sys
import time
import os
from script_2_cf_extract import extract_companies
from script_3_enrich import enrich_companies
from script_4_cf_clean import clean_companies
from script_5_research import main as research_companies

def run_pipeline():
    print("\n=== Starting Portfolio Analysis Pipeline ===\n")
    
    print("Step 1: Extracting companies...")
    extract_companies()
    
    print("\nStep 2: Enriching company data...")
    enrich_companies()
    
    print("\nStep 3: Analyzing companies...")
    clean_companies()
    
    print("\nStep 4: Researching fundraising data...")
    research_companies()
    
    print("\n=== Pipeline Complete ===")
    print("Check the data folder for results:")
    print("1. Initial data: portfolio_1_cf_extracted.json")
    print("2. Enriched data: portfolio_2_cf_enriched.json")
    print("3. Analyzed data: portfolio_3_cf_analyzed.json")
    print("4. Final data with valuations: portfolio_4_cf_valuations.json")

if __name__ == "__main__":
    run_pipeline()