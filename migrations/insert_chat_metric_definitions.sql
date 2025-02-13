-- Category Classification Metric
INSERT INTO chat_metric_definitions (
    name,
    description,
    prompt,
    model,
    refresh_interval_hours,
    is_preset
) VALUES (
    'group_category_classification',
    'Classifies Telegram groups into categories like PORTAL_GROUP, CRYPTO_PROJECT, KOL, etc.',
    E'You are a Web3 community manager analyzing Telegram groups. Your task is to classify groups based on their content and characteristics.\n\nCLASSIFICATION CATEGORIES:\n\nPORTAL_GROUP\n- Primary indicators:\n  * Group name typically contains "Portal"\n  * Contains bot verification messages (Safeguard, Rose, Captcha)\n  * Has "verify", "tap to verify" or "human verification" button/link\n  * Very few messages posted by the group owner, no user messages and no recent messages\n\nCRYPTO_PROJECT\n- Primary indicators:\n  * Smart contract address in description/pinned\n  * Group name often includes token ticker with $ (e.g., $BOX)\n  * Project details in pinned messages/description\n  * Keywords: tokenomics, whitepaper, roadmap\n\nKOL\n- Primary indicators:\n  * Group name/description features specific individual\n  * KOL''s username and introduction in description\n  * Keywords: exclusive content, signals, alpha\n\nVIRTUAL_CAPITAL\n- Primary indicators:\n  * Contains "VC" or "Venture Capital" in name/description\n  * Keywords: investment strategy, portfolio, institutional\n\nEVENT\n- Primary indicators:\n  * Group name includes event name/date\n  * Contains event registration links\n  * Keywords: meetup, conference, hackathon, RSVP\n\nTECH_DISCUSSION\n- Primary indicators:\n  * Group name/description mentions technical focus\n  * Contains code discussions/snippets\n  * Keywords: dev, protocol, smart contract, architecture\n\nFOUNDER\n- Primary indicators:\n  * Group name contains "founder" or "startup"\n  * Founder-focused discussions in description\n  * Keywords: fundraising, startup, founder\n\nOTHERS\n- Use when no other category fits clearly\n\nOutput format:\n{\n    "value": "CATEGORY_NAME",\n    "confidence": 0-100,\n    "reason": "Explanation for the classification and confidence level"\n}',
    'gpt-4',
    24,
    true
);

-- Entity Extraction Metric
-- INSERT INTO chat_metric_definitions (
--     name,
--     description,
--     prompt,
--     model,
--     refresh_interval_hours,
--     is_preset
-- ) VALUES (
--     'group_entity_extraction',
--     'Extracts relevant entity data based on group category (CRYPTO_PROJECT, KOL, or VIRTUAL_CAPITAL)',
--     E'You are a Web3 data extractor. Your task is to extract structured entity data from group information based on the group''s category.\n\nEntity Schema by Category:\n\nFor CRYPTO_PROJECT:\n{\n    "ticker": "",\n    "chain": "",\n    "contract": "",\n    "website": "",\n    "name": "",\n    "social": {\n        "twitter": "",\n        "other": []\n    }\n}\n\nFor KOL:\n{\n    "name": "",\n    "username": "",\n    "website": "",\n    "social": {\n        "twitter": "",\n        "telegram": "",\n        "linkedin": "",\n        "other": []\n    }\n}\n\nFor VIRTUAL_CAPITAL:\n{\n    "name": "",\n    "website": "",\n    "social": {\n        "twitter": "",\n        "linkedin": ""\n    }\n}\n\nGuidelines:\n- Extract all available information from the group description, pinned messages, and recent messages\n- Only extract information you are highly confident about\n- For other categories, return null\n- If data is insufficient, return null with 0 confidence\n\nOutput format:\n{\n    "value": {"entity_data": entity_object_or_null},\n    "confidence": 0-100,\n    "reason": "Explanation for the extracted data and confidence level"\n}',
--     'gpt-4',
--     24,
--     true
-- );