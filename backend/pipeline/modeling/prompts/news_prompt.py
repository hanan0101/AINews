# Builds the news selection prompt used by the modeling stage.

from backend.config.settings import AI_UPDATES_LOOKBACK_DAYS, NEWS_SECTORS, recency_cutoff_query_token, utc_now


USER_ARABIC_STYLE_RULES = """
## ARABIC SUMMARY

Write the summary as ONE flowing Arabic paragraph, not a list of separate templated sentences.

Structure (match newsletter style exactly):
- Open directly with the verb of launch/update + the product name in parentheses + the exact new feature (no throat-clearing intro).
- Chain the remaining details as coordinated clauses joined by connectors like "كما"، "مع"، "بحيث"، "ويدعم"، "دون"، "مما يتيح" — do NOT break them into separate numbered sentences. The paragraph should read as 1 to 2 sentences total, ending in a single closing period, exactly like a real editorial brief.
- Every clause must state a concrete, source-mentioned detail (a number, a duration, a named capability, a named limitation) — never a vague benefit statement.
- If there's a limitation or availability condition, fold it into the same flowing paragraph using "دون" or "مع" — do not add it as a separate 4th sentence.
- The paragraph MUST end with a single Arabic full stop "." — never end on a comma، a dangling connector، or with no closing punctuation at all.

Fixed length rule (STRICT):
- Target exactly 50 to 55 Arabic words. This is not a flexible range — treat it as a fixed length matching the first two cards of the reference newsletter, so the text fills exactly 4 display lines without overflow or clipping.
- Do not go under 48 or over 56 words under any circumstance. If the source has more detail than fits, cut secondary details rather than exceeding the word count.

Verb variety rule (STRICT):
- Vary the opening verb across different cards in the same newsletter batch. Rotate among verbs like: أطلقت، قدّمت، أضافت، أعلنت، كشفت، دشّنت، وفّرت — matching whichever fits the actual action described.
- Never repeat the exact same opening verb in two consecutive cards being generated in the same batch.
- Never use "صار" anywhere in the text to express a change of state or a new capability. Use "أصبح" instead (e.g. "أصبح بإمكان المستخدم..." not "صار بإمكان المستخدم...").
- Avoid mechanical, templated repetition of the exact same clause structure card after card (e.g. always "بحيث يمكن للمستخدم..." verbatim) — rephrase the connective structure naturally per card while keeping the same information density.

Proofreading rule (STRICT):
- The Arabic text must be fully free of spelling errors, missing/extra letters, incorrect hamza placement (أ إ ا ء), and typos in product names.
- Re-read the generated sentence once before finalizing and silently correct any spelling or grammatical slip — do not output a draft with visible errors.

Tone and style rules:
- The title must be polished Modern Standard Arabic, 6 to 8 words.
- The title must reflect the exact meaning of the specific update: product + concrete feature/action, not a generic AI headline.
- The title must not exaggerate or market the update; it should say what changed precisely.
- Put every English product name, company name, acronym, model name, or technical term inside one clean pair of parentheses.
- Never create nested parentheses. Write (Nano Banana 2), not (Nano (Banana) 2).
- Do not write foreign company names in Arabic transliteration when the source uses English. Use (Google), (Claude), (Runway), etc.
- Never use generic titles such as "تحديث جديد للذكاء الاصطناعي" or "ميزة ذكاء اصطناعي جديدة".
- Base the paragraph only on features, changes, access path, and limits explicitly mentioned in the source.
- Do not force a closing sentence that names a user category such as للمستخدمين، للمصممين، للمبدعين، للفرق، أو للمهنيين.
- Do not use source filler anywhere, including "كما ذكر المصدر", "وفقًا للمصدر", "بحسب المصدر", "نُشر في المدونة الرسمية", "ضمن تحديثات مايو 2026", or any clause whose only job is to name the source/date.
- Keep source/date context in official_url and published_date only; the Arabic summary must focus on the actual feature, access path, and user-facing change.
- Do not repeat the title wording inside the description.
- Do not repeat the product name more than once.
- No promotional words: ثوري، رائد، قوي، مذهل، يغير قواعد اللعبة.
- Avoid vague endings like "يساعد المستخدمين" أو "يوفر تجربة أفضل" unless the source names a concrete feature immediately.

## very important TERMINOLOGY SIMPLIFICATION
replace technical terms with plain Arabic:
- وكيل / عميل ذكاء اصطناعي -> مساعد ذكي
- نموذج لغوي كبير / LLM -> نموذج ذكاء اصطناعي
- مدخلات / إدخال -> أوامر أو طلبات
- استدلال / inference -> معالجة
- واجهة برمجة / API -> (API) مع شرح بسيط إن لزم
- تضمينات / embeddings -> تحليل المحتوى
- ضبط دقيق / fine-tuning -> تدريب مخصص
- أتمتة سير العمل -> أتمتة المهام
- متعدد الوسائط / multimodal -> يدعم النص والصوت والصورة
""".strip()


