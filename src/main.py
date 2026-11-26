from __future__ import annotations

import asyncio
import json
import os
import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

AI_BOTS = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,12}\b")
IGNORED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".css", ".js")
CTA_KEYWORDS = (
    "request a quote",
    "get a quote",
    "rfq",
    "book a demo",
    "schedule a demo",
    "contact sales",
    "inquire now",
    "whatsapp",
    "calendly.com",
)


class _PageAuditHTMLParser(HTMLParser):
    """Lightweight, zero-dependency HTML head/body signal extractor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_lang: str = ""
        self.title_parts: list[str] = []
        self._in_title = False
        self._in_h1 = False
        self._current_h1: list[str] = []
        self.h1_list: list[str] = []
        self._in_ld_json = False
        self._current_ld: list[str] = []
        self.ld_json_raw: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str = ""
        self.links: list[tuple[str, str]] = []
        self._in_a = False
        self._current_href = ""
        self._current_a_text: list[str] = []
        self.form_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t == "html" and not self.html_lang:
            self.html_lang = attr_map.get("lang", "").strip()
        elif t == "title":
            self._in_title = True
        elif t == "h1":
            self._in_h1 = True
            self._current_h1 = []
        elif t == "meta":
            key = (attr_map.get("name") or attr_map.get("property") or "").strip().lower()
            content = attr_map.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif t == "link":
            rel = attr_map.get("rel", "").lower()
            if "canonical" in rel and not self.canonical:
                self.canonical = attr_map.get("href", "").strip()
        elif t == "script":
            stype = attr_map.get("type", "").lower()
            if "application/ld+json" in stype:
                self._in_ld_json = True
                self._current_ld = []
        elif t == "a":
            self._in_a = True
            self._current_href = attr_map.get("href", "").strip()
            self._current_a_text = []
        elif t == "form":
            self.form_count += 1

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        elif t == "h1" and self._in_h1:
            self._in_h1 = False
            text = " ".join("".join(self._current_h1).split())
            if text:
                self.h1_list.append(text)
        elif t == "script" and self._in_ld_json:
            self._in_ld_json = False
            raw = "".join(self._current_ld).strip()
            if raw:
                self.ld_json_raw.append(raw)
        elif t == "a" and self._in_a:
            self._in_a = False
            text = " ".join("".join(self._current_a_text).split())
            self.links.append((self._current_href, text))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_h1:
            self._current_h1.append(data)
        if self._in_ld_json:
            self._current_ld.append(data)
        if self._in_a:
            self._current_a_text.append(data)


def _extract_schema_types(node: Any, collected: list[str]) -> None:
    if isinstance(node, dict):
        raw_type = node.get("@type")
        if isinstance(raw_type, str):
            collected.append(raw_type)
        elif isinstance(raw_type, list):
            collected.extend(str(x) for x in raw_type if x)
        for val in node.values():
            _extract_schema_types(val, collected)
    elif isinstance(node, list):
        for item in node:
            _extract_schema_types(item, collected)


def analyze_robots_txt(robots_text: str | None) -> dict[str, str]:
    """Check whether major AI search/LLM crawlers are allowed or blocked in robots.txt."""
    if not robots_text:
        return {bot: "allowed_default" for bot in AI_BOTS}

    rules_by_agent: dict[str, list[tuple[str, str]]] = {}
    current_agents: list[str] = []
    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = [p.strip() for p in line.split(":", 1)]
        fl = field.lower()
        if fl == "user-agent":
            agent_key = value.lower()
            current_agents = [agent_key]
            rules_by_agent.setdefault(agent_key, [])
        elif fl in ("disallow", "allow") and current_agents:
            for ag in current_agents:
                rules_by_agent.setdefault(ag, []).append((fl, value))

    status: dict[str, str] = {}
    wildcard_rules = rules_by_agent.get("*", [])
    for bot in AI_BOTS:
        bot_rules = rules_by_agent.get(bot.lower(), wildcard_rules)
        blocked = any(kind == "disallow" and path.strip() == "/" for kind, path in bot_rules)
        explicitly_allowed = any(kind == "allow" and path.strip() == "/" for kind, path in bot_rules)
        if blocked and not explicitly_allowed:
            status[bot] = "blocked"
        elif bot.lower() in rules_by_agent:
            status[bot] = "allowed_explicit"
        else:
            status[bot] = "allowed_default"
    return status


def parse_page_audit(
    url: str,
    final_url: str,
    status_code: int,
    latency_ms: int,
    html: str,
    has_llms_txt: bool,
    robots_txt: str | None,
) -> dict[str, Any]:
    """Produce a structured B2B GEO, Schema.org JSON-LD, and conversion audit item."""
    parser = _PageAuditHTMLParser()
    parser.feed(html)

    title = " ".join("".join(parser.title_parts).split())
    meta_desc = parser.meta.get("description", "")
    og_title = parser.meta.get("og:title", "")
    og_image = parser.meta.get("og:image", "")

    schema_types: list[str] = []
    invalid_ld_blocks = 0
    for raw_ld in parser.ld_json_raw:
        try:
            parsed = json.loads(raw_ld)
            _extract_schema_types(parsed, schema_types)
        except json.JSONDecodeError:
            invalid_ld_blocks += 1

    unique_schema_types = sorted(set(schema_types))
    lower_types = {t.lower() for t in unique_schema_types}
    has_org_schema = bool(lower_types & {"organization", "corporation", "localbusiness"})
    has_product_schema = bool(lower_types & {"product", "softwareapplication", "service", "offer"})
    has_faq_schema = "faqpage" in lower_types

    emails: set[str] = set()
    phones: set[str] = set()
    cta_matches: set[str] = set()

    for href, anchor_text in parser.links:
        hl = href.lower()
        combined = f"{hl} {anchor_text.lower()}"
        if hl.startswith("mailto:"):
            addr = href[7:].split("?", 1)[0].strip().lower()
            if addr and not addr.endswith(IGNORED_EMAIL_SUFFIXES):
                emails.add(addr)
        elif hl.startswith("tel:"):
            tel = href[4:].strip()
            if tel:
                phones.add(tel)
        for kw in CTA_KEYWORDS:
            if kw in combined:
                cta_matches.add(kw)

    for match in EMAIL_RE.findall(html):
        candidate = match.lower()
        if not candidate.endswith(IGNORED_EMAIL_SUFFIXES):
            emails.add(candidate)

    ai_bot_rules = analyze_robots_txt(robots_txt)
    blocked_ai_bots = [bot for bot, rule in ai_bot_rules.items() if rule == "blocked"]

    # Weighted 0-100 B2B GEO & Conversion Readiness Score
    score = 0
    recommendations: list[str] = []

    if title and 15 <= len(title) <= 75:
        score += 10
    else:
        recommendations.append("Optimize <title> length to 15-75 characters with primary B2B category intent.")

    if meta_desc and len(meta_desc) >= 50:
        score += 10
    else:
        recommendations.append("Add a descriptive <meta name='description'> (50-160 chars) for search & AI snippets.")

    if parser.h1_list:
        score += 10
    else:
        recommendations.append("Include a clear primary <h1> headline describing the core product or service.")

    if unique_schema_types:
        score += 15
    else:
        recommendations.append("Add Schema.org JSON-LD structured data (<script type='application/ld+json'>).")

    if has_org_schema:
        score += 10
    else:
        recommendations.append("Add Organization / LocalBusiness JSON-LD with logo, sameAs, and contactPoint.")

    if has_product_schema or has_faq_schema:
        score += 15
    else:
        recommendations.append("Add Product/Service or FAQPage JSON-LD so AI answer engines cite specs & pricing accurately.")

    if has_llms_txt:
        score += 10
    else:
        recommendations.append("Publish /llms.txt summarizing core products, specs, and documentation URLs for LLM agents.")

    if len(blocked_ai_bots) == 0:
        score += 10
    else:
        recommendations.append(f"Unblock AI search crawlers in robots.txt ({', '.join(blocked_ai_bots)}) if AI citation traffic is desired.")

    if parser.form_count > 0 or cta_matches or emails:
        score += 10
    else:
        recommendations.append("Expose a clear RFQ / Demo CTA, lead form, or sales contact email on the page.")

    return {
        "inputUrl": url,
        "finalUrl": final_url,
        "httpStatus": status_code,
        "latencyMs": latency_ms,
        "geoAndConversionScore": score,
        "seoBasics": {
            "htmlLang": parser.html_lang,
            "title": title,
            "metaDescription": meta_desc,
            "canonicalUrl": parser.canonical,
            "ogTitle": og_title,
            "hasOgImage": bool(og_image),
            "h1Count": len(parser.h1_list),
            "primaryH1": parser.h1_list[0] if parser.h1_list else "",
        },
        "jsonLdSchema": {
            "blockCount": len(parser.ld_json_raw),
            "invalidBlockCount": invalid_ld_blocks,
            "detectedTypes": unique_schema_types,
            "hasOrganizationSchema": has_org_schema,
            "hasProductOrServiceSchema": has_product_schema,
            "hasFaqSchema": has_faq_schema,
        },
        "aiSearchReadiness": {
            "hasLlmsTxt": has_llms_txt,
            "aiCrawlerRules": ai_bot_rules,
            "blockedAiCrawlers": blocked_ai_bots,
        },
        "b2bLeadSignals": {
            "formCount": parser.form_count,
            "detectedCtaIntents": sorted(cta_matches),
            "publicEmails": sorted(emails)[:10],
            "publicPhones": sorted(phones)[:10],
        },
        "recommendations": recommendations,
    }


def _normalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip()
    if not cleaned:
        return ""
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned


async def audit_single_url(client: httpx.AsyncClient, raw_url: str) -> dict[str, Any]:
    url = _normalize_url(raw_url)
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    t0 = time.perf_counter()
    try:
        page_task = client.get(url)
        llms_task = client.get(urljoin(origin, "/llms.txt"))
        robots_task = client.get(urljoin(origin, "/robots.txt"))
        page_resp, llms_resp, robots_resp = await asyncio.gather(
            page_task, llms_task, robots_task, return_exceptions=True
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if isinstance(page_resp, Exception):
            return {
                "inputUrl": raw_url,
                "finalUrl": url,
                "error": str(page_resp),
                "geoAndConversionScore": 0,
            }

        has_llms_txt = (
            not isinstance(llms_resp, Exception)
            and llms_resp.status_code == 200
            and len(llms_resp.text.strip()) > 20
            and "<html" not in llms_resp.text[:200].lower()
        )
        robots_txt = (
            robots_resp.text
            if (not isinstance(robots_resp, Exception) and robots_resp.status_code == 200)
            else None
        )

        return parse_page_audit(
            url=raw_url,
            final_url=str(page_resp.url),
            status_code=page_resp.status_code,
            latency_ms=latency_ms,
            html=page_resp.text,
            has_llms_txt=has_llms_txt,
            robots_txt=robots_txt,
        )
    except Exception as exc:  # pragma: no cover
        return {
            "inputUrl": raw_url,
            "finalUrl": url,
            "error": str(exc),
            "geoAndConversionScore": 0,
        }


async def main() -> None:
    from apify import Actor

    async with Actor:
        actor_input = await Actor.get_input() or {}
        urls: list[str] = actor_input.get("urls") or ["https://example.com"]
        timeout_secs = int(actor_input.get("timeoutSecs", 15))

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; B2BGeoSchemaAuditor/1.0; +https://apify.com/store)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        semaphore = asyncio.Semaphore(8)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_secs),
            follow_redirects=True,
            headers=headers,
        ) as client:

            async def _bounded_audit(u: str) -> dict[str, Any]:
                async with semaphore:
                    return await audit_single_url(client, u)

            results = await asyncio.gather(*(_bounded_audit(u) for u in urls if str(u).strip()))

        for item in results:
            await Actor.push_data(item)
            # Supports Apify Pay-Per-Event monetization when configured in Console
            if os.getenv("APIFY_IS_AT_HOME") == "1" and hasattr(Actor, "charge"):
                try:
                    await Actor.charge(event_name="url-audited", count=1)
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
