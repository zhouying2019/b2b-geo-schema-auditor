# B2B Website AI-Readiness (GEO), JSON-LD Schema & Lead Signal Auditor

An ultra-fast Python **Apify Actor** built for **SEO/GEO agencies, B2B lead-generation workflows (n8n / Make / Clay), and e-commerce consultants**.

Given a batch of company or product URLs, this Actor concurrently audits every target for:
1. **Schema.org JSON-LD Coverage**: Detects all `@type` entities (`Organization`, `Product`, `Service`, `SoftwareApplication`, `FAQPage`), malformed JSON-LD blocks, and high-intent B2B schema gaps.
2. **AI Search / GEO Readiness (`llms.txt` & AI Crawler Access)**: Verifies `/llms.txt` availability and parses `/robots.txt` permissions for `GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`, `PerplexityBot`, and `Google-Extended`.
3. **B2B Lead & Conversion Signals**: Extracts public sales emails, `tel:` numbers, inquiry form counts, and high-intent CTAs (`Request a Quote`, `RFQ`, `Book a Demo`, `Contact Sales`, `WhatsApp`, `Calendly`).
4. **0–100 Actionable GEO & Conversion Score**: Outputs prioritized engineering fixes ready to plug directly into automated cold-outreach audit reports or CRM enrichment tables.

---

## Sample Output Item

```json
{
  "inputUrl": "https://acme-industrial.example",
  "finalUrl": "https://acme-industrial.example/",
  "httpStatus": 200,
  "latencyMs": 312,
  "geoAndConversionScore": 85,
  "seoBasics": {
    "htmlLang": "en",
    "title": "Acme CNC Precision Machining | ISO 9001 Custom Parts",
    "metaDescription": "Custom 5-axis CNC machining with 48-hour rapid prototyping and global shipping.",
    "canonicalUrl": "https://acme-industrial.example/",
    "ogTitle": "Acme CNC Precision Machining",
    "hasOgImage": true,
    "h1Count": 1,
    "primaryH1": "Precision 5-Axis CNC Machining for Aerospace & Robotics"
  },
  "jsonLdSchema": {
    "blockCount": 2,
    "invalidBlockCount": 0,
    "detectedTypes": ["FAQPage", "Organization", "Product"],
    "hasOrganizationSchema": true,
    "hasProductOrServiceSchema": true,
    "hasFaqSchema": true
  },
  "aiSearchReadiness": {
    "hasLlmsTxt": false,
    "aiCrawlerRules": {
      "GPTBot": "allowed_default",
      "OAI-SearchBot": "allowed_default",
      "ChatGPT-User": "allowed_default",
      "ClaudeBot": "allowed_default",
      "PerplexityBot": "allowed_default",
      "Google-Extended": "allowed_default"
    },
    "blockedAiCrawlers": []
  },
  "b2bLeadSignals": {
    "formCount": 1,
    "detectedCtaIntents": ["request a quote", "rfq"],
    "publicEmails": ["sales@acme-industrial.example"],
    "publicPhones": ["+1-800-555-0199"]
  },
  "recommendations": [
    "Publish /llms.txt summarizing core products, specs, and documentation URLs for LLM agents."
  ]
}
```

---

## 3-Minute Apify Store Passive Monetization Setup (80% Revenue Share)

1. Push this directory to a GitHub repository under `zhouying2019` (e.g. `zhouying2019/b2b-geo-schema-auditor`).
2. Sign in to `https://console.apify.com` → **Actors** → **Create new** → **Link Git Repository**.
3. Click **Build** (uses `apify/actor-python:3.11`), then open **Publication** → **Monetization**:
   - Choose **Pay per event (PPE)**:
     - Event `url-audited`: **`$0.004` per URL** (`$4.00` per 1,000 audited B2B domains; Apify pays out **80%** of profit once balance reaches `$20` via PayPal / Wise).
4. Toggle **Publish to Apify Store**.