# Builds the full news-selection prompt for the configured target count.
# Builds the full news-selection prompt for the configured target count.
def build_news_prompt(target_limit: int, *, single: bool = False, batch_mode: bool = False) -> str:
    _ = single
    target_per_level = max(1, target_limit // 3)
    culture_sectors = (
        "museums, films, heritage, fashion, libraries, music, visual arts, "
        "literature, cooking, architecture, theater, creative workflows, "
        "culture, knowledge research"
    )
    if batch_mode:
        selection_instructions = f"""
STEP 2 - BATCH SELECTION
Input: qualified list from STEP 1 for this small batch only.
Output: up to {target_limit} accepted items from this batch.

This is only one batch from a larger run. Do not try to build the final
12-card newsletter bank here. Do not enforce 4 Beginner, 4 Intermediate,
and 4 Advanced inside this batch.

Return fewer than {target_limit} items if only a few candidates qualify.
Return an empty latest_updates array if none qualify.

Within the accepted items in this batch:
- Prefer broadly available, user-facing AI tool/product updates.
- Avoid developer-only API/SDK/framework/coding-agent updates unless the
  update has clear non-technical user value.
- Prefer concrete stories with one named launch, rollout, or feature over
  generic changelog pages, vague update indexes, or brand storytelling posts.
- Classify each accepted item as beginner, intermediate, or advanced.
- Set is_highlight=false for batch items unless one item is clearly the
  strongest item in this batch.


  
""".strip()
    else:
        selection_instructions = f"""
STEP 2 - DIVERSITY AND ORDERING
Input: qualified list from STEP 1
Output: final ordered list of {target_limit} items

COMPANY RULE:
Never select more than 2 items from the same company or product owner.

USER VALUE PRIORITY:
Company diversity is a secondary objective.
Never reject a significantly stronger user-facing update simply to increase company diversity.
If two stories have similar value, then use diversity as the tie-breaker.

FIRST 6 SLOTS:
1. At least 2 items must connect to CULTURE_SECTORS.
2. No single category may occupy more than 2 of the first 6 slots.
3. Fill remaining slots with the strongest items across different sectors.
4. If fewer than 2 culture items exist, fill with the next strongest items.

RANKING PRIORITY:
Rank accepted candidates using this order:
1. New capability users can immediately use.
2. Significant improvement to an existing feature.
3. Public rollout of an important capability.
4. Major workflow or productivity improvement.
5. New AI model integrated into an existing product.
6. Everything else.
Always prefer user impact over company prestige.

REMAINING SLOTS:
Cover sectors not already represented in the first 6.
Do not repeat the same sector path if a strong alternative exists.

HIGHLIGHT RULE:
Set is_highlight=true on exactly one item that delivers the biggest practical
improvement for the largest number of users, published inside the
{AI_UPDATES_LOOKBACK_DAYS}-day window.
Prefer:
- Major new capabilities.
- Widely available rollouts.
- Features users can immediately benefit from.
Do not choose marketing announcements or company news as the highlight unless
no stronger product update exists.

BACKUP SLOTS:
Fill backup positions with items that cover missing sectors first.
If enough qualified items exist, return exactly {target_limit} items.

LEVEL BANK REQUIREMENT:
For a full newsletter run with {target_limit} items, prepare a balanced bank:
- exactly {target_per_level} Beginner items,
- exactly {target_per_level} Intermediate items,
- exactly {target_per_level} Advanced items.
Do not repeat the same story, product feature, URL, or near-duplicate wording across levels.
""".strip()

    if batch_mode:
        user_value_validation = ""
    else:
        user_value_validation = f"""
STEP 3 - USER VALUE VALIDATION
Before finalizing the selected items, compare all accepted candidates.

For every candidate ask:
1. Can users try this today?
2. Does it unlock a new capability?
3. Will existing users immediately notice the improvement?
4. Is this more than a marketing announcement?
5. Would an AI user be excited to see this in a newsletter?

Candidates answering YES to at least four questions should be ranked above
candidates answering YES to fewer questions.

If replacing one selected story with one rejected story increases the overall
practical value of the newsletter, make that replacement.

SOURCE QUALITY RE-CHECK:
Before finalizing, re-verify that no selected item slipped through despite
being a tutorial/how-to article or a roundup/index source (see STEP 1 rejection
rules). If one did, drop it and promote the next strongest qualified candidate
in its place, even if that candidate belongs to a less "official" source.
""".strip()

    return f"""
You are selecting AI product updates for an Arabic newsletter.
Use this same quality bar for both full newsletter generation and single-card replacement.
Use only the provided Exa and SearXNG candidates. Do not invent or add outside sources.
Current date: {utc_now().date().isoformat()}.
Approved sector labels: {", ".join(NEWS_SECTORS)}.
CULTURE_SECTORS: {culture_sectors}.

STEP 1 - FILTERING
Input: all Exa and SearXNG candidates
Output: qualified list

Do not proceed to STEP 2 until all candidates have been evaluated.
Use only the provided candidates. Do not invent or add outside sources.
The acceptance window is the last {AI_UPDATES_LOOKBACK_DAYS} days,
starting {recency_cutoff_query_token()}.

ACCEPT if ALL of the following are true:
- The item describes a concrete AI product update: a launch, new feature, rollout, changelog, release note, or now-available announcement.
- The product has a clear owner, a public user-facing surface, and broad availability.
- The specific update itself is broadly available.
- A general user can understand what the product does and where to use it.
- The update touches daily life, creative work, productivity, education, culture, or knowledge research.
- Source coverage is credible and not an SEO listicle or PR newswire.
- The candidate has enough detail to explain what changed and why a user should care.

USER IMPACT REQUIREMENT:
The update must provide a clear, user-visible improvement.
Strong acceptance signals include:
- A new feature users can use immediately.
- A new AI capability.
- Better image, video, voice, or text generation.
- Better reasoning or quality.
- Faster or simpler workflows.
- New multimodal functionality.
- Major productivity improvements.
- Public rollout of a previously limited feature.
- New integrations that expand what users can do.
A reader should be able to answer: "What can I do today that I couldn't do before?"

ALSO ACCEPT if:
- The update is from SDAIA or a Saudi AI product with national-level availability.
- The update is an Arabic-language AI tool available across the Arab world.

REJECT if ANY of the following are true:
- The story is local, narrow, one-client, one-city, or pilot-only with no broad public availability.
- The update is available in only one country or a small country group with no broader rollout.
- The story is mainly about Facebook, Android, Google Play, or generic mobile app notices.
- The story only says a model is listed on a catalog, model hub, benchmark page, or provider listing.
- The story is mainly consumer hardware or devices.
- The product is unknown, regional-only, a one-client pilot, or demo-only enterprise tooling.
- The content is funding, stock, legal, research-only, SDK/API-only, infrastructure, GPU, event-only, or non-AI technical news.
- The source is a documentation index, changelog landing page, help article, or broad roundup without one clear update.
- The candidate is an old evergreen/product page, a vague official news index, or a story where the AI update is not specific.

ALSO REJECT OR STRONGLY DEPRIORITIZE IF:
- The story is mainly corporate branding.
- The story is primarily marketing.
- The story is a customer case study.
- The story is an executive interview.
- The story is a vision or strategy announcement.
- The story describes internal infrastructure only.
- The update has no obvious practical benefit for end users.
- The update is technically correct but users gain little or nothing new.
- The article is a tutorial, how-to, guide, "ways to use", or explainer piece that
  teaches usage of a tool rather than reporting an actual new update, feature,
  or release. Mentioning a product name inside a how-to/educational article does
  NOT make it a qualifying update — reject it even if it looks informative.
- The source page is a company blog homepage, news index, press-release feed,
  or "latest updates" listing page that aggregates multiple unrelated
  announcements, rather than a dedicated article/post about one specific update.
  If the candidate text reads like a list of several different releases instead
  of one concrete story, reject it.

LOCAL RELEVANCE EXCEPTION:
Do not apply the "local, narrow, one-country" rejection rules above to a
Saudi or Arabic-language AI update with national-level or Arab-world
availability. Such stories should be treated as broadly available for
acceptance purposes and given added selection weight over an equally
strong international story in later ranking steps.

NOTE ON INFERENCE:
Scan the full body for availability restrictions such as available in, rolling out to,
starting with, limited to, developers only, waitlist, beta, early access, or not yet available in.
If a restriction is clearly present and no broader rollout is mentioned, reject the candidate.
Also scan for structural signals of a tutorial (numbered "how to" steps, "in this article we will show you")
or of a roundup/index page (multiple distinct product names each with their own short blurb,
"latest news" or "this week in AI" framing). Reject on either signal even if the writing seems detailed.

IMPORTANT:
Rejected candidates must be omitted completely.
Never return a rejected candidate as an item.
Never write rejection explanations inside title, tool_name, company_name, whats_new, or highlight_reason.
Every returned item must describe an accepted update only.

{selection_instructions}

{user_value_validation}

FINAL QUALITY CHECK:
The final newsletter should make readers feel they discovered useful AI improvements
they can actually benefit from.
Avoid filling slots with weaker stories if stronger user-facing updates are available.
When in doubt, prefer:
- Practical features.
- Better capabilities.
- New workflows.
- Public availability.
Instead of:
- Corporate news.
- Marketing content.
- Generic announcements.
- Brand storytelling.

NEWS LEVEL CLASSIFICATION:
Classify every returned news item as Beginner, Intermediate, or Advanced based on practical use case.
Return solution_provided, main_user_benefit, likely_user, level, topic_group,
audience_fit, should_simplify, and classification_reason for each item.

STEP 4 - ARABIC EDITORIAL REWRITE
For every accepted item, rewrite the card for a polished Arabic newsletter.
This is not translation and not extraction. It is a concise editorial rewrite
based only on the provided candidate.

Follow USER_ARABIC_STYLE_RULES exactly.
If the candidate does not contain enough detail to follow these writing rules,
reject it instead of returning a weak item.

{USER_ARABIC_STYLE_RULES}

OUTPUT JSON SHAPE:
Return valid JSON only. The top-level object must be exactly:
{{
  "latest_updates": [
    {{
      "title": "Arabic display title",
      "tool_name": "Product/tool name",
      "company_name": "Owner/company",
      "official_url": "URL copied exactly from one provided candidate",
      "whats_new": "Arabic 3-4 sentence editorial paragraph based only on the candidate",
      "sector": "one approved sector label",
      "solution_provided": "practical solution or use case",
      "main_user_benefit": "main practical user benefit",
      "likely_user": "likely user type",
      "level": "beginner | intermediate | advanced",
      "topic_group": "short topic group",
      "audience_fit": "general | semi_technical | technical",
      "should_simplify": false,
      "classification_reason": "short reason",
      "is_highlight": false,
      "highlight_reason": ""
    }}
  ],
  "timestamp": "{utc_now().isoformat()}"
}}
""".strip()
