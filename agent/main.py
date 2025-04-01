from __future__ import annotations

import asyncio
import json
import logging
import uuid
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, Any, Optional, Literal, Annotated
from pathlib import Path

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
)
from livekit.agents.multimodal import MultimodalAgent
from livekit.plugins import openai

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("my-worker")
logger.setLevel(logging.INFO)


@dataclass
class SessionConfig:
    openai_api_key: str
    instructions: str
    voice: openai.realtime.api_proto.Voice
    temperature: float
    max_response_output_tokens: str | int
    modalities: list[openai.realtime.api_proto.Modality]
    turn_detection: openai.realtime.ServerVadOptions

    def __post_init__(self):
        if self.modalities is None:
            self.modalities = self._modalities_from_string("text_and_audio")

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if k != "openai_api_key"}

    @staticmethod
    def _modalities_from_string(modalities: str) -> list[str]:
        modalities_map = {
            "text_and_audio": ["text", "audio"],
            "text_only": ["text"],
        }
        return modalities_map.get(modalities, ["text", "audio"])

    def __eq__(self, other: SessionConfig) -> bool:
        return self.to_dict() == other.to_dict()


def parse_session_config(data: Dict[str, Any]) -> SessionConfig:
    turn_detection = None

    if data.get("turn_detection"):
        turn_detection_json = json.loads(data.get("turn_detection"))
        turn_detection = openai.realtime.ServerVadOptions(
            threshold=turn_detection_json.get("threshold", 0.5),
            prefix_padding_ms=turn_detection_json.get("prefix_padding_ms", 200),
            silence_duration_ms=turn_detection_json.get("silence_duration_ms", 300),
            create_response=True  # Added missing required parameter
        )
    else:
        turn_detection = openai.realtime.DEFAULT_SERVER_VAD_OPTIONS

    config = SessionConfig(
        openai_api_key=data.get("openai_api_key", ""),
        instructions=data.get("instructions", ""),
        voice=data.get("voice", "alloy"),
        temperature=float(data.get("temperature", 0.8)),
        max_response_output_tokens=data.get("max_output_tokens")
        if data.get("max_output_tokens") == "inf"
        else int(data.get("max_output_tokens") or 2048),
        modalities=SessionConfig._modalities_from_string(
            data.get("modalities", "text_and_audio")
        ),
        turn_detection=turn_detection,
    )
    return config


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()

    await run_multimodal_agent(ctx, participant)

    logger.info("agent started")


