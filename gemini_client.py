"""
gemini_client.py - Google Gemini Vision & Advisory Client for StadiumFlow

Uses the google-genai Python SDK to interface with Google Gemini.
Reads GEMINI_API_KEY from the environment to provide:
1. Grounded Q&A for attendees: answers fan questions in at most 3 sentences
   using ONLY the provided computed facts, falling back to plain facts if the
   key is missing or the call fails so the app never crashes.
2. Multimodal computer vision queue analysis and crowd density estimation.
3. Automated stadium PA and digital signage crowd diversion advisories.
"""

import base64
import json
import logging
import os
import re
from dotenv import load_dotenv

# Load environment variables (.env)
load_dotenv()

logger = logging.getLogger(__name__)


def format_facts_text(facts):
    """
    Normalizes facts into a clean, human-readable plain text string.

    Args:
        facts (str, dict, or list): The computed venue/facility facts.

    Returns:
        str: Plain text representation of the facts.
    """
    if isinstance(facts, str):
        return facts.strip()
    if isinstance(facts, dict):
        if "recommendation" in facts:
            rec = facts["recommendation"]
            extra = []
            if "walking_time" in facts and "waiting_time" in facts:
                extra.append(f"Walking time: {facts['walking_time']} min, Waiting time: {facts['waiting_time']} min, Total time: {facts.get('total_time', 0)} min")
            if extra:
                return f"{rec} ({', '.join(extra)})"
            return rec
        return "; ".join(f"{k}: {v}" for k, v in facts.items() if k != "facility")
    if isinstance(facts, (list, tuple)):
        return "\n".join(format_facts_text(item) for item in facts)
    return str(facts).strip()


def answer_fan_question(facts, question):
    """
    Answers a fan's question using Gemini 3.8 Flash, strictly constrained to computed facts.
    Returns a friendly answer of at most 3 sentences that uses ONLY those facts.
    If the API key is missing or the call fails, returns the plain facts text so the app never crashes.

    Args:
        facts (str, dict, or list): The verified stadium facts (e.g. wait times, walking times).
        question (str): The fan's query or concern.

    Returns:
        str: A friendly response of at most 3 sentences using only the computed facts,
             or the plain facts text as a safe fallback.
    """
    plain_facts = format_facts_text(facts)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    # If key is missing or is placeholder, return plain facts text immediately
    if not api_key or api_key.startswith("your_"):
        logger.info("GEMINI_API_KEY missing or placeholder; returning plain facts.")
        return plain_facts

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a helpful and friendly stadium assistant speaking directly to a fan at a sporting event.

COMPUTED FACTS:
{plain_facts}

FAN'S QUESTION:
{question}

STRICT INSTRUCTIONS:
1. Provide a warm, friendly answer to the fan's question in at most 3 sentences.
2. Use ONLY the computed facts provided above. Do not assume, invent, or extrapolate any outside details.
3. If the facts do not answer part of the question, politely explain what the facts confirm in at most 3 sentences.
"""

        interaction = client.interactions.create(
            model="gemini-3.8-flash",
            input=[{"type": "text", "text": prompt}]
        )

        output = (interaction.output_text or "").strip()
        if output:
            return output

        # If model returned empty text, return plain facts
        return plain_facts

    except Exception as e:
        logger.warning("Gemini Q&A call failed: %s. Returning plain facts.", e)
        return plain_facts


# Aliases for convenience
ask_gemini = answer_fan_question
ask_fan_assistant = answer_fan_question


class GeminiCrowdClient:
    """Client for multimodal Gemini crowd estimation and tactical coordination."""

    def __init__(self):
        """Initializes Gemini client reading API key from environment."""
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = "gemini-3.8-flash"
        self.client = None

        if self.api_key and not self.api_key.startswith("your_"):
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Google GenAI Client initialized successfully.")
            except Exception as e:
                logger.warning("Could not initialize Google GenAI Client: %s", e)
                self.client = None
        else:
            logger.warning("No valid GEMINI_API_KEY found; running in simulated mode.")

    def is_available(self):
        """Returns True if the live Gemini API client is initialized."""
        return self.client is not None

    def answer_fan_question(self, facts, question):
        """
        Answers a fan's question constrained to computed facts in at most 3 sentences.
        Falls back to plain facts if missing key or call fails.
        """
        return answer_fan_question(facts, question)

    def analyze_queue_image(self, image_bytes, mime_type="image/jpeg", zone_context=None):
        """
        Submits a queue photo or CCTV frame to Gemini Vision.
        Extracts headcount, density, wait times, chokepoint diagnosis, and staff actions.
        """
        zone_context = zone_context or {}
        zone_name = zone_context.get("name", "Stadium Facility")
        zone_type = zone_context.get("type", "queue")
        section = zone_context.get("section", "Concourse")

        # Fallback heuristic if API is unconfigured or unavailable
        if not self.is_available():
            return self._fallback_image_analysis(zone_context, reason="Gemini API key not configured or client offline.")

        try:
            base64_img = base64.b64encode(image_bytes).decode("utf-8")

            prompt = f"""
