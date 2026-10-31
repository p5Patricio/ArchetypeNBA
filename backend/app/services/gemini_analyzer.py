import json
import logging
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.services.injury_scraper import InjuryItem

logger = logging.getLogger(__name__)


class PlayerQualitativeModifier(BaseModel):
    player_name: str
    team: str
    status: str
    minute_multiplier: float = Field(default=1.0, ge=0.0, le=1.3)
    usage_multiplier: float = Field(default=1.0, ge=0.0, le=1.4)
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, EXTREME
    tactical_summary: str = ""


class SlateAnalysisResult(BaseModel):
    modifiers: List[PlayerQualitativeModifier] = []
    slate_summary: str = ""
    engine_source: str = "HEURISTIC"  # "GEMINI" or "HEURISTIC"
    model_used: Optional[str] = None


class GeminiAnalyzerService:
    """Uses Gemini API to extract qualitative modifiers and risk factors from unstructured news & injuries."""

    GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL or "gemini-3.8-flash"
        self.fallback_model = (
            fallback_model
            if fallback_model is not None
            else getattr(settings, "GEMINI_FALLBACK_MODEL", "gemini-3.6-flash")
        )
        self.transport = transport

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and "your_" not in self.api_key)

    def analyze_injuries_and_news(
        self,
        injury_items: List[InjuryItem],
        extra_notes: Optional[str] = None,
    ) -> SlateAnalysisResult:
        """
        Processes injury reports through Gemini 3.8 Flash with structured output.
        Falls back to rule-based heuristics if no API key is present or on API error.
        """
        if not injury_items:
            return SlateAnalysisResult(
                modifiers=[],
                slate_summary="No injury items to analyze.",
                engine_source="HEURISTIC",
                model_used=None,
            )

        if not self.is_configured:
            logger.info("GeminiAnalyzer: API Key not set. Using statistical heuristic analysis.")
            return self._heuristic_analysis(injury_items)

        report_text = "\n".join(
            [f"- {i.team} | {i.player_name} | Status: {i.status} | Reason: {i.reason}" for i in injury_items]
        )
        if extra_notes:
            report_text += f"\nAdditional Beat Notes:\n{extra_notes}"

        system_instruction = (
            "You are a world-class NBA sports analytics and player props modeling engine. "
            "Your task is to analyze the daily injury report and contextual news. "
            "For each key player mentioned (or teammate heavily impacted by an injury vacancy), "
            "estimate the minute_multiplier (0.0 if OUT, 0.7-0.85 if on minutes limit/questionable, 1.0 normal, 1.05-1.15 if taking extra minutes), "
            "usage_multiplier (0.0 if OUT, 1.0 normal, 1.08-1.25 if a primary scoring teammate is OUT), "
            "risk_level ('LOW', 'MEDIUM', 'HIGH', 'EXTREME'), and a concise tactical_summary. "
            "Return valid JSON adhering strictly to the requested schema."
        )

        prompt = f"Official Injury & Context Report:\n{report_text}\n\nExtract the qualitative modifiers for player props."

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}],
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            },
        }

        candidate_models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            candidate_models.append(self.fallback_model)

        client_kwargs = {"timeout": 35.0}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        for idx, model_name in enumerate(candidate_models):
            is_primary = (idx == 0)
            has_fallback = (is_primary and len(candidate_models) > 1)
            url = f"{self.GEMINI_API_ENDPOINT}/{model_name}:generateContent"

            try:
                with httpx.Client(**client_kwargs) as client:
                    res = client.post(url, json=payload, headers=headers)
                    if res.status_code in (404, 429):
                        if has_fallback:
                            logger.warning(
                                "GeminiAnalyzer: Model %s returned status %d. Retrying once with fallback model %s...",
                                model_name,
                                res.status_code,
                                self.fallback_model,
                            )
                            continue
                        else:
                            logger.warning(
                                "GeminiAnalyzer: Model %s returned status %d. No further fallback retries.",
                                model_name,
                                res.status_code,
                            )
                            break

                    res.raise_for_status()
                    data = res.json()
                    text_content = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_content)

                    logger.info("GeminiAnalyzer: Successfully generated analysis using model %s.", model_name)

                    # Handle if Gemini returned a list directly or a dict with modifiers
                    if isinstance(parsed, list):
                        modifiers = [PlayerQualitativeModifier(**item) for item in parsed]
                        return SlateAnalysisResult(
                            modifiers=modifiers,
                            slate_summary=f"Analyzed {len(modifiers)} players via Gemini AI ({model_name}).",
                            engine_source="GEMINI",
                            model_used=model_name,
                        )
                    elif isinstance(parsed, dict):
                        modifiers_raw = parsed.get("modifiers", parsed.get("players", []))
                        summary = parsed.get(
                            "slate_summary",
                            parsed.get("summary", f"Gemini Slate Analysis Complete ({model_name})."),
                        )
                        modifiers = [PlayerQualitativeModifier(**item) for item in modifiers_raw]
                        return SlateAnalysisResult(
                            modifiers=modifiers,
                            slate_summary=summary,
                            engine_source="GEMINI",
                            model_used=model_name,
                        )
            except Exception as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "[REDACTED]")
                logger.warning("GeminiAnalyzer: Attempt with %s failed: %s", model_name, err_msg)
                if has_fallback:
                    continue
                break

        logger.info("GeminiAnalyzer: All Gemini models busy/unavailable. Falling back to heuristic rules.")
        return self._heuristic_analysis(injury_items)

    def _heuristic_analysis(self, injury_items: List[InjuryItem]) -> SlateAnalysisResult:
        """Deterministic rule-based fallback when Gemini API is unavailable."""
        modifiers: List[PlayerQualitativeModifier] = []

        for item in injury_items:
            status_lower = item.status.lower()
            if "out" in status_lower:
                modifiers.append(
                    PlayerQualitativeModifier(
                        player_name=item.player_name,
                        team=item.team,
                        status="OUT",
                        minute_multiplier=0.0,
                        usage_multiplier=0.0,
                        risk_level="EXTREME",
                        tactical_summary=f"Confirmed OUT ({item.reason}). Zero projection.",
                    )
                )
            elif "doubtful" in status_lower:
                modifiers.append(
                    PlayerQualitativeModifier(
                        player_name=item.player_name,
                        team=item.team,
                        status="DOUBTFUL",
                        minute_multiplier=0.25,
                        usage_multiplier=0.8,
                        risk_level="HIGH",
                        tactical_summary=f"Doubtful ({item.reason}). Severe minute reduction expected.",
                    )
                )
            elif "questionable" in status_lower:
                modifiers.append(
                    PlayerQualitativeModifier(
                        player_name=item.player_name,
                        team=item.team,
                        status="QUESTIONABLE",
                        minute_multiplier=0.75,
                        usage_multiplier=0.9,
                        risk_level="MEDIUM",
                        tactical_summary=f"Questionable ({item.reason}). Likely game-time decision or cautious minutes.",
                    )
                )
            elif "probable" in status_lower:
                modifiers.append(
                    PlayerQualitativeModifier(
                        player_name=item.player_name,
                        team=item.team,
                        status="PROBABLE",
                        minute_multiplier=0.95,
                        usage_multiplier=1.0,
                        risk_level="LOW",
                        tactical_summary=f"Probable ({item.reason}). Expected to play near-normal rotation.",
                    )
                )
            else:
                # Available / healthy
                modifiers.append(
                    PlayerQualitativeModifier(
                        player_name=item.player_name,
                        team=item.team,
                        status="AVAILABLE",
                        minute_multiplier=1.0,
                        usage_multiplier=1.0,
                        risk_level="LOW",
                        tactical_summary=f"Fully available ({item.reason}). Standard baseline.",
                    )
                )

        return SlateAnalysisResult(
            modifiers=modifiers,
            slate_summary="Heuristic quantitative analysis applied based on official injury classifications.",
            engine_source="HEURISTIC",
            model_used=None,
        )
