import math
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
from sqlmodel import Session, select

from app.models import Player, Season, PlayerSeasonStats, Team, PlayerAdvancedStats, PlayerContract
from app.schemas import (
    FinancialAnalyticsResponse,
    ContractDetailItem,
    TeamPayrollSummary,
)
from app.services.training import _normalize_str


CURRENT_SALARY_CAP: float = 140588000.0  # $140.6M 2024-25 Cap
CURRENT_LUXURY_TAX: float = 170814000.0  # $170.8M Luxury Tax Threshold

# Comprehensive NBA Contract Baseline Data for Top Players
NBA_CONTRACT_MASTER_DATA: Dict[str, Dict[str, Any]] = {
    "Stephen Curry": {"salary": 51915615.0, "type": "Supermax", "years": 2, "fa": 2026},
    "Nikola Jokic": {"salary": 47607350.0, "type": "Supermax", "years": 4, "fa": 2028},
    "Nikola Jokić": {"salary": 47607350.0, "type": "Supermax", "years": 4, "fa": 2028},
    "LeBron James": {"salary": 47607350.0, "type": "Max Veteran", "years": 2, "fa": 2026},
    "Joel Embiid": {"salary": 47607350.0, "type": "Supermax", "years": 3, "fa": 2027},
    "Kevin Durant": {"salary": 47649433.0, "type": "Supermax", "years": 2, "fa": 2026},
    "Giannis Antetokounmpo": {"salary": 45640084.0, "type": "Supermax", "years": 3, "fa": 2027},
    "Damian Lillard": {"salary": 45640084.0, "type": "Supermax", "years": 3, "fa": 2027},
    "Kawhi Leonard": {"salary": 45640084.0, "type": "Max Veteran", "years": 3, "fa": 2027},
    "Paul George": {"salary": 45640084.0, "type": "Max Veteran", "years": 4, "fa": 2028},
    "Jimmy Butler": {"salary": 45183960.0, "type": "Max Veteran", "years": 2, "fa": 2026},
    "Luka Doncic": {"salary": 40064220.0, "type": "Max Designated", "years": 3, "fa": 2027},
    "Luka Dončić": {"salary": 40064220.0, "type": "Max Designated", "years": 3, "fa": 2027},
    "Trae Young": {"salary": 40064220.0, "type": "Max Designated", "years": 3, "fa": 2027},
    "Shai Gilgeous-Alexander": {"salary": 33386840.0, "type": "Max Designated", "years": 3, "fa": 2027},
    "Jayson Tatum": {"salary": 32600060.0, "type": "Supermax Extension", "years": 5, "fa": 2029},
    "Devin Booker": {"salary": 36016200.0, "type": "Supermax", "years": 4, "fa": 2028},
    "Anthony Edwards": {"salary": 13534817.0, "type": "Rookie Scale", "years": 5, "fa": 2029},
    "Tyrese Haliburton": {"salary": 35859950.0, "type": "Max Designated", "years": 5, "fa": 2029},
    "Victor Wembanyama": {"salary": 12160680.0, "type": "Rookie Scale (#1 Pick)", "years": 3, "fa": 2027},
    "Chet Holmgren": {"salary": 10404000.0, "type": "Rookie Scale (#2 Pick)", "years": 2, "fa": 2026},
    "Jalen Brunson": {"salary": 26346666.0, "type": "Mid-Scale Bargain", "years": 4, "fa": 2028},
    "Derrick White": {"salary": 18357143.0, "type": "Starter Value", "years": 4, "fa": 2028},
    "Alex Caruso": {"salary": 9400000.0, "type": "Defensive Bargain", "years": 2, "fa": 2026},
    "Donte DiVincenzo": {"salary": 11440000.0, "type": "Mid-Level Value", "years": 3, "fa": 2027},
    "Austin Reaves": {"salary": 12015150.0, "type": "Early Bird Bargain", "years": 3, "fa": 2027},
    "Herb Jones": {"salary": 12000000.0, "type": "Elite Wing Bargain", "years": 3, "fa": 2027},
    "Naz Reid": {"salary": 12950000.0, "type": "6th Man Value", "years": 2, "fa": 2026},
}