You are an expert stadium operations computer vision AI analyzing crowd queues and pedestrian flow at a major sporting event.
Analyze this photo from: {zone_name} (Category: {zone_type}, Location: {section}).

Assess the scene carefully and output ONLY a valid JSON object (no markdown, no extra commentary) with the following exact keys:
{{
  "headcount": <integer estimate of people visible in or joining the queue>,
  "density_level": "<'Low' | 'Moderate' | 'High' | 'Critical'>",
  "estimated_wait_minutes": <integer estimate of wait time in minutes>,
  "queue_flow_rate": "<'Moving Smoothly' | 'Slow Crawl' | 'Stationary / Blocked'>",
  "bottleneck_reason": "<1-sentence physical assessment of what is causing or avoiding delay>",
  "marshal_action": "<1-sentence tactical instruction for on-ground stadium stewards/staff>",
  "fan_advice": "<1-sentence helpful guidance for attendees in this area>",
  "confidence_score": <integer percentage between 75 and 98>
}}
"""

            interaction = self.client.interactions.create(
                model=self.model_name,
                input=[
                    {"type": "text", "text": prompt},
                    {"type": "image", "data": base64_img, "mime_type": mime_type}
                ]
            )

            raw_text = interaction.output_text or ""
            parsed = self._extract_json(raw_text)

            if parsed:
                parsed["is_simulated"] = False
                parsed["model_used"] = self.model_name
                return parsed

            logger.warning("Could not parse JSON from Gemini response: %s", raw_text)
            return self._fallback_image_analysis(zone_context, reason="Model response was not valid JSON.")

        except Exception as e:
            logger.error("Gemini Vision API error: %s", e)
            return self._fallback_image_analysis(zone_context, reason=f"Gemini API call failed: {str(e)}")

    def generate_advisory(self, zone_name, wait_minutes, alt_zone_name=None, alt_wait=None, time_saved=0):
        """
        Asks Gemini to generate a professional, calming stadium PA announcement / app alert.
        """
        if not self.is_available():
            if alt_zone_name and time_saved > 0:
                return (
                    f"Fan Flow Notice: {zone_name} is experiencing heavy demand (~{wait_minutes}m wait). "
                    f"Please proceed to {alt_zone_name} (~{alt_wait}m wait) to save approximately {time_saved} minutes."
                )
            return f"Notice: {zone_name} is experiencing high foot traffic (~{wait_minutes}m wait). Venue staff are assisting."

        try:
            alt_info = f"Alternative: {alt_zone_name} with only {alt_wait} min wait (saves ~{time_saved} min)." if alt_zone_name else "No alternative specified."
            prompt = f"""
Write a calm, authoritative, and concise 1-2 sentence stadium crowd alert for attendees:
- Affected Area: {zone_name} ({wait_minutes} min wait time)
- {alt_info}
Ensure the tone is helpful and prevents panic while motivating attendees to take the alternative path. Output only the text.
"""
            interaction = self.client.interactions.create(
                model=self.model_name,
                input=[{"type": "text", "text": prompt}]
            )
            return interaction.output_text.strip().replace('"', '')

        except Exception as e:
            logger.error("Gemini text advisory error: %s", e)
            return f"Crowd Update: High density at {zone_name} ({wait_minutes}m wait). Follow stewards to nearby facilities."

    def _extract_json(self, text):
        """Extracts JSON object from text, handling markdown code fences."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            return json.loads(cleaned)
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            return None

    def _fallback_image_analysis(self, zone_context, reason=None):
        """
        Intelligent simulation fallback so the system is 100% resilient
        during live pitches even if offline or without internet access.
        """
        base_count = zone_context.get("current_count", 45)
        service_rate = max(1, zone_context.get("service_rate_pm", 10))
        wait = max(1, round(base_count / service_rate))

        density = "Critical" if wait >= 14 else ("High" if wait >= 8 else "Moderate")

        return {
            "headcount": base_count,
            "density_level": density,
            "estimated_wait_minutes": wait,
            "queue_flow_rate": "Slow Crawl" if wait >= 8 else "Moving Smoothly",
            "bottleneck_reason": f"Elevated transaction volume at {zone_context.get('name', 'location')} with localized corridor compression.",
            "marshal_action": "Deploy 2 additional queue marshals and open overflow stanchions.",
            "fan_advice": f"Consider using adjacent facilities to avoid delays exceeding {wait} minutes.",
            "confidence_score": 86,
            "is_simulated": True,
            "fallback_reason": reason or "Simulated fallback"
        }