class PortfolioFunctions(llm.FunctionContext):
    def __init__(self):
        super().__init__()
        kb_path = Path(__file__).parent.parent / "data" / "portfolio_4_cf_valuations.json"
        with open(kb_path) as f:
            self.portfolio_data = json.load(f)
        # Precompute all industries (in lowercase) from the portfolio for dynamic matching.
        self.all_industries = set()
        for company in self.portfolio_data:
            for domain in company.get("industry_domains", []):
                self.all_industries.add(domain.lower())
        # Investment styles (for other functions)
        self.collabfund_style = (
            "Collaborative Fund Investment Style:\n"
            "1. Dual Impact Mandate: Invest in companies that deliver robust financial returns while generating meaningful social or environmental benefits.\n"
            "2. Market Disruption & Momentum: Back ventures that not only ride existing trends but actively create new market dynamics through innovative business models.\n"
            "3. Resilient Business Fundamentals (Villain Test): Choose opportunities compelling enough that even a self-interested investor would back them, ensuring strong market potential.\n"
            "4. Systemic & Holistic Alignment: Prioritize investments that align with broad societal shifts, integrating business success with civic and systemic impact."
        )

        self.personal_style = (
            "Personal Investment Style:\n"
            "1. Billion-Person Impact: Look for companies that can meaningfully impact a billion or more people\n"
            "2. Economic Paradigm Shifts: Seek businesses that create entirely new markets or fundamentally transform existing ones\n"
            "3. Deep Technical Innovation: Prioritize companies with significant technical differentiation that is difficult to replicate\n"
            "4. Novel Experiences: Value startups that enable fundamentally new types of interactions or experiences"
        )

    # ----------------------------
    # Existing Functions (unchanged)
    # ----------------------------
    @llm.ai_callable(description="Get a summary of investment styles")
    async def get_investment_style(
        self,
        style_type: str = "both"
    ) -> str:
        if style_type.lower() == "collabfund":
            return self.collabfund_style
        elif style_type.lower() == "personal":
            return self.personal_style
        else:
            return f"Collaborative Fund Investment Style:\n{self.collabfund_style}\n\nPersonal Investment Style:\n{self.personal_style}"

    @llm.ai_callable(description="Check if a company is in the portfolio")
    async def check_portfolio_company(
            self,
            company_name: Annotated[
                str, llm.TypeInfo(description="The name of the company to check")
            ],
        ) -> str:
            company_name = company_name.lower()
            for company in self.portfolio_data:
                if company_name in company["name"].lower():
                    return f"Yes, {company['name']} is in our portfolio. Would you like to know more about them?"
            return f"No, {company_name} is not currently in our portfolio. Would you like to see some similar companies we do invest in?"

    @llm.ai_callable(description="Check investment thesis alignment")
    async def check_thesis_alignment(
        self,
        company_name: str,
        thesis_type: str = "both"
    ) -> str:
        company_name = company_name.lower()
        for company in self.portfolio_data:
            if company_name in company["name"].lower():
                if thesis_type.lower() == "collabfund":
                    return (f"Collaborative Thesis Alignment for {company['name']}:\n"
                            f"Score: {company['collabfund_thesis_alignment']['score']}/10\n"
                            f"Analysis: {company['collabfund_thesis_alignment']['description']}")
                elif thesis_type.lower() == "personal":
                    return (f"Personal Thesis Alignment for {company['name']}:\n"
                            f"Score: {company['zizo_thesis_alignment']['score']}/10\n"
                            f"Analysis: {company['zizo_thesis_alignment']['description']}")
                else:
                    return (f"Thesis Alignment for {company['name']}:\n\n"
                            f"Collaborative Fund Thesis:\nScore: {company['collabfund_thesis_alignment']['score']}/10\n"
                            f"{company['collabfund_thesis_alignment']['description']}\n\n"
                            f"Personal Thesis:\nScore: {company['zizo_thesis_alignment']['score']}/10\n"
                            f"{company['zizo_thesis_alignment']['description']}")
        return f"Could not find {company_name} in our portfolio."

    @llm.ai_callable(description="Get company valuation and fundraising details")
    async def get_company_valuation(
        self,
        company_name: str
    ) -> str:
        for company in self.portfolio_data:
            if company_name.lower() in company['name'].lower():
                response = [f"Here's what I know about {company['name']}:"]
                if company.get('valuation'):
                    valuation = company['valuation']
                    for divisor in [1000, 100, 10, 1]:
                        val_bn = valuation / divisor
                        if val_bn >= 0.1:
                            response.append(f"Current valuation: about ${val_bn:.1f} billion.")
                            break
                    else:
                        response.append(f"Current valuation: about ${valuation:.1f} million.")
                if company.get('recent_raise'):
                    response.append(f"They recently raised around ${company['recent_raise']} million on {company['fundraising_announcement_date']}.")
                elif company.get('fundraising_announcement_date'):
                    response.append(f"The last fundraising date was {company['fundraising_announcement_date']}.")
                if company.get('fundraising_source_article'):
                    response.append(f"You can read more about it here: {company['fundraising_source_article']}")
                if company.get('fundraising_data_updated'):
                    response.append(f"Data updated as of {company['fundraising_data_updated'][:10]}.")
                return " ".join(response)
        return f"Sorry, I couldn't find valuation details for {company_name}."

    @llm.ai_callable(description="Get companies sorted by valuation")
    async def get_companies_by_valuation(
        self,
        limit: int = 5
    ) -> str:
        filtered_companies = []
        for company in self.portfolio_data:
            valuation = company.get('valuation')
            if valuation:
                valuation_bn = valuation / 1000
                filtered_companies.append({
                    'name': company['name'],
                    'valuation': valuation_bn,
                    'date': company.get('fundraising_data_updated', 'N/A')
                })
        if not filtered_companies:
            return "I couldn't find any companies with known valuations."
        sorted_companies = sorted(
            filtered_companies,
            key=lambda x: x['valuation'],
            reverse=True
        )[:limit]
        response = [f"Here are the top {len(sorted_companies)} companies by valuation:"]
        for company in sorted_companies:
            date = company['date'][:10] if company['date'] != 'N/A' else 'an unknown date'
            response.append(f"- {company['name']}: approximately ${company['valuation']:.1f} billion (as of {date}).")
        return "\n".join(response)

    @llm.ai_callable(description="Get a list of all unique domains in the portfolio")
    async def get_domains(self) -> str:
        domains = set()
        for company in self.portfolio_data:
            domains.update(company.get("industry_domains", []))
        sorted_domains = sorted(domains)
        response = ["The portfolio covers these domains:"]
        for domain in sorted_domains:
            response.append(f"- {domain}")
        return "\n".join(response)

    # ----------------------------
    # New Helper Functions for Extended NL Queries and Ranking
    # ----------------------------
    def _parse_extended_nl_criteria(self, query: str) -> dict:
        """
        Extract filtering criteria from a freeform spoken query.
        This function covers every field in the portfolio.
        """
        criteria = {}
        q_lower = query.lower()

        # --- Name ---
        m = re.search(r'name\s+(?:is|equals)\s+"([^"]+)"', q_lower)
        if m:
            criteria["name"] = m.group(1).strip()

        # --- URL ---
        m = re.search(r'url\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["url_contains"] = m.group(1).strip()

        # # --- is_boxgroup_office ---
        # if "boxgroup office" in q_lower:
        #     criteria["is_boxgroup_office"] = True

        # --- Description ---
        m = re.search(r'description\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["description_contains"] = m.group(1).strip()

        # --- Status (active, ipo, exit) ---
        if "ipo" in q_lower and "active" not in q_lower and "exit" not in q_lower:
            criteria["status"] = "ipo"
        elif "exit" in q_lower:
            criteria["status"] = "exit"
        elif "active" in q_lower:
            criteria["status"] = "active"

        # --- Investment Thesis ---
        m = re.search(r'investment thesis\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["investment_thesis_contains"] = m.group(1).strip()

        # --- Notes: Market Size ---
        m = re.search(r'market size 2022 estimate (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_market_size_2022"] = float(m.group(1))
        m = re.search(r'market size 2022 estimate (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_market_size_2022"] = float(m.group(1))
        m = re.search(r'market size 2024 estimate (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_market_size_2024"] = float(m.group(1))
        m = re.search(r'market size 2024 estimate (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_market_size_2024"] = float(m.group(1))
        m = re.search(r'market size 2030 estimate (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_market_size_2030"] = float(m.group(1))
        m = re.search(r'market size 2030 estimate (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_market_size_2030"] = float(m.group(1))

        # --- Notes: Defensibility ---
        m = re.search(r'defensibility score (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_defensibility_score"] = float(m.group(1))
        m = re.search(r'market saturation (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_market_saturation"] = float(m.group(1))
        m = re.search(r'defensibility description\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["defensibility_description_contains"] = m.group(1).strip()
        m = re.search(r'defensibility considerations\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["defensibility_considerations_contains"] = m.group(1).strip()
        m = re.search(r'competitor\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["competitor"] = m.group(1).strip()

        # --- Notes: Venture Scale Returns ---
        m = re.search(r'venture scale returns description\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["venture_scale_returns_description_contains"] = m.group(1).strip()
        m = re.search(r'venture scale returns risks\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["venture_scale_returns_risks_contains"] = m.group(1).strip()

        #  --- Industry Domains (dynamic) ---
        industry_matches = []
        for ind in self.all_industries:
            if ind in q_lower:
                industry_matches.append(ind)
        # Explicitly add "biotech" if mentioned
        if "biotech" in q_lower and "biotech" not in industry_matches:
            industry_matches.append("biotech")
        if industry_matches:
            criteria["industry_keywords"] = industry_matches

        # --- Unicorn Potential ---
        m = re.search(r'unicorn potential (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_unicorn_potential"] = float(m.group(1))
        m = re.search(r'unicorn potential (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_unicorn_potential"] = float(m.group(1))

        # --- Decacorn Potential ---
        m = re.search(r'decacorn potential (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_decacorn_potential"] = float(m.group(1))
        m = re.search(r'decacorn potential (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_decacorn_potential"] = float(m.group(1))

        # --- Venture Scale Probability ---
        m = re.search(r'venture scale probability (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_venture_scale_probability"] = float(m.group(1))
        m = re.search(r'venture scale probability (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_venture_scale_probability"] = float(m.group(1))

        # --- Thesis Alignment (Collaborative Fund and Personal) --- need to make sure the next line works
        m = re.search(r'(?:collaborative fund thesis alignment|collabfund)\s+(?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_collabfund_thesis"] = float(m.group(1))
        m = re.search(r'(?:personal thesis alignment|zizo thesis alignment|personal)\s+(?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_personal_thesis"] = float(m.group(1))
        m = re.search(r'thesis alignment (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m and ("min_collabfund_thesis" not in criteria and "min_personal_thesis" not in criteria):
            val = float(m.group(1))
            criteria["min_collabfund_thesis"] = val
            criteria["min_personal_thesis"] = val
        m = re.search(r'collaborative fund thesis description\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["collabfund_thesis_description_contains"] = m.group(1).strip()
        m = re.search(r'personal thesis description\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["zizo_thesis_description_contains"] = m.group(1).strip()

        # --- Excitement ---
        if "excited" in q_lower or "excitement" in q_lower:
            m = re.search(r'excitement (?:above|over|greater than)\s*([\d\.]+)', q_lower)
            if m:
                criteria["min_excitement"] = float(m.group(1))
            else:
                criteria["min_excitement"] = 7

        # --- Entry Barriers ---
        m = re.search(r'entry barriers\s+(?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["entry_barriers_contains"] = m.group(1).strip()

        # --- Barrier Difficulty ---
        m = re.search(r'barrier difficulty (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_barrier_difficulty"] = float(m.group(1))
        m = re.search(r'barrier difficulty (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_barrier_difficulty"] = float(m.group(1))

        # --- Behavior Change Requirement ---
        m = re.search(r'behavior change requirement (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_behavior_change_requirement"] = float(m.group(1))
        m = re.search(r'behavior change requirement (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_behavior_change_requirement"] = float(m.group(1))

        # --- Technological Complexity ---
        m = re.search(r'technological complexity (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_tech_complexity"] = float(m.group(1))
        m = re.search(r'technological complexity (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_tech_complexity"] = float(m.group(1))

        # --- Operational Complexity ---
        m = re.search(r'operational complexity (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_op_complexity"] = float(m.group(1))
        m = re.search(r'operational complexity (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_op_complexity"] = float(m.group(1))

        # --- Capital Intensity ---
        m = re.search(r'capital intensity (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_capital_intensity"] = float(m.group(1))
        m = re.search(r'capital intensity (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_capital_intensity"] = float(m.group(1))

        # --- Deep Tech ---
        if "deep tech" in q_lower:
            if "not deep tech" in q_lower or "non deep tech" in q_lower:
                criteria["deep_tech"] = False
            else:
                criteria["deep_tech"] = True

        # --- Recent Raise ---
        m = re.search(r'recent raise (?:above|over|greater than)\s*([\d\.]+)', q_lower)
        if m:
            criteria["min_recent_raise"] = float(m.group(1))
        m = re.search(r'recent raise (?:below|under)\s*([\d\.]+)', q_lower)
        if m:
            criteria["max_recent_raise"] = float(m.group(1))

        # --- Fundraising Announcement Date ---
        m = re.search(r'fundraising announcement date (?:after|since)\s+"([^"]+)"', q_lower)
        if m:
            criteria["min_fundraising_announcement_date"] = m.group(1).strip()
        m = re.search(r'fundraising announcement date (?:before|until)\s+"([^"]+)"', q_lower)
        if m:
            criteria["max_fundraising_announcement_date"] = m.group(1).strip()

        # --- Fundraising Source Article ---
        m = re.search(r'fundraising source article (?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["fundraising_source_article_contains"] = m.group(1).strip()

        # --- Fundraising Source Publisher ---
        m = re.search(r'fundraising source publisher (?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["fundraising_source_publisher_contains"] = m.group(1).strip()

        # --- Fundraising Source URL ---
        m = re.search(r'fundraising source url (?:contains|includes)\s+"([^"]+)"', q_lower)
        if m:
            criteria["fundraising_source_url_contains"] = m.group(1).strip()

        # --- Fundraising Data Updated ---
        m = re.search(r'fundraising data updated (?:after|since)\s+"([^"]+)"', q_lower)
        if m:
            criteria["min_fundraising_data_updated"] = m.group(1).strip()
        m = re.search(r'fundraising data updated (?:before|until)\s+"([^"]+)"', q_lower)
        if m:
            criteria["max_fundraising_data_updated"] = m.group(1).strip()

        return criteria

    def _apply_extended_criteria(self, criteria: dict) -> list:
        matches = []
        for company in self.portfolio_data:
            keep = True

            # --- Name ---
            if "name" in criteria:
                if criteria["name"].lower() not in company.get("name", "").lower():
                    keep = False

            # --- URL ---
            if "url_contains" in criteria:
                if criteria["url_contains"].lower() not in company.get("url", "").lower():
                    keep = False

            # # --- is_boxgroup_office ---
            # if "is_boxgroup_office" in criteria:
            #     if company.get("is_boxgroup_office") != criteria["is_boxgroup_office"]:
            #         keep = False

            # --- Description ---
            if "description_contains" in criteria:
                if criteria["description_contains"].lower() not in company.get("description", "").lower():
                    keep = False

            # --- Status ---
            if "status" in criteria:
                if company.get("status", "").lower() != criteria["status"]:
                    keep = False

            # --- Investment Thesis ---
            if "investment_thesis_contains" in criteria:
                if criteria["investment_thesis_contains"].lower() not in company.get("investment_thesis", "").lower():
                    keep = False

            # --- Notes: Market Size 2022 ---
            if "min_market_size_2022" in criteria:
                ms = company.get("notes", {}).get("market_size", {}).get("2022_estimate", 0)
                if ms < criteria["min_market_size_2022"]:
                    keep = False
            if "max_market_size_2022" in criteria:
                ms = company.get("notes", {}).get("market_size", {}).get("2022_estimate", 0)
                if ms > criteria["max_market_size_2022"]:
                    keep = False

            # --- Notes: Market Size 2024 ---
            if "min_market_size_2024" in criteria:
                ms = company.get("notes", {}).get("market_size", {}).get("2024_estimate", 0)
                if ms < criteria["min_market_size_2024"]:
                    keep = False
            if "max_market_size_2024" in criteria:
                ms = company.get("notes", {}).get("market_size", {}).get("2024_estimate", 0)
                if ms > criteria["max_market_size_2024"]:
                    keep = False

            # --- Notes: Market Size 2030 ---
            if "min_market_size_2030" in criteria:
                ms = company.get("notes", {}).get("market_size", {}).get("2030_estimate", 0)
                if ms < criteria["min_market_size_2030"]:
                    keep = False
            if "max_market_size_2030" in criteria:
                ms = company.get("notes", {}).get("market_size", {}).get("2030_estimate", 0)
                if ms > criteria["max_market_size_2030"]:
                    keep = False

            # --- Notes: Defensibility Score ---
            if "min_defensibility_score" in criteria:
                ds = company.get("notes", {}).get("defensibility", {}).get("defensibility_score", 0)
                if ds < criteria["min_defensibility_score"]:
                    keep = False

            # --- Notes: Market Saturation ---
            if "max_market_saturation" in criteria:
                msat = company.get("notes", {}).get("defensibility", {}).get("market_saturation", 100)
                if msat > criteria["max_market_saturation"]:
                    keep = False

            # --- Notes: Defensibility Description ---
            if "defensibility_description_contains" in criteria:
                text = company.get("notes", {}).get("defensibility", {}).get("description", "").lower()
                if criteria["defensibility_description_contains"].lower() not in text:
                    keep = False

            # --- Notes: Defensibility Considerations ---
            if "defensibility_considerations_contains" in criteria:
                text = company.get("notes", {}).get("defensibility", {}).get("considerations", "").lower()
                if criteria["defensibility_considerations_contains"].lower() not in text:
                    keep = False

            # --- Notes: Competitor ---
            if "competitor" in criteria:
                competitors = company.get("notes", {}).get("defensibility", {}).get("competitors", [])
                if not any(criteria["competitor"].lower() in comp.lower() for comp in competitors):
                    keep = False

            # --- Notes: Venture Scale Returns Description ---
            if "venture_scale_returns_description_contains" in criteria:
                text = company.get("notes", {}).get("venture_scale_returns", {}).get("description", "").lower()
                if criteria["venture_scale_returns_description_contains"].lower() not in text:
                    keep = False

            # --- Notes: Venture Scale Returns Risks ---
            if "venture_scale_returns_risks_contains" in criteria:
                text = company.get("notes", {}).get("venture_scale_returns", {}).get("risks", "").lower()
                if criteria["venture_scale_returns_risks_contains"].lower() not in text:
                    keep = False

            # --- Industry Keywords ---
            if "industry_keywords" in criteria:
                domains = " ".join(company.get("industry_domains", [])).lower()
                description = (company.get("description") or "").lower()
                thesis = (company.get("investment_thesis") or "").lower()
                combined = f"{domains} {description} {thesis}"
                for keyword in criteria["industry_keywords"]:
                    if keyword not in combined:
                        keep = False
                        break

            # --- Unicorn Potential ---
            if "min_unicorn_potential" in criteria:
                if company.get("unicorn_potential", 0) < criteria["min_unicorn_potential"]:
                    keep = False
            if "max_unicorn_potential" in criteria:
                if company.get("unicorn_potential", 0) > criteria["max_unicorn_potential"]:
                    keep = False

            # --- Decacorn Potential ---
            if "min_decacorn_potential" in criteria:
                if company.get("decacorn_potential", 0) < criteria["min_decacorn_potential"]:
                    keep = False
            if "max_decacorn_potential" in criteria:
                if company.get("decacorn_potential", 0) > criteria["max_decacorn_potential"]:
                    keep = False

            # --- Venture Scale Probability ---
            if "min_venture_scale_probability" in criteria:
                if company.get("venture_scale_probability", 0) < criteria["min_venture_scale_probability"]:
                    keep = False
            if "max_venture_scale_probability" in criteria:
                if company.get("venture_scale_probability", 0) > criteria["max_venture_scale_probability"]:
                    keep = False

            # --- Collaborative Fund Thesis Alignment ---
            if "min_collabfund_thesis" in criteria:
                score = company.get("collabfund_thesis_alignment", {}).get("score", 0)
                if score < criteria["min_collabfund_thesis"]:
                    keep = False
            if "collabfund_thesis_description_contains" in criteria:
                text = company.get("collabfund_thesis_alignment", {}).get("description", "").lower()
                if criteria["collabfund_thesis_description_contains"].lower() not in text:
                    keep = False

            # --- Personal (Zizo) Thesis Alignment ---
            if "min_personal_thesis" in criteria:
                score = company.get("zizo_thesis_alignment", {}).get("score", 0)
                if score < criteria["min_personal_thesis"]:
                    keep = False
            if "zizo_thesis_description_contains" in criteria:
                text = company.get("zizo_thesis_alignment", {}).get("description", "").lower()
                if criteria["zizo_thesis_description_contains"].lower() not in text:
                    keep = False

            # --- Excitement ---
            if "min_excitement" in criteria:
                if company.get("excitement", 0) < criteria["min_excitement"]:
                    keep = False

            # --- Entry Barriers ---
            if "entry_barriers_contains" in criteria:
                if criteria["entry_barriers_contains"].lower() not in company.get("entry_barriers", "").lower():
                    keep = False

            # --- Barrier Difficulty ---
            if "min_barrier_difficulty" in criteria:
                if company.get("barrier_difficulty", 0) < criteria["min_barrier_difficulty"]:
                    keep = False
            if "max_barrier_difficulty" in criteria:
                if company.get("barrier_difficulty", 0) > criteria["max_barrier_difficulty"]:
                    keep = False

            # --- Behavior Change Requirement ---
            if "min_behavior_change_requirement" in criteria:
                if company.get("behavior_change_requirement", 0) < criteria["min_behavior_change_requirement"]:
                    keep = False
            if "max_behavior_change_requirement" in criteria:
                if company.get("behavior_change_requirement", 0) > criteria["max_behavior_change_requirement"]:
                    keep = False

            # --- Technological Complexity ---
            if "min_tech_complexity" in criteria:
                if company.get("technological_complexity", 0) < criteria["min_tech_complexity"]:
                    keep = False
            if "max_tech_complexity" in criteria:
                if company.get("technological_complexity", 0) > criteria["max_tech_complexity"]:
                    keep = False

            # --- Operational Complexity ---
            if "min_op_complexity" in criteria:
                if company.get("operational_complexity", 0) < criteria["min_op_complexity"]:
                    keep = False
            if "max_op_complexity" in criteria:
                if company.get("operational_complexity", 0) > criteria["max_op_complexity"]:
                    keep = False

            # --- Capital Intensity ---
            if "min_capital_intensity" in criteria:
                if company.get("capital_intensity", 0) < criteria["min_capital_intensity"]:
                    keep = False
            if "max_capital_intensity" in criteria:
                if company.get("capital_intensity", 0) > criteria["max_capital_intensity"]:
                    keep = False

            # --- Deep Tech ---
            if "deep_tech" in criteria:
                if company.get("deep_tech", False) != criteria["deep_tech"]:
                    keep = False

            # --- Recent Raise ---
            if "min_recent_raise" in criteria:
                if company.get("recent_raise", 0) < criteria["min_recent_raise"]:
                    keep = False
            if "max_recent_raise" in criteria:
                if company.get("recent_raise", 0) > criteria["max_recent_raise"]:
                    keep = False

            # --- Fundraising Announcement Date ---
            if "min_fundraising_announcement_date" in criteria:
                fad = company.get("fundraising_announcement_date", "").lower()
                if criteria["min_fundraising_announcement_date"].lower() not in fad:
                    keep = False
            if "max_fundraising_announcement_date" in criteria:
                fad = company.get("fundraising_announcement_date", "").lower()
                if criteria["max_fundraising_announcement_date"].lower() not in fad:
                    keep = False

            # --- Fundraising Source Article ---
            if "fundraising_source_article_contains" in criteria:
                text = company.get("fundraising_source_article", "").lower()
                if criteria["fundraising_source_article_contains"].lower() not in text:
                    keep = False

            # --- Fundraising Source Publisher ---
            if "fundraising_source_publisher_contains" in criteria:
                text = (company.get("fundraising_source_publisher") or "").lower()
                if criteria["fundraising_source_publisher_contains"].lower() not in text:
                    keep = False

            # --- Fundraising Source URL ---
            if "fundraising_source_url_contains" in criteria:
                text = company.get("fundraising_source_url", "").lower()
                if criteria["fundraising_source_url_contains"].lower() not in text:
                    keep = False

            # --- Fundraising Data Updated ---
            if "min_fundraising_data_updated" in criteria:
                fdu = company.get("fundraising_data_updated", "").lower()
                if criteria["min_fundraising_data_updated"].lower() not in fdu:
                    keep = False
            if "max_fundraising_data_updated" in criteria:
                fdu = company.get("fundraising_data_updated", "").lower()
                if criteria["max_fundraising_data_updated"].lower() not in fdu:
                    keep = False

            if keep:
                matches.append(company)
        return matches

    # ----------------------------
    # New Function: Rank Companies by a Specific Field
    # ----------------------------
    @llm.ai_callable(
        description=(
            "Rank companies by a specified numeric field using dot notation. "
            "Examples of ranking_field include: 'valuation', 'recent_raise', 'excitement', "
            "'personal_thesis' (zizo), 'collabfund_thesis', 'defensibility', 'market_saturation', "
            "'market_size_2022', 'market_size_2024', 'market_size_2030', "
            "'behavior_change_requirement', 'technological_complexity', 'operational_complexity', or 'capital_intensity'.\n\n"
            "Optionally, provide a filter_query to narrow the companies and set ascending=true if lower values are better.\n\n"
            "For ranking by 'recent_raise', you may also provide start_date and end_date "
            "to restrict to companies that raised funds within that time frame (e.g., '2024-01-01').\n\n"
            "If fixed_list is provided (as a comma-separated list of company names), only those companies will be ranked."
        )
    )
    async def rank_companies(
        self,
        ranking_field: Annotated[str, llm.TypeInfo(description="The dot-notated key to rank by.")],
        limit: int = 5,
        filter_query: str = "",
        ascending: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fixed_list: Optional[str] = None
    ) -> str:
        # First, filter companies using the filter_query (if provided).
        filtered_companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            filtered_companies = self._apply_extended_criteria(criteria)
        
        # If ranking by funds raised and a time frame is provided, further restrict by fundraising date.
        if ranking_field.lower() == "recent_raise" and (start_date or end_date):
            def parse_date(date_str: str) -> Optional[datetime]:
                try:
                    return datetime.fromisoformat(date_str)
                except ValueError:
                    try:
                        return datetime.strptime(date_str, "%B %d, %Y")
                    except ValueError:
                        return None

            filtered_companies = [
                comp for comp in filtered_companies
                if comp.get("recent_raise") is not None 
                   and comp.get("fundraising_announcement_date")
                   and (not start_date or (parse_date(comp["fundraising_announcement_date"]) 
                                          and parse_date(comp["fundraising_announcement_date"]) >= parse_date(start_date)))
                   and (not end_date or (parse_date(comp["fundraising_announcement_date"]) 
                                        and parse_date(comp["fundraising_announcement_date"]) <= parse_date(end_date)))
            ]
        
        # If a fixed_list is provided, restrict the companies to that fixed set.
        if fixed_list:
            fixed_names = [name.strip().lower() for name in fixed_list.split(",")]
            filtered_companies = [
                comp for comp in filtered_companies
                if comp.get("name", "").lower() in fixed_names
            ]
        
        if not filtered_companies:
            return "I couldn't find any companies matching the provided criteria."

        # Mapping for supported fields.
        field_mapping = {
            "valuation": lambda comp: comp.get("valuation", 0),
            "recent_raise": lambda comp: comp.get("recent_raise", 0),
            "excitement": lambda comp: comp.get("excitement", 0),
            "personal_thesis": lambda comp: comp.get("zizo_thesis_alignment", {}).get("score", 0),
            "collabfund_thesis": lambda comp: comp.get("collabfund_thesis_alignment", {}).get("score", 0),
            "defensibility": lambda comp: comp.get("notes", {}).get("defensibility", {}).get("defensibility_score", 0),
            "market_saturation": lambda comp: comp.get("notes", {}).get("defensibility", {}).get("market_saturation", 0),
            "market_size_2022": lambda comp: comp.get("notes", {}).get("market_size", {}).get("2022_estimate", 0),
            "market_size_2024": lambda comp: comp.get("notes", {}).get("market_size", {}).get("2024_estimate", 0),
            "market_size_2030": lambda comp: comp.get("notes", {}).get("market_size", {}).get("2030_estimate", 0),
            "behavior_change_requirement": lambda comp: comp.get("behavior_change_requirement", 0),
            "technological_complexity": lambda comp: comp.get("technological_complexity", 0),
            "operational_complexity": lambda comp: comp.get("operational_complexity", 0),
            "capital_intensity": lambda comp: comp.get("capital_intensity", 0),
                }
        key_func = field_mapping.get(ranking_field.lower())
        if not key_func:
            return f"Ranking field '{ranking_field}' is not supported. Please choose one of: {', '.join(field_mapping.keys())}."

        def safe_sort_key(company):
            value = key_func(company)
            # Return a tuple where None values are sorted last
            return (value is None, value)

        sorted_companies = sorted(
            filtered_companies,
            key=safe_sort_key,
            reverse=not ascending
        )[:limit]

        if not sorted_companies:
            return "No companies found after applying the ranking."

        lines = [f"Top {len(sorted_companies)} companies by {ranking_field}:"]
        for comp in sorted_companies:
            value = key_func(comp)
            lines.append(f"- {comp.get('name')}: {value}")
        return "\n".join(lines)

    @llm.ai_callable(
        description="Search companies based on a natural language query across all fields."
    )
    async def search_companies_nl(self, query: str) -> str:
        criteria = self._parse_extended_nl_criteria(query)
        matching = self._apply_extended_criteria(criteria)

        # Filter for recent fundraising if requested
        if "recent_fundraising" in query.lower():
            matching = [
                company for company in matching 
                if (company.get("fundraising_announcement_date") and 
                    company.get("recent_raise") is not None)
            ]

        if not matching:
            return "I couldn't find any companies matching that description."

        lines = ["Here are the matching companies:"]
        for comp in matching:
            line_parts = [f"- {comp['name']}"]
            if comp.get("recent_raise") is not None:
                line_parts.append(f"raised ${comp['recent_raise']}M")
                if comp.get("fundraising_announcement_date"):
                    line_parts.append(f"on {comp['fundraising_announcement_date']}")
            if comp.get("valuation") is not None:
                line_parts.append(f"at a ${comp['valuation']/1000:.1f}B valuation")
            if comp.get("industry_domains"):
                line_parts.append(f"operating in {', '.join(comp['industry_domains'])}")
            lines.append(" ".join(line_parts))

        return "\n".join(lines)

    # ----------------------------
    # New Calculation Functions
    # ----------------------------

    @llm.ai_callable(
        description="Calculate the average valuation (in billions) of companies, optionally filtered by a natural language query."
    )
    async def calculate_average_valuation(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        if not companies:
            return "No companies found matching the criteria."
        vals = [comp.get("valuation") for comp in companies if comp.get("valuation")]
        if not vals:
            return "No valuation data available."
        avg = sum(vals) / len(vals) / 1000  # converting to billions
        return f"The average valuation is approximately ${avg:.2f} billion."

    @llm.ai_callable(
        description="Calculate the total valuation (in billions) of companies, optionally filtered by a natural language query."
    )
    async def calculate_total_valuation(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("valuation") for comp in companies if comp.get("valuation")]
        if not vals:
            return "No valuation data available."
        total = sum(vals) / 1000  # in billions
        return f"The total valuation of the selected companies is approximately ${total:.2f} billion."

    @llm.ai_callable(
        description="Calculate the average recent raise (in millions) of companies, optionally filtered by a natural language query."
    )
    async def calculate_average_recent_raise(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        raises = [comp.get("recent_raise") for comp in companies if comp.get("recent_raise")]
        if not raises:
            return "No recent raise data available."
        avg = sum(raises) / len(raises)
        return f"The average recent raise is approximately ${avg:.2f} million."

    @llm.ai_callable(
        description="Calculate the total recent raise (in millions) of companies, optionally filtered by a natural language query."
    )
    async def calculate_total_recent_raise(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        raises = [comp.get("recent_raise") for comp in companies if comp.get("recent_raise")]
        if not raises:
            return "No recent raise data available."
        total = sum(raises)
        return f"The total recent raise of the selected companies is approximately ${total:.2f} million."

    @llm.ai_callable(
        description="Calculate the average excitement score of companies, optionally filtered by a natural language query."
    )
    async def calculate_average_excitement(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        scores = [comp.get("excitement") for comp in companies if comp.get("excitement") is not None]
        if not scores:
            return "No excitement data available."
        avg = sum(scores) / len(scores)
        return f"The average excitement score is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average Collaborative Fund thesis alignment score, optionally filtered by a natural language query."
    )
    async def calculate_average_collabfund_thesis(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        scores = [comp.get("collabfund_thesis_alignment", {}).get("score") for comp in companies
                  if comp.get("collabfund_thesis_alignment", {}).get("score") is not None]
        if not scores:
            return "No Collaborative Fund thesis data available."
        avg = sum(scores) / len(scores)
        return f"The average Collaborative Fund thesis alignment score is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average personal (Zizo) thesis alignment score, optionally filtered by a natural language query."
    )
    async def calculate_average_personal_thesis(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        scores = [comp.get("zizo_thesis_alignment", {}).get("score") for comp in companies
                  if comp.get("zizo_thesis_alignment", {}).get("score") is not None]
        if not scores:
            return "No personal thesis data available."
        avg = sum(scores) / len(scores)
        return f"The average personal thesis alignment score is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average unicorn potential, optionally filtered by a natural language query."
    )
    async def calculate_average_unicorn_potential(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("unicorn_potential") for comp in companies if comp.get("unicorn_potential") is not None]
        if not vals:
            return "No unicorn potential data available."
        avg = sum(vals) / len(vals)
        return f"The average unicorn potential is {avg:.2f}."

    @llm.ai_callable(
        description="Calculate the average decacorn potential, optionally filtered by a natural language query."
    )
    async def calculate_average_decacorn_potential(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("decacorn_potential") for comp in companies if comp.get("decacorn_potential") is not None]
        if not vals:
            return "No decacorn potential data available."
        avg = sum(vals) / len(vals)
        return f"The average decacorn potential is {avg:.2f}."

    @llm.ai_callable(
        description="Calculate the average venture scale probability, optionally filtered by a natural language query."
    )
    async def calculate_average_venture_scale_probability(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("venture_scale_probability") for comp in companies if comp.get("venture_scale_probability") is not None]
        if not vals:
            return "No venture scale probability data available."
        avg = sum(vals) / len(vals)
        return f"The average venture scale probability is {avg:.2f}."

    @llm.ai_callable(
        description="Calculate the average barrier difficulty, optionally filtered by a natural language query."
    )
    async def calculate_average_barrier_difficulty(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("barrier_difficulty") for comp in companies if comp.get("barrier_difficulty") is not None]
        if not vals:
            return "No barrier difficulty data available."
        avg = sum(vals) / len(vals)
        return f"The average barrier difficulty is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average behavior change requirement, optionally filtered by a natural language query."
    )
    async def calculate_average_behavior_change_requirement(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("behavior_change_requirement") for comp in companies if comp.get("behavior_change_requirement") is not None]
        if not vals:
            return "No behavior change requirement data available."
        avg = sum(vals) / len(vals)
        return f"The average behavior change requirement is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average technological complexity, optionally filtered by a natural language query."
    )
    async def calculate_average_technological_complexity(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("technological_complexity") for comp in companies if comp.get("technological_complexity") is not None]
        if not vals:
            return "No technological complexity data available."
        avg = sum(vals) / len(vals)
        return f"The average technological complexity is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average operational complexity, optionally filtered by a natural language query."
    )
    async def calculate_average_operational_complexity(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("operational_complexity") for comp in companies if comp.get("operational_complexity") is not None]
        if not vals:
            return "No operational complexity data available."
        avg = sum(vals) / len(vals)
        return f"The average operational complexity is {avg:.2f}/10."

    @llm.ai_callable(
        description="Calculate the average capital intensity, optionally filtered by a natural language query."
    )
    async def calculate_average_capital_intensity(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        vals = [comp.get("capital_intensity") for comp in companies if comp.get("capital_intensity") is not None]
        if not vals:
            return "No capital intensity data available."
        avg = sum(vals) / len(vals)
        return f"The average capital intensity is {avg:.2f}/10."

    @llm.ai_callable(
        description="Count the number of deep tech companies, optionally filtered by a natural language query."
    )
    async def count_deep_tech_companies(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        count = sum(1 for comp in companies if comp.get("deep_tech") is True)
        return f"There are {count} deep tech companies."

    @llm.ai_callable(
        description="Count companies by status (active, ipo, exit), optionally filtered by a natural language query."
    )
    async def count_companies_by_status(self, filter_query: str = "") -> str:
        companies = self.portfolio_data
        if filter_query:
            criteria = self._parse_extended_nl_criteria(filter_query)
            companies = self._apply_extended_criteria(criteria)
        status_counts: Dict[str, int] = {"active": 0, "ipo": 0, "exit": 0}
        for comp in companies:
            status = comp.get("status", "").lower()
            if status in status_counts:
                status_counts[status] += 1
        return (f"Status breakdown: Active: {status_counts['active']}, "
                f"IPO: {status_counts['ipo']}, Exit: {status_counts['exit']}.")

    @llm.ai_callable(
        description="Count the number of companies in each industry domain."
    )
    async def count_companies_by_industry(self) -> str:
        industry_counts: Dict[str, int] = {}
        for comp in self.portfolio_data:
            for domain in comp.get("industry_domains", []):
                domain_lower = domain.lower()
                industry_counts[domain_lower] = industry_counts.get(domain_lower, 0) + 1
        lines = ["Companies by industry:"]
        for domain, count in sorted(industry_counts.items()):
            lines.append(f"- {domain.capitalize()}: {count}")
        return "\n".join(lines)
        
    @llm.ai_callable(
        description="Get the full JSON information for a specific company."
    )
    async def get_full_company_info(self, company_name: str) -> str:
        for company in self.portfolio_data:
            if company_name.lower() in company.get("name", "").lower():
                return f"Full information for {company.get('name')}:\n{json.dumps(company, indent=2)}"
        return f"I'm sorry, I couldn't find a company matching '{company_name}'."

    @llm.ai_callable(
        description=(
            "Analyze company information based on a natural language query. "
            "If the query asks for full details (e.g. 'full info', 'all details', 'complete'), "
            "the full JSON is returned. Otherwise, a summary is provided."
        )
    )
    async def analyze_company_info(self, query: str) -> str:
        target_company = None
        for company in self.portfolio_data:
            if company.get("name", "").lower() in query.lower():
                target_company = company
                break

        if not target_company:
            return "I'm sorry, I couldn't identify the company you're referring to."

        if any(keyword in query.lower() for keyword in ["full info", "all details", "complete", "everything"]):
            return await self.get_full_company_info(target_company["name"])

        summary = f"Summary for {target_company.get('name', 'N/A')}:\n"
        summary += f"Description: {target_company.get('description', 'N/A')}\n"
        summary += f"Status: {target_company.get('status', 'N/A')}\n"
        summary += f"Industries: {', '.join(target_company.get('industry_domains', []))}\n"
        valuation = target_company.get("valuation")
        if valuation:
            summary += f"Valuation: approximately ${valuation/1000:.1f} billion\n"
        else:
            summary += "Valuation: N/A\n"
        defensibility = target_company.get("notes", {}).get("defensibility", {})
        defensibility_score = defensibility.get("defensibility_score", "N/A")
        summary += f"Defensibility Score: {defensibility_score}\n"
        excitement = target_company.get("excitement", "N/A")
        summary += f"Excitement: {excitement}/10\n"
        return summary

    @llm.ai_callable(
        description=(
            "Get specific information about a company based on a natural language query. "
            "If the query mentions specific fields (e.g. 'defensibility', 'investment thesis', 'collaborative fund', 'personal', 'excitement', "
            "'technological complexity', 'operational complexity', 'capital intensity', 'competitors', 'barriers to entry', etc.), "
            "only that part of the record is returned. Otherwise, a complete summary is provided covering all fields."
        )
    )
    async def get_company_specific_info(self, query: str) -> str:
        target_company = None
        q_lower = query.lower()

        # Identify the target company by matching its name.
        for company in self.portfolio_data:
            if company.get("name", "").lower() in q_lower:
                target_company = company
                break

        if not target_company:
            return "I'm sorry, I couldn't identify which company you're referring to."

        # If the user asks for full details, return the full JSON.
        if any(kw in q_lower for kw in ["full info", "all details", "complete", "everything"]):
            return await self.get_full_company_info(target_company["name"])

        # If specific fields are mentioned, return only that part.
        if "defensibility" in q_lower:
            defens = target_company.get("notes", {}).get("defensibility", {})
            if not defens:
                return f"I'm sorry, I don't have defensibility information for {target_company['name']}."
            output = f"Defensibility for {target_company['name']}:\n"
            output += f"Score: {defens.get('defensibility_score', 'N/A')}\n"
            output += f"Description: {defens.get('description', 'N/A')}\n"
            output += f"Considerations: {defens.get('considerations', 'N/A')}\n"
            competitors = defens.get("competitors", [])
            if competitors:
                output += f"Competitors: {', '.join(competitors)}"
            return output

        elif "investment thesis" in q_lower:
            inv_thesis = target_company.get("investment_thesis", "N/A")
            return f"Investment Thesis for {target_company['name']}:\n{inv_thesis}"

        elif "collaborative fund" in q_lower:
            box_info = target_company.get("collabfund_thesis_alignment", {})
            if not box_info:
                return f"I'm sorry, I don't have Collaborative Fund thesis alignment info for {target_company['name']}."
            output = f"Collaborative Fund Thesis Alignment for {target_company['name']}:\n"
            output += f"Score: {box_info.get('score', 'N/A')}/10\n"
            output += f"Description: {box_info.get('description', 'N/A')}"
            return output

        elif "personal" in q_lower or "zizo" in q_lower:
            pers_info = target_company.get("zizo_thesis_alignment", {})
            if not pers_info:
                return f"I'm sorry, I don't have personal thesis alignment info for {target_company['name']}."
            output = f"Personal Thesis Alignment for {target_company['name']}:\n"
            output += f"Score: {pers_info.get('score', 'N/A')}/10\n"
            output += f"Description: {pers_info.get('description', 'N/A')}"
            return output

        elif "excitement" in q_lower:
            excitement = target_company.get("excitement", "N/A")
            return f"Excitement for {target_company['name']}: {excitement}/10"

        elif "technological complexity" in q_lower:
            tech_comp = target_company.get("technological_complexity", "N/A")
            return f"Technological Complexity for {target_company['name']}: {tech_comp}/10"

        elif "operational complexity" in q_lower:
            op_comp = target_company.get("operational_complexity", "N/A")
            return f"Operational Complexity for {target_company['name']}: {op_comp}/10"

        elif "capital intensity" in q_lower:
            cap_int = target_company.get("capital_intensity", "N/A")
            return f"Capital Intensity for {target_company['name']}: {cap_int}/10"

        elif "behavior change requirement" in q_lower:
            beh_change = target_company.get("behavior_change_requirement", "N/A")
            return f"Behavior Change Requirement for {target_company['name']}: {beh_change}/10"

        elif "competitor" in q_lower:
            defens = target_company.get("notes", {}).get("defensibility", {})
            competitors = defens.get("competitors", [])
            if competitors:
                return f"Competitors for {target_company['name']}: {', '.join(competitors)}"
            else:
                return f"I'm sorry, there is no competitor information for {target_company['name']}."

        elif "entry barrier" in q_lower:
            barriers = target_company.get("entry_barriers", "N/A")
            return f"Entry Barriers for {target_company['name']}: {barriers}"

        # Otherwise, return a full summary covering every field.
        summary = f"Summary for {target_company.get('name', 'N/A')}:\n"
        summary += f"Name: {target_company.get('name', 'N/A')}\n"
        summary += f"URL: {target_company.get('url', 'N/A')}\n"
        summary += f"IPO: {target_company.get('is_ipo', 'N/A')}\n"
        summary += f"Exit: {target_company.get('is_exit', 'N/A')}\n"
        # summary += f"BoxGroup Office: {target_company.get('is_boxgroup_office', 'N/A')}\n"
        summary += f"Description: {target_company.get('description', 'N/A')}\n"
        summary += f"Status: {target_company.get('status', 'N/A')}\n"
        summary += f"Investment Thesis: {target_company.get('investment_thesis', 'N/A')}\n"
        summary += "Notes:\n"
        notes = target_company.get("notes", {})
        for note_key, note_val in notes.items():
            if isinstance(note_val, dict):
                summary += f"  {note_key.capitalize()}:\n"
                for sub_key, sub_val in note_val.items():
                    summary += f"    {sub_key.capitalize()}: {sub_val}\n"
            else:
                summary += f"  {note_key.capitalize()}: {note_val}\n"
        summary += f"Industry Domains: {', '.join(target_company.get('industry_domains', []))}\n"
        summary += f"Unicorn Potential: {target_company.get('unicorn_potential', 'N/A')}\n"
        summary += f"Decacorn Potential: {target_company.get('decacorn_potential', 'N/A')}\n"
        summary += f"Venture Scale Probability: {target_company.get('venture_scale_probability', 'N/A')}\n"
        summary += f"Collaborative Fund Thesis Alignment: Score {target_company.get('collabfund_thesis_alignment', {}).get('score', 'N/A')} - {target_company.get('collabfund_thesis_alignment', {}).get('description', 'N/A')}\n"
        summary += f"Personal Thesis Alignment: Score {target_company.get('zizo_thesis_alignment', {}).get('score', 'N/A')} - {target_company.get('zizo_thesis_alignment', {}).get('description', 'N/A')}\n"
        summary += f"Excitement: {target_company.get('excitement', 'N/A')}/10\n"
        summary += f"Entry Barriers: {target_company.get('entry_barriers', 'N/A')}\n"
        summary += f"Barrier Difficulty: {target_company.get('barrier_difficulty', 'N/A')}/10\n"
        summary += f"Behavior Change Requirement: {target_company.get('behavior_change_requirement', 'N/A')}/10\n"
        summary += f"Technological Complexity: {target_company.get('technological_complexity', 'N/A')}/10\n"
        summary += f"Operational Complexity: {target_company.get('operational_complexity', 'N/A')}/10\n"
        summary += f"Capital Intensity: {target_company.get('capital_intensity', 'N/A')}/10\n"
        summary += f"Deep Tech: {target_company.get('deep_tech', 'N/A')}\n"
        summary += f"Recent Raise: {target_company.get('recent_raise', 'N/A')} million\n"
        summary += f"Valuation: {target_company.get('valuation', 'N/A')}\n"
        summary += f"Fundraising Announcement Date: {target_company.get('fundraising_announcement_date', 'N/A')}\n"
        summary += f"Fundraising Source Article: {target_company.get('fundraising_source_article', 'N/A')}\n"
        summary += f"Fundraising Source Publisher: {target_company.get('fundraising_source_publisher', 'N/A')}\n"
        summary += f"Fundraising Source URL: {target_company.get('fundraising_source_url', 'N/A')}\n"
        summary += f"Fundraising Data Updated: {target_company.get('fundraising_data_updated', 'N/A')}\n"
        return summary

    @llm.ai_callable(description="Compare two companies based on a natural language query")
    async def compare_companies_nl(
        self,
        query: str
    ) -> str:
        m = re.search(r"compare\s+(.+?)\s+(?:and|vs\.?)\s+(.+)", query.lower())
        if not m:
            return "I'm sorry, I couldn't extract two companies to compare from your query."
        comp1_name = m.group(1).strip()
        comp2_name = m.group(2).strip()

        def find_company(name: str) -> Optional[Dict[str, Any]]:
            for company in self.portfolio_data:
                if name in company['name'].lower():
                    return company
            return None

        comp1 = find_company(comp1_name)
        comp2 = find_company(comp2_name)
        if not comp1 or not comp2:
            missing = []
            if not comp1:
                missing.append(comp1_name)
            if not comp2:
                missing.append(comp2_name)
            return f"I couldn't find the following company(ies): {', '.join(missing)}."

        def format_comparison(company: Dict[str, Any]) -> str:
            lines = []
            lines.append(f"{company['name']}:")
            if company.get("valuation"):
                lines.append(f"  Valuation: about ${company['valuation']/1000:.1f} billion")
            else:
                lines.append("  Valuation: unknown")
            lines.append(f"  Status: {company.get('status', 'unknown')}")
            lines.append(f"  Domains: {', '.join(company.get('industry_domains', []))}")
            lines.append(f"  Deep Tech: {'Yes' if company.get('deep_tech') else 'No'}")
            return "\n".join(lines)

        response = [
            "Here's how the two companies compare:",
            format_comparison(comp1),
            "",
            format_comparison(comp2)
        ]
        return "\n".join(response)

    @llm.ai_callable(description="Provide information about a company based on a natural language query")
    async def get_company_info_nl(
        self,
        query: str
    ) -> str:
        candidate = None
        for company in self.portfolio_data:
            if company["name"].lower() in query.lower():
                candidate = company
                break
        if not candidate:
            return "I'm sorry, I couldn't identify which company you're asking about."

        query_lower = query.lower()
        if "note" in query_lower:
            notes = candidate.get("notes", {})
            def format_dict(d, indent=0):
                lines = []
                for key, value in d.items():
                    if isinstance(value, dict):
                        lines.append(" " * indent + f"{key.capitalize()}:")
                        lines.extend(format_dict(value, indent + 2))
                    elif isinstance(value, list):
                        lines.append(" " * indent + f"{key.capitalize()}: {', '.join(map(str, value))}")
                    else:
                        lines.append(" " * indent + f"{key.capitalize()}: {value}")
                return lines
            formatted_notes = "\n".join(format_dict(notes))
            return f"Here are the notes for {candidate['name']}:\n{formatted_notes}"
        elif "valuation" in query_lower:
            return await self.get_company_valuation(candidate["name"])
        elif "thesis" in query_lower:
            return (f"The investment thesis for {candidate['name']} is as follows: "
                    f"{candidate.get('collabfund_thesis_alignment', {}).get('description', 'No thesis available')}")
        elif "compare" in query_lower:
            return f"Would you like me to compare {candidate['name']} with another company? Please specify the other company."
        else:
            response = [f"Here's some information about {candidate['name']}:"]
            if description := candidate.get("description"):
                response.append(description)
            response.append(f"Status: {candidate.get('status', 'unknown')}.")
            response.append(f"Industries: {', '.join(candidate.get('industry_domains', []))}.")
            if candidate.get("valuation"):
                response.append(f"It is currently valued at approximately ${candidate['valuation']/1000000000:.1f} billion.")
            return " ".join(filter(None, response))
    
    @llm.ai_callable(
        description=(
            "Retrieve news articles for a given company from the news file. "
            "Optionally filter by start_date and end_date (ISO or 'Month Day, Year'). "
            "Articles without an explicit year are assumed to be in the current or previous year. "
            "Results are sorted with the most recent first, and you can limit the number of articles returned. "
            "Set brief=true to return a minimal summary (title, source, date, link)."
        )
    )
    async def get_company_news(
        self,
        company_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        brief: bool = True
    ) -> str:
        # Construct the path to the news file.
        news_path = Path(__file__).parent.parent / "data" / "news.json"
        try:
            with open(news_path, "r") as f:
                news_data = json.load(f)
        except Exception as e:
            return f"Error loading news data: {str(e)}"
        
        # Look up the company's news in a case-insensitive manner.
        company_key = None
        for key in news_data:
            if company_name.lower() in key.lower():
                company_key = key
                break
        if not company_key:
            return f"No news found for {company_name}."
        
        articles = news_data.get(company_key, {}).get("articles", [])
        if not articles:
            return f"No news articles available for {company_name}."
        
        # Helper function to parse an article's date.
        def parse_article_date(article: Dict[str, Any]) -> Optional[datetime]:
            dt_str = article.get("datetime")
            if dt_str:
                try:
                    return datetime.fromisoformat(dt_str.replace("Z", ""))
                except Exception:
                    pass
            # Fallback: use the "time" field.
            t_str = article.get("time", "").strip()
            if t_str:
                try:
                    # Try to parse with year.
                    return datetime.strptime(t_str, "%b %d, %Y")
                except ValueError:
                    try:
                        # If no year is provided, assume current year, unless that date is in the future.
                        dt = datetime.strptime(t_str, "%b %d")
                        now = datetime.now()
                        dt_with_year = dt.replace(year=now.year)
                        if dt_with_year > now:
                            dt_with_year = dt_with_year.replace(year=now.year - 1)
                        return dt_with_year
                    except Exception:
                        return None
            return None
        
        # Helper to parse filter dates.
        def parse_filter_date(date_str: str) -> Optional[datetime]:
            try:
                return datetime.fromisoformat(date_str)
            except ValueError:
                try:
                    return datetime.strptime(date_str, "%b %d, %Y")
                except Exception:
                    return None
        
        parsed_start = parse_filter_date(start_date) if start_date else None
        parsed_end = parse_filter_date(end_date) if end_date else None

        # Filter articles by the optional date range.
        filtered_articles = []
        for article in articles:
            art_date = parse_article_date(article)
            if art_date is None:
                continue
            if parsed_start and art_date < parsed_start:
                continue
            if parsed_end and art_date > parsed_end:
                continue
            # Save the parsed date for sorting.
            article["_parsed_date"] = art_date
            filtered_articles.append(article)
        
        # Sort articles with the most recent first.
        filtered_articles.sort(key=lambda a: a["_parsed_date"], reverse=True)
        if limit is not None:
            filtered_articles = filtered_articles[:limit]
        if not filtered_articles:
            return f"No news articles found for {company_name} in the specified date range."
        
        # Build the output.
        output_lines = [f"News articles for {company_name}:"]
        for article in filtered_articles:
            # Use the ISO datetime if available; otherwise, fallback to the "time" field.
            date_str = article.get("datetime") or article.get("time") or "Unknown date"
            title = article.get("title", "No title")
            source = article.get("source", "Unknown source")
            link = article.get("link", "")
            if brief:
                output_lines.append(f"- {title} ({source}, {date_str}): {link}")
            else:
                output_lines.append(f"Title: {title}")
                output_lines.append(f"Source: {source}")
                output_lines.append(f"Date: {date_str}")
                output_lines.append(f"Link: {link}")
                output_lines.append("")  # blank line for separation
        
        return "\n".join(output_lines)

async def run_multimodal_agent(ctx: JobContext, participant: rtc.Participant):
    async def show_toast(
        title: str,
        description: str | None,
        variant: Literal["default", "success", "warning", "destructive"],
    ):
        await ctx.room.local_participant.perform_rpc(
            destination_identity=participant.identity,
            method="pg.toast",
            payload=json.dumps(
                {"title": title, "description": description, "variant": variant}
            ),
        )

    try:
        metadata = json.loads(participant.metadata)
        config = parse_session_config(metadata)

        logger.info(f"starting MultimodalAgent with config: {config.to_dict()}")

        if not config.openai_api_key:
            raise Exception("OpenAI API Key is required")

        fnc_ctx = PortfolioFunctions()

        model = openai.realtime.RealtimeModel(
            api_key=config.openai_api_key,
            instructions=config.instructions,
            voice=config.voice,
            temperature=config.temperature,
            max_response_output_tokens=config.max_response_output_tokens,
            modalities=config.modalities,
            turn_detection=config.turn_detection,
        )
        assistant = MultimodalAgent(model=model, fnc_ctx=fnc_ctx)
        assistant.start(ctx.room)
        
        session = model.sessions[0]

        if config.modalities == ["text", "audio"]:
            session.conversation.item.create(
                llm.ChatMessage(
                    role="user",
                    content="Please begin the interaction with the user in a manner consistent with your instructions.",
                )
            )
            session.response.create()

        @ctx.room.local_participant.register_rpc_method("pg.updateConfig")
        async def update_config(
            data: rtc.rpc.RpcInvocationData,
        ):
            if data.caller_identity != participant.identity:
                return

            new_config = parse_session_config(json.loads(data.payload))
            if config != new_config:
                logger.info(
                    f"config changed: {new_config.to_dict()}, participant: {participant.identity}"
                )
                session = model.sessions[0]
                session.session_update(
                    instructions=new_config.instructions,
                    voice=new_config.voice,
                    temperature=new_config.temperature,
                    max_response_output_tokens=new_config.max_response_output_tokens,
                    turn_detection=new_config.turn_detection,
                    modalities=new_config.modalities,
                )
                return json.dumps({"changed": True})
            else:
                return json.dumps({"changed": False})

        @session.on("response_done")
        def on_response_done(response: openai.realtime.RealtimeResponse):
            variant: Literal["warning", "destructive"]
            description: str | None = None
            title: str
            if response.status == "incomplete":
                if response.status_details and response.status_details["reason"]:
                    reason = response.status_details["reason"]
                    if reason == "max_output_tokens":
                        variant = "warning"
                        title = "Max output tokens reached"
                        description = "Response may be incomplete"
                    elif reason == "content_filter":
                        variant = "warning"
                        title = "Content filter applied"
                        description = "Response may be incomplete"
                    else:
                        variant = "warning"
                        title = "Response incomplete"
                else:
                    variant = "warning"
                    title = "Response incomplete"
            elif response.status == "failed":
                if response.status_details and response.status_details["error"]:
                    error_code = response.status_details["error"]["code"]
                    if error_code == "server_error":
                        variant = "destructive"
                        title = "Server error"
                    elif error_code == "rate_limit_exceeded":
                        variant = "destructive"
                        title = "Rate limit exceeded"
                    else:
                        variant = "destructive"
                        title = "Response failed"
                else:
                    variant = "destructive"
                    title = "Response failed"
            else:
                return

            asyncio.create_task(show_toast(title, description, variant))

        async def send_transcription(
            ctx: JobContext,
            participant: rtc.Participant,
            track_sid: str,
            segment_id: str,
            text: str,
            is_final: bool = True,
        ):
            transcription = rtc.Transcription(
                participant_identity=participant.identity,
                track_sid=track_sid,
                segments=[
                    rtc.TranscriptionSegment(
                        id=segment_id,
                        text=text,
                        start_time=0,
                        end_time=0,
                        language="en",
                        final=is_final,
                    )
                ],
            )
            await ctx.room.local_participant.publish_transcription(transcription)

        async def show_toast(
            title: str,
            description: str | None,
            variant: Literal["default", "success", "warning", "destructive"],
        ):
            await ctx.room.local_participant.perform_rpc(
                destination_identity=participant.identity,
                method="pg.toast",
                payload=json.dumps(
                    {"title": title, "description": description, "variant": variant}
                ),
            )

        last_transcript_id = None

        @session.on("input_speech_started")
        def on_input_speech_started():
            nonlocal last_transcript_id
            remote_participant = next(iter(ctx.room.remote_participants.values()), None)
            if not remote_participant:
                return

            track_sid = next(
                (
                    track.sid
                    for track in remote_participant.track_publications.values()
                    if track.source == rtc.TrackSource.SOURCE_MICROPHONE
                ),
                None,
            )
            if last_transcript_id:
                asyncio.create_task(
                    send_transcription(
                        ctx, remote_participant, track_sid, last_transcript_id, ""
                    )
                )

            new_id = str(uuid.uuid4())
            last_transcript_id = new_id
            asyncio.create_task(
                send_transcription(
                    ctx, remote_participant, track_sid, new_id, "…", is_final=False
                )
            )

        @session.on("input_speech_transcription_completed")
        def on_input_speech_transcription_completed(
            event: openai.realtime.InputTranscriptionCompleted,
        ):
            nonlocal last_transcript_id
            if last_transcript_id:
                remote_participant = next(iter(ctx.room.remote_participants.values()), None)
                if not remote_participant:
                    return

                track_sid = next(
                    (
                        track.sid
                        for track in remote_participant.track_publications.values()
                        if track.source == rtc.TrackSource.SOURCE_MICROPHONE
                    ),
                    None,
                )
                asyncio.create_task(
                    send_transcription(
                        ctx, remote_participant, track_sid, last_transcript_id, ""
                    )
                )
                last_transcript_id = None

        @session.on("input_speech_transcription_failed")
        def on_input_speech_transcription_failed(
            event: openai.realtime.InputTranscriptionFailed,
        ):
            nonlocal last_transcript_id
            if last_transcript_id:
                remote_participant = next(iter(ctx.room.remote_participants.values()), None)
                if not remote_participant:
                    return

                track_sid = next(
                    (
                        track.sid
                        for track in remote_participant.track_publications.values()
                        if track.source == rtc.TrackSource.SOURCE_MICROPHONE
                    ),
                    None,
                )

                error_message = "⚠️ Transcription failed"
                asyncio.create_task(
                    send_transcription(
                        ctx,
                        remote_participant,
                        track_sid,
                        last_transcript_id,
                        error_message,
                    )
                )
                last_transcript_id = None

    except Exception as e:
        logger.error(f"Error in multimodal agent: {str(e)}")
        await show_toast(
            "Connection Error",
            "Failed to initialize the agent. Please try reconnecting.",
            "destructive"
        )
        raise

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, worker_type=WorkerType.ROOM))