class FinancialService:
    def __init__(self, session: Session):
        self.session = session

    def get_financial_analytics(self) -> FinancialAnalyticsResponse:
        # Retrieve recent season (e.g. 2023-24 or active)
        active_season = self.session.exec(
            select(Season).order_by(Season.id.desc())
        ).first()

        if not active_season:
            raise ValueError("No seasons available in database")

        all_stats = self.session.exec(
            select(PlayerSeasonStats).where(
                PlayerSeasonStats.season_id == active_season.id,
                PlayerSeasonStats.gp >= 15,
            )
        ).all()

        contracts_list: List[ContractDetailItem] = []

        for stat in all_stats:
            player = self.session.get(Player, stat.player_id)
            team = self.session.get(Team, stat.team_id) if stat.team_id else None
            if not player:
                continue

            adv_stat = self.session.exec(
                select(PlayerAdvancedStats).where(
                    PlayerAdvancedStats.player_id == player.id,
                    PlayerAdvancedStats.season_id == active_season.id,
                )
            ).first()

            # Contract lookup
            c_info = None
            clean_name = _normalize_str(player.full_name)
            for m_name, m_data in NBA_CONTRACT_MASTER_DATA.items():
                if _normalize_str(m_name) == clean_name:
                    c_info = m_data
                    break

            gp = max(stat.gp or 1, 1)
            ppg = max(round((stat.pts or 0.0) / gp, 1), 1.0)
            ws = max(adv_stat.ws if adv_stat and adv_stat.ws else (ppg * 0.25), 0.5)

            if c_info:
                salary = c_info["salary"]
                c_type = c_info["type"]
                years = c_info["years"]
                fa_year = c_info["fa"]
            else:
                # Deterministic scale estimation based on PPG and experience
                if ppg >= 25.0:
                    salary = 38500000.0
                    c_type = "Max Starter"
                    years = 3
                    fa_year = 2027
                elif ppg >= 18.0:
                    salary = 24000000.0
                    c_type = "Core Starter"
                    years = 3
                    fa_year = 2027
                elif ppg >= 12.0:
                    salary = 14000000.0
                    c_type = "Rotation Starter"
                    years = 2
                    fa_year = 2026
                else:
                    salary = 4500000.0
                    c_type = "Rotation Specialist"
                    years = 1
                    fa_year = 2025

            cap_pct = round((salary / CURRENT_SALARY_CAP) * 100.0, 1)
            cost_per_pt = round(salary / (ppg * gp), 0) if (ppg * gp) > 0 else salary
            cost_per_ws = round(salary / ws, 0) if ws > 0 else salary

            # Surplus Value Model (Market Production Value - Real Salary)
            # Market value = $2.8M baseline + $1.4M per PPG + $3.2M per Win Share
            market_val = 2800000.0 + (ppg * 1400000.0) + (ws * 3200000.0)
            surplus = market_val - salary
            surplus_score = round(float(np.clip(50.0 + (surplus / 1000000.0) * 2.0, 1.0, 99.0)), 1)

            if surplus_score >= 80.0:
                tier = "elite_bargain"
            elif surplus_score >= 60.0:
                tier = "high_value"
            elif surplus_score >= 40.0:
                tier = "fair_value"
            else:
                tier = "overpaid"

            contracts_list.append(
                ContractDetailItem(
                    player_id=player.id,
                    player_name=player.full_name,
                    team_abbreviation=team.abbreviation if team else "NBA",
                    team_name=team.full_name if team else "NBA Team",
                    annual_salary=salary,
                    salary_formatted=f"${round(salary / 1000000.0, 1)}M",
                    cap_hit_pct=cap_pct,
                    contract_type=c_type,
                    years_remaining=years,
                    free_agency_year=fa_year,
                    cost_per_pt=cost_per_pt,
                    cost_per_ws=cost_per_ws,
                    surplus_value_rating=surplus_score,
                    value_tier=tier,
                )
            )

        # Top Bargains (Highest Surplus Value Rating)
        top_bargains = sorted(contracts_list, key=lambda c: c.surplus_value_rating, reverse=True)[:10]

        # Top Salaries (Highest Annual Salary)
        top_salaries = sorted(contracts_list, key=lambda c: c.annual_salary, reverse=True)[:10]

        # Aggregate Team Payrolls
        team_dict: Dict[str, List[ContractDetailItem]] = {}
        for c in contracts_list:
            team_dict.setdefault(c.team_abbreviation, []).append(c)

        team_payrolls: List[TeamPayrollSummary] = []
        all_teams = self.session.exec(select(Team)).all()
        for tm in all_teams:
            tm_contracts = team_dict.get(tm.abbreviation, [])
            total_pay = sum(c.annual_salary for c in tm_contracts)
            if total_pay == 0:
                total_pay = 138000000.0  # League average baseline if sparse

            cap_spc = round(CURRENT_SALARY_CAP - total_pay, 0)
            in_tax = total_pay > CURRENT_LUXURY_TAX

            top_tm_c = sorted(tm_contracts, key=lambda x: x.annual_salary, reverse=True)[:5]

            team_payrolls.append(
                TeamPayrollSummary(
                    team_id=tm.id,
                    team_abbreviation=tm.abbreviation,
                    team_name=tm.full_name,
                    total_payroll=total_pay,
                    payroll_formatted=f"${round(total_pay / 1000000.0, 1)}M",
                    salary_cap=CURRENT_SALARY_CAP,
                    luxury_tax_threshold=CURRENT_LUXURY_TAX,
                    cap_space=cap_spc,
                    is_in_luxury_tax=in_tax,
                    top_contracts=top_tm_c,
                )
            )

        team_payrolls.sort(key=lambda t: t.total_payroll, reverse=True)

        return FinancialAnalyticsResponse(
            salary_cap_current=CURRENT_SALARY_CAP,
            luxury_tax_current=CURRENT_LUXURY_TAX,
            top_bargain_contracts=top_bargains,
            top_salary_contracts=top_salaries,
            team_payrolls=team_payrolls,
        )
