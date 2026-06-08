"""OpenAI model calls and structured editorial selection.

GPT receives only normalized, live candidates from the fetch/filter stages. It
selects the final stories, writes Arabic summaries, and returns structured data
that can be validated against the original source URLs.
"""

from __future__ import annotations

import json
import hashlib
import re
from collections import Counter

from openai import OpenAI
from pydantic import BaseModel, Field

from .config import (
    AI_UPDATES_GPT_COMPACT_LIMIT,
    AI_UPDATES_LOOKBACK_DAYS,
    AI_UPDATES_OUTPUT_LIMIT,
    AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT,
    AI_UPDATES_SINGLE_OUTPUT_LIMIT,
    NEWS_SECTORS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    AI_UPDATES_RUN_REPORT_FILE,
    clean_text,
    recency_cutoff_query_token,
    result_is_recent_enough,
    safe_write_json,
    source_domain,
    normalized_text,
    utc_now,
)
from .fetchers import (
    candidate_owner_key,
    domain_blocked,
    infer_sector,
)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

class AITool(BaseModel):
    """Structured schema GPT must fill for each selected news card."""
    title: str = Field(description="Arabic title, 6 to 8 words, specific to the update")
    tool_name: str = Field(description="Product or tool name")
    company_name: str = Field(description="Canonical product owner")
    official_url: str = Field(description="Source URL from the provided candidate list")
    whats_new: str = Field(description="Arabic 3-4 sentence paragraph")
    sector: str = Field(default="", description="One of the approved 15 sectors")
    is_highlight: bool = Field(default=False, description="True only for the strongest update")
    highlight_reason: str = Field(default="", description="Short reason for the highlight")


class TargetAIReport(BaseModel):
    latest_updates: list[AITool] = Field(default=[])
    timestamp: str


class SupportingCard(BaseModel):
    """Structured schema GPT must fill for course and movie support cards."""
    title: str = Field(description="Final display title from the provided source record")
    text: str = Field(description="Arabic factual summary based only on the provided source record")
    url: str = Field(description="Source URL from the provided candidate list")
    type: str = Field(description="course or movie")
    source: str = Field(default="", description="Source/platform name")
    provider: str = Field(default="", description="Course provider if available")
    platform: str = Field(default="", description="Course platform if available")
    level: str = Field(default="", description="Beginner or Intermediate for courses")
    duration: str | None = Field(default=None, description="Course duration if available")
    certificate: str = Field(default="", description="Course certificate information")
    poster: str = Field(default="", description="Movie poster URL")


class SupportingReport(BaseModel):
    articles: list[SupportingCard] = Field(default=[])


def failure_report(reason: str, diagnostics: dict | None = None) -> dict:
    return {
        "latest_updates": [],
        "timestamp": utc_now().isoformat(),
        "success": False,
        "error": reason,
        "diagnostics": diagnostics or {},
    }


def result_url_key(url: str) -> str:
    return (url or "").strip().rstrip("/")


def normalized_update_title(value: str = "") -> str:
    return " ".join(clean_text(value).lower().split())


SOURCE_FILLER_PHRASES = (
    "كما ذكر المصدر",
    "كما ورد في المصدر",
    "بحسب المصدر",
    "وفقًا للمصدر",
    "وفقا للمصدر",
    "نُشر في المدونة",
    "نشر في المدونة",
    "نشرت المدونة",
    "ضمن تحديثات",
    "كتحديثات",
    "في مدونة",
    "according to the source",
    "as mentioned in the source",
)


def strip_source_filler_sentences(value: str = "") -> str:
    """Remove editorial filler that only references the source/date."""
    text = clean_text(value or "")
    if not text:
        return ""
    for phrase in SOURCE_FILLER_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.!؟])\s+", text)
    kept = []
    for sentence in sentences:
        lowered = sentence.lower()
        source_only = any(
            marker in lowered
            for marker in (
                "المدونة الرسمية",
                "تحديثات مايو",
                "تحديثات يونيو",
                "مدونة",
                "نشرت",
                "مايو",
                "يونيو",
                "الرسمية",
                "بحسب",
                "وفق",
                "المصدر",
                "official blog",
                "according to",
            )
        )
        feature_signal = any(
            marker in lowered
            for marker in (
                "ميزة",
                "تتيح",
                "يتيح",
                "تضيف",
                "يضيف",
                "يدعم",
                "يمكن",
                "إطلاق",
                "new feature",
                "users can",
                "now available",
            )
        )
        if source_only and not feature_signal:
            continue
        clean_sentence = sentence.strip(" ،,")
        if clean_sentence:
            kept.append(clean_sentence)
    cleaned = " ".join(kept).strip()
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def flatten_nested_parentheses(value: str = "") -> str:
    """Collapse nested display parentheses, e.g. (Nano (Banana) 2)."""
    text = clean_text(value or "")
    pattern = re.compile(r"\(([^()]*)\(([^()]+)\)([^()]*)\)")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(lambda match: f"({match.group(1)}{match.group(2)}{match.group(3)})", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def wrap_english_terms(value: str = "") -> str:
    """Ensure English product/model/technical terms appear inside one pair of parentheses."""
    text = flatten_nested_parentheses(value)
    if not text:
        return ""
    parts = re.split(r"(\([^()]*\))", text)
    english_run = re.compile(r"\b[A-Za-z][A-Za-z0-9&+.\-]*(?:\s+[A-Za-z0-9&+.\-]+){0,4}\b")

    def wrap(match: re.Match) -> str:
        phrase = match.group(0).strip()
        if not phrase:
            return phrase
        return f"({phrase})"

    output = []
    for part in parts:
        if not part:
            continue
        if part.startswith("(") and part.endswith(")"):
            output.append(flatten_nested_parentheses(part))
        else:
            output.append(english_run.sub(wrap, part))
    return flatten_nested_parentheses("".join(output))


def normalize_editorial_text(value: str = "") -> str:
    return wrap_english_terms(strip_source_filler_sentences(value))


def selected_story_tokens(item: dict) -> set[str]:
    source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
    text = normalized_update_title(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "tool_name", "company_name", "source_title", "whats_new")
        )
        + " "
        + " ".join(
            str(source_item.get(key) or "")
            for key in ("title", "content", "summary", "query", "tool", "company")
        )
    )
    stop = {
        "ai", "the", "and", "for", "with", "now", "new", "feature", "users", "can",
        "available", "launch", "launches", "adds", "inside", "directly",
        "artificial", "intelligence", "official", "announcement", "update", "updates",
        "product", "tool", "tools", "app", "release", "released", "rollout",
    }
    return {word for word in re.split(r"\s+", text) if len(word) >= 4 and word not in stop}


def selected_same_story(left: dict, right: dict) -> bool:
    left_source = left.get("source_item") if isinstance(left.get("source_item"), dict) else {}
    right_source = right.get("source_item") if isinstance(right.get("source_item"), dict) else {}
    left_story = str(left_source.get("story_key") or "").strip()
    right_story = str(right_source.get("story_key") or "").strip()
    if left_story and right_story and left_story == right_story:
        return True
    left_owner = normalized_text(left.get("owner_key") or left.get("company_name") or left.get("tool_name") or left_source.get("owner_key") or "")
    right_owner = normalized_text(right.get("owner_key") or right.get("company_name") or right.get("tool_name") or right_source.get("owner_key") or "")
    if left_owner and right_owner and left_owner != right_owner:
        return False
    left_tokens = selected_story_tokens(left)
    right_tokens = selected_story_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens)) or 1
    return overlap >= 4 or (overlap >= 3 and (overlap / smaller) >= 0.42) or (overlap / smaller) >= 0.55


def dedupe_selected_updates(items: list[dict], diagnostics: dict) -> list[dict]:
    seen_urls = set()
    seen_titles = set()
    unique = []
    removed = 0
    same_story_removed = 0
    for item in items or []:
        source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
        url_key = result_url_key(item.get("official_url") or source_item.get("url") or "").lower()
        title_key = normalized_update_title(item.get("title") or item.get("source_title") or source_item.get("title") or "")
        if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
            removed += 1
            continue
        if any(selected_same_story(item, existing) for existing in unique):
            same_story_removed += 1
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(item)
    if removed:
        diagnostics["duplicate_model_updates_removed"] = removed
    if same_story_removed:
        diagnostics["same_story_model_updates_removed"] = same_story_removed
    return unique


def compact_model_candidate(item: dict) -> dict:
    """Keep model context small while preserving selection evidence."""
    return {
        "title": clean_text(item.get("title") or "")[:220],
        "content": clean_text(item.get("content") or item.get("summary") or "")[:700],
        "url": item.get("url") or "",
        "source_domain": item.get("source_domain") or source_domain(item.get("url") or ""),
        "published_date": item.get("published_date") or item.get("published_raw") or "",
        "sector": item.get("sector") or "",
        "source_type": item.get("source_type") or "",
        "tool": item.get("tool") or "",
        "company": item.get("company") or "",
        "tool_type": item.get("tool_type") or "",
        "sector_hint": item.get("sector_hint") or "",
        "query_mix": item.get("query_mix") or "",
        "tool_score": int(item.get("tool_score") or 0),
        "tool_query_variant": item.get("tool_query_variant") or "",
    }

def filter_model_items(items: list[dict], diagnostics: dict, source_by_url: dict[str, dict]) -> list[dict]:
    """Validate GPT output against the live candidate URLs it was given."""
    kept = []
    rejected = []
    warnings = []
    for item in items or []:
        url = item.get("official_url") or ""
        domain = source_domain(url)
        if domain_blocked(domain):
            rejected.append({"title": item.get("title") or item.get("tool_name"), "reason": "disallowed_source_domain", "domain": domain})
            continue
        source_item = source_by_url.get(result_url_key(url))
        if not source_item:
            rejected.append({"title": item.get("title") or item.get("tool_name"), "reason": "source_url_not_in_live_results", "domain": domain})
            continue
        title = source_item.get("title") or ""
        content = source_item.get("content") or ""
        published_date = source_item.get("published_date") or source_item.get("published_raw") or ""
        if not result_is_recent_enough(published_date):
            rejected.append({"title": item.get("title") or item.get("tool_name"), "reason": "outside_14_day_window", "domain": domain})
            continue
        item["title"] = normalize_editorial_text(item.get("title") or "")
        item["whats_new"] = normalize_editorial_text(item.get("whats_new") or "")
        item["tool_name"] = flatten_nested_parentheses(clean_text(item.get("tool_name") or ""))
        item["company_name"] = flatten_nested_parentheses(clean_text(item.get("company_name") or ""))
        item["source_item"] = source_item
        item["source_title"] = title
        item["source_domain"] = source_item.get("source_domain") or domain
        item["owner_key"] = candidate_owner_key(
            {
                **source_item,
                "company_name": item.get("company_name") or source_item.get("company_name"),
                "tool_name": item.get("tool_name") or source_item.get("tool_name"),
            },
            url=url,
            title=f"{item.get('title') or ''} {title}",
            content=f"{item.get('whats_new') or ''} {content}",
        )
        item["published_date"] = source_item.get("published_date") or source_item.get("published_raw") or ""
        item["source_query"] = source_item.get("query") or ""
        item["source_bucket"] = source_item.get("bucket") or ""
        if item.get("sector") not in NEWS_SECTORS:
            item["sector"] = source_item.get("sector") or infer_sector(title, content, source_item.get("bucket") or "")
        kept.append(item)
    if rejected:
        diagnostics.setdefault("gpt_output_rejected", []).extend(rejected)
    if warnings:
        diagnostics.setdefault("gpt_output_warnings", []).extend(warnings)
    return kept

def balance_for_diversity(items: list[dict], target_limit: int, diagnostics: dict) -> list[dict]:
    """Preserve GPT order; only enforce hard duplicate and company-repeat guards."""
    items = dedupe_selected_updates(items, diagnostics)
    if not items:
        return []

    selected = []
    company_counts = Counter()
    for item in items:
        source_item = item.get("source_item") if isinstance(item.get("source_item"), dict) else {}
        if item.get("sector") not in NEWS_SECTORS:
            item["sector"] = source_item.get("sector") or infer_sector(
                item.get("title") or "",
                item.get("whats_new") or source_item.get("content") or "",
                item.get("source_bucket") or source_item.get("bucket") or "",
            )
        owner = item.get("owner_key") or candidate_owner_key(item, url=item.get("official_url") or "")
        item["owner_key"] = owner
        if owner and company_counts[owner] >= 2:
            continue
        selected.append(item)
        if owner:
            company_counts[owner] += 1
        if len(selected) >= target_limit:
            break

    if selected:
        highlight_seen = False
        for item in selected:
            if item.get("is_highlight") and not highlight_seen:
                highlight_seen = True
            else:
                item["is_highlight"] = False
            item.setdefault("highlight_reason", "")
        if not highlight_seen:
            selected[0]["is_highlight"] = True
            selected[0]["highlight_reason"] = selected[0].get("highlight_reason") or "اختيار المودل الأعلى أولوية"

    diagnostics["sector_counts_after_balance"] = dict(Counter(item.get("sector") or "unknown" for item in selected))
    diagnostics["visible_sector_counts"] = dict(Counter(item.get("sector") or "unknown" for item in selected[:6]))
    diagnostics["company_counts_after_balance"] = dict(Counter(item.get("owner_key") or "unknown" for item in selected))
    diagnostics["visible_company_counts"] = dict(Counter(item.get("owner_key") or "unknown" for item in selected[:6]))
    diagnostics["highlight_title"] = next((item.get("title") for item in selected if item.get("is_highlight")), selected[0].get("title") if selected else "")
    return selected


USER_ARABIC_STYLE_RULES = """
## STEP 4 - ARABIC SUMMARY

Write the summary as a natural Arabic paragraph of 3 to 4 sentences.

Strict sentence order:
Sentence 1: Name the product and state exactly what the new feature or update is.
Sentence 2: Explain where the user finds the feature or how to activate it.
Sentence 3: Explain the concrete new capability or feature detail mentioned by the source.
Sentence 4 only if needed: Mention a concrete availability condition or limitation.

Tone and style rules:
- The title must be polished Modern Standard Arabic, 6 to 8 words.
- The title must reflect the exact meaning of the specific update: product + concrete feature/action, not a generic AI headline.
- The title must not exaggerate or market the update; it should say what changed precisely.
- Put every English product name, company name, acronym, model name, or technical term inside one clean pair of parentheses.
- Never create nested parentheses. Write (Nano Banana 2), not (Nano (Banana) 2).
- Do not write foreign company names in Arabic transliteration when the source uses English. Use (Google), (Claude), (Runway), etc.
- Never use generic titles such as "تحديث جديد للذكاء الاصطناعي" or "ميزة ذكاء اصطناعي جديدة".
- Write as a neutral editorial paragraph, not a list.
- Base the paragraph only on features, changes, access path, and limits explicitly mentioned in the source.
- The summary itself must be short enough to display fully in four newsletter lines without UI clipping; prefer 45 to 60 Arabic words unless a required availability note is very short.
- Do not force a closing sentence that names a user category such as للمستخدمين، للمصممين، للمبدعين، للفرق، or للمهنيين.
- Do not use source filler anywhere, including "كما ذكر المصدر", "وفقًا للمصدر", "بحسب المصدر", "نُشر في المدونة الرسمية", "ضمن تحديثات مايو 2026", or any sentence whose only job is to name the source/date.
- Keep source/date context in official_url and published_date only; the Arabic summary must focus on the actual feature, access path, and user-facing change.
- Do not repeat the title wording inside the description.
- Do not repeat the product name more than once.
- No promotional words: ثوري، رائد، قوي، مذهل، يغير قواعد اللعبة.
- Avoid vague endings like "يساعد المستخدمين" or "يوفر تجربة أفضل" unless the source names a concrete feature immediately.

## STEP 5 - TERMINOLOGY SIMPLIFICATION

Before finalizing, replace technical terms with plain Arabic:
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


def model_prompt(target_limit: int, *, single: bool = False) -> str:
    """Build the unified prompt used for full generation and single refill."""
    _ = single  # Runtime behavior is controlled by target_limit and fetch limits; prompt rules stay unified.
    return f"""
Selection controls:
- This is one unified editorial prompt for both full generation and single replacement. Use the same quality, rejection, diversity, and writing rules in both modes.
- target_limit controls the output size: full generation asks for the newsletter pool, while single replacement asks for one fast replacement. Do not loosen quality for single replacement.
- Use only the provided Exa and SearXNG candidates. Do not invent outside news.
- The acceptance window is the last {AI_UPDATES_LOOKBACK_DAYS} days, starting {recency_cutoff_query_token()}.
- Date is only a hard acceptance window. Inside the window, prefer the strongest update over the newest weak item.
- Choose updates for well-known or clearly usable AI tools in the current market. Do not require a hard-coded company list and do not depend on queries that mention company names.
- "Known" means: clear product owner, public product surface, broad availability, credible source coverage, and a specific user action.
- Prefer user-facing AI products: assistants, productivity tools, creative tools, design/video/audio tools, learning tools, browser/mobile assistants, shopping/travel helpers, culture/knowledge tools, and daily-work tools.
- Items tagged source_type=trending_tool come from the monthly tools layer. Prefer them when they describe a real AI feature, launch, release note, or user-facing capability.
- For general tools such as assistants and search/workspace products, infer the best sector from the article itself; do not reject them just because the tool is multi-purpose.
- Do not over-concentrate on design, images, or visual tools. They are welcome when strong, but must compete with work, daily life, learning, audio, culture, and practical assistants.
- Culture and creative coverage is important. When valid candidates exist, include updates connected to museums, films, heritage, fashion, libraries, music, visual arts, literature, cooking, architecture, theater, or creative workflows.
- Do not let work productivity, general assistants, design/image generation, or writing tools dominate the first 6 cards. The first 6 should feel like a balanced cultural/creative/daily-life newsletter, not a generic tech digest.
- Never select more than two updates from the same company or product owner.
- Reject local or narrow stories, even if they mention AI: one city, one museum, one school, one hospital, one customer, one region, one state/province, Australia-only/local-government pilots, municipal deployments, or local apps with no broad availability.
- Reject unknown local apps, small regional services, one-client pilots, obscure startups, demo-only enterprise services, SEO/listicles, PR/newswire, funding/stock/legal stories, finance tools, pure CRM/customer-support/sales/admin tools, GitHub repos, research papers, SDK/API-only updates, and developer-only infrastructure unless there is a clear public user-facing product feature.

أنت محرر نشرة ثقافية ذكية عن تحديثات أدوات الذكاء الاصطناعي.
اختر من نتائج Exa وSearXNG فقط، ولا تختر أي خبر من خارج البيانات.
التاريخ الحالي: {utc_now().date().isoformat()}.

اختر فقط:
- تحديث منتج AI واضح: إطلاق، ميزة جديدة، rollout، changelog، release notes، أو now available
- أداة أو منتج يستطيع المستخدم العادي فهم أين يستخدمه وماذا يفعل به.
- تحديث يلمس الحياة اليومية أو العمل الإبداعي أو الإنتاجية أو التعليم أو الثقافة أو البحث المعرفي.
- تحديثات لأدوات ذكاء اصطناعي معروفة في السوق أو منتجات واضحة الاستخدام العام، بدون الاعتماد على ذكر اسم الشركة داخل الكويري.

ارفض:
- الأخبار المحلية أو الضيقة: مدينة واحدة، متحف واحد، مدرسة واحدة، مستشفى واحد، عميل واحد، جهة حكومية محلية، ولاية/مقاطعة واحدة، أو تجربة داخل منطقة محددة مثل خبر خاص بمنطقه معينه فقط.
- أي خبر لا يثبت أن الميزة متاحة أو قابلة للاستخدام على نطاق واسع.
- أخبار AI العامة والآراء والتوقعات.
- مقالات SEO مثل best/top AI tools أو alternatives.
- PR/newswire والتمويل والأسهم والقضايا القانونية.
- GitHub repos أو نماذج مفتوحة المصدر موجهة للمطورين فقط.
- SDK/API/GPU إذا لم تكن ميزة واضحة للمستخدم العادي.
- إذا كان  خبر مرتبط بمؤتمر 
- إذا كان خبر تقني غير متعلق بالذكاء الاصطناعي 
التنوع:
- القطاعات المعتمدة: {"، ".join(NEWS_SECTORS)}.
- أول 6 أخبار يجب أن تكون من قطاعات مختلفة قدر الإمكان.
- إذا توفرت مرشحات صالحة، يجب أن يظهر في أول 6 خبران على الأقل من المجالات الثقافية أو الإبداعية مثل الأفلام، الموسيقى، التراث، المكتبات، الفنون البصرية، الأدب، الأزياء، العمارة، الطهي، أو المتاحف.
- لا تجعل أغلب أول 6 من الإنتاجية العامة أو المساعدات العامة أو الصور/التصميم فقط.
- الاحتياط يغطي القطاعات الناقصة ولا يكرر نفس المسار إذا توفرت بدائل قوية.
- ضع is_highlight=true على خبر واحد فقط: الأقوى تأثيرًا خلال آخر أسبوعين.
- إذا توفرت نتائج كافية، أرجع {target_limit} عنصرًا ولا تكتف بعدد أقل.

اتبع قواعد الأسلوب العربي والتبسيط الموجودة في USER_ARABIC_STYLE_RULES أدناه.
اكتب الوصف في 3 إلى 4 جمل قصيرة فقط، ويجب أن يظهر كاملًا داخل 4 أسطر في كرت النشرة بدون قص من الواجهة. اجعل الوصف غالبًا بين 45 و60 كلمة عربية، واذكر الميزات التي وردت في المصدر دون حشو أو تصنيف إجباري لفئة المستخدمين أو جملة نشر/مصدر في نهاية الوصف.
ممنوع استخدام عبارات مثل "كما ذكر المصدر"، "بحسب المصدر"، "وفقًا للمصدر"، "نشرت المدونة"، أو أي صياغة لا تضيف معلومة عن الميزة نفسها.
أي اسم أو مصطلح إنجليزي يجب أن يكون بين قوسين مرة واحدة فقط، بدون أقواس داخل أقواس، مثل (Nano Banana 2).
العنوان يجب أن يعكس معنى الخبر بدقة: اسم المنتج أو الأداة + الميزة أو التغيير الفعلي، بدون تعميم أو مبالغة.

املأ company_name باسم مالك المنتج الحقيقي، وليس اسم موقع الأخبار.
املأ sector باسم واحد من القطاعات المعتمدة.



{USER_ARABIC_STYLE_RULES}

""".strip()

def select_news_updates(candidates: list[dict], diagnostics: dict, *, single: bool = False) -> dict:
    """Ask GPT to select final updates from the shortlist."""
    target_limit = max(1, AI_UPDATES_SINGLE_OUTPUT_LIMIT if single else AI_UPDATES_OUTPUT_LIMIT)
    configured_limit = max(1, AI_UPDATES_SINGLE_GPT_COMPACT_LIMIT if single else AI_UPDATES_GPT_COMPACT_LIMIT)
    compact_limit = min(max(configured_limit, target_limit * 5), 24 if single else 72)
    if not candidates:
        return failure_report(diagnostics.get("error") or "no_live_results", diagnostics)
    if client is None:
        return failure_report("missing_openai_api_key", diagnostics)

    def ask_model(compact_source: list[dict], ask_limit: int, stage: str) -> list[dict]:
        compact = [compact_model_candidate(item) for item in compact_source]
        source_by_url = {result_url_key(item.get("url") or ""): item for item in compact_source if item.get("url")}
        diagnostics[f"gpt_{stage}_payload_candidates"] = len(compact)
        if stage == "primary":
            diagnostics["gpt_compact_limit_used"] = len(compact_source)
            diagnostics["gpt_payload_candidates"] = len(compact)
        print(f"[AI Updates] Sending {len(compact)} live results to GPT ({stage})", flush=True)
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": model_prompt(ask_limit, single=single)},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))},
            ],
            response_format=TargetAIReport,
        )
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        parsed_data = parsed.model_dump() if parsed is not None else json.loads(message.content or "{}")
        return filter_model_items(list(parsed_data.get("latest_updates") or [])[:ask_limit], diagnostics, source_by_url)

    compact_source = candidates[:compact_limit]
    try:
        data = {"latest_updates": [], "timestamp": utc_now().isoformat()}
        primary_ask_limit = target_limit if single else min(target_limit + 4, max(target_limit, len(compact_source)))
        selected = ask_model(compact_source, primary_ask_limit, "primary")
        data["latest_updates"] = balance_for_diversity(selected, target_limit, diagnostics)
        if len(data["latest_updates"]) < target_limit:
            for attempt in range(1, 3):
                missing = target_limit - len(data["latest_updates"])
                if missing <= 0:
                    break
                used_urls = {
                    result_url_key(item.get("official_url") or "").lower()
                    for item in data["latest_updates"]
                    if item.get("official_url")
                }
                remaining_source = [
                    item for item in candidates[compact_limit:]
                    if result_url_key(item.get("url") or "").lower() not in used_urls
                ]
                if not remaining_source:
                    remaining_source = [
                        item for item in compact_source
                        if result_url_key(item.get("url") or "").lower() not in used_urls
                    ]
                retry_cap = 24 if single else 40
                retry_floor = 10 if single else 16
                retry_source = remaining_source[:min(max(retry_floor, missing * 6), retry_cap)]
                if not retry_source:
                    break
                diagnostics["gpt_topup_attempted"] = True
                diagnostics[f"gpt_topup_{attempt}_missing_before"] = missing
                try:
                    topup_ask_limit = min(len(retry_source), max(missing + 4, missing * 3))
                    topup_selected = ask_model(retry_source, topup_ask_limit, f"topup_{attempt}")
                    diagnostics[f"gpt_topup_{attempt}_raw_selected"] = len(topup_selected)
                    selected = selected + topup_selected
                    data["latest_updates"] = balance_for_diversity(
                        selected,
                        target_limit,
                        diagnostics,
                    )
                except Exception as topup_exc:
                    diagnostics[f"gpt_topup_{attempt}_error"] = str(topup_exc)
                    break
        data["timestamp"] = utc_now().isoformat()
        data["success"] = bool(data["latest_updates"])
        data["diagnostics"] = diagnostics
        if not data["latest_updates"]:
            data["error"] = "gpt_selected_no_updates"
        print(f"[AI Updates] GPT selected {len(data['latest_updates'])} update(s)", flush=True)
        return data
    except Exception as exc:
        print(f"[AI Updates] GPT failed: {exc}", flush=True)
        return failure_report("gpt_failed", {**diagnostics, "exception": str(exc)})


def compact_supporting_candidate(item: dict, content_type: str, index: int) -> dict:
    """Keep course/movie prompt input small and source-bound."""
    return {
        "article_index": index,
        "visible_pair_priority": item.get("_visible_pair_priority") or "",
        "title": clean_text(item.get("title") or "")[:220],
        "overview": clean_text(item.get("content") or item.get("summary") or item.get("text") or item.get("overview") or "")[:900],
        "url": item.get("url") or item.get("source_url") or "",
        "source": item.get("source") or item.get("platform") or item.get("provider") or source_domain(item.get("url") or ""),
        "platform": item.get("platform") or "",
        "provider": item.get("provider") or "",
        "level": item.get("level") or "",
        "duration": item.get("duration") or "",
        "certificate": item.get("certificate") or "",
        "date": item.get("published_date") or item.get("published") or item.get("date") or "",
        "source_query": item.get("source_query") or "",
        "poster": item.get("poster") or item.get("image") or "",
        "type": content_type,
    }


def supporting_prompt(content_type: str, target_count: int, *, visible_count: int | None = None) -> str:
    """Build the dedicated prompt for course or movie support cards."""
    visible_count = max(1, int(visible_count or target_count or 1))
    if content_type == "movie":
        return f"""
You are a movie curator focused on AI-related films.

Use ONLY the provided records. Select up to {target_count} movies.

Strict rules:
- type must be "movie".
- Keep the movie title in English exactly as provided.
- Select a movie only if the provided overview clearly shows an artificial intelligence theme.
- Do not rely on outside knowledge about the film.
- Reject generic science fiction, robots, future technology, or surveillance stories unless the overview clearly connects them to AI or an AI system.
- Use the provided overview as the source for the Arabic summary.
- Do not invent plot details.
- The summary must be 2 to 3 short formal Arabic sentences.
- Do not mention rating, popularity, or duration inside the summary.
- Return the movie poster URL in poster only. Do not create image or logo fields.
- Return only records whose url appears in the provided candidate list.
""".strip()

    if content_type == "course":
        return f"""
You are an AI course curator for a newsletter aimed at general, non-technical employees.

Use ONLY the provided records. Select up to {target_count} real AI courses.

Select only courses that:
- Come from the trusted course domains already provided in the records.
- Have a direct official course landing page URL.
- Are genuinely about AI, generative AI, prompt engineering, AI productivity, AI tools, responsible AI, or practical AI basics.
- Are suitable for Beginner or Intermediate learners.
- Are useful for general employees, creators, designers, writers, educators, or knowledge workers.
- Include enough overview, objectives, skills, prerequisites, or learning outcomes to support the summary.

Reject:
- Advanced, expert, research-heavy, engineering-heavy, MLOps, model deployment, cloud engineering, or math-heavy courses when stated clearly.
- Ended, expired, archived, closed-enrollment, waitlist-only, or past cohort courses.
- Blogs, articles, tutorials, docs, events, listicles, rankings, search pages, category pages, reviews, and third-party summaries.
- Records that do not explain what the learner will actually learn.

Output rules:
- type must be "course".
- level must be exactly "Beginner" or "Intermediate"; never output "Advanced".
- Prefer variety: do not choose all courses from the same platform when alternatives are valid.
- The first {visible_count} selected courses are the visible newsletter cards. Optimize those first.
- Records marked visible_pair_priority=1 and visible_pair_priority=2 were preselected for visible-card level, platform, and topic diversity. Use them as the first visible cards unless one violates the rejection rules.
- If the first {visible_count} includes two courses and both levels exist in the provided records, make them exactly one Beginner and one Intermediate.
- If the first {visible_count} includes two courses and multiple platforms exist, use two different platforms.
- Never make the first two visible courses from the same platform when any valid course from another platform is available in the provided records.
- If the first {visible_count} includes two courses and multiple practical topics exist, use two different topics such as prompting, productivity, creative AI, responsible AI, generative AI basics, or AI tools for work.
- For target_count 2 or more, return extra valid alternatives when available so the final balancer can preserve level, platform, and topic diversity.
- Do not choose two visible courses from the same provider/company unless the provided records have no valid alternative.
- Keep official English course names in English.
- Write the Arabic description as one natural paragraph, around one and a half to two lines.
- Vary the wording by course; do not use a fixed repeated pattern.
- Do not mention publication dates or update dates in the description.
- Avoid promotional words and marketing claims.
- Return only records whose url appears in the provided candidate list.
""".strip()

    return f"""
Use ONLY the provided records. Select up to {target_count} valid items.
Write concise factual Arabic summaries and do not invent missing information.
""".strip()


def merge_supporting_cards(
    articles: list[dict],
    source_pool: list[dict],
    content_type: str,
    target_count: int,
) -> list[dict]:
    """Attach GPT writing to the original source records and drop anything not source-bound."""
    source_by_url = {
        result_url_key(item.get("url") or item.get("source_url") or ""): item
        for item in source_pool or []
        if item.get("url") or item.get("source_url")
    }
    selected = []
    seen_urls = set()
    for article in articles or []:
        url_key = result_url_key(article.get("url") or "")
        source_item = source_by_url.get(url_key)
        if not source_item or url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        merged = dict(source_item)
        title = clean_text(article.get("title") or source_item.get("title") or "")
        text = clean_text(article.get("text") or source_item.get("text") or source_item.get("summary") or "")
        if not title or not text:
            continue
        merged["title"] = title
        merged["text"] = text
        merged["summary"] = text
        merged["url"] = source_item.get("url") or article.get("url") or ""
        merged["source_url"] = merged["url"]
        merged["type"] = content_type
        merged["source"] = clean_text(article.get("source") or source_item.get("source") or source_domain(merged["url"]))
        if content_type == "course":
            level = clean_text(article.get("level") or source_item.get("level") or "")
            if level not in {"Beginner", "Intermediate"}:
                level = "Beginner"
            merged["level"] = level
            merged["platform"] = clean_text(article.get("platform") or source_item.get("platform") or merged["source"])
            merged["provider"] = clean_text(article.get("provider") or source_item.get("provider") or merged["platform"])
            merged["certificate"] = clean_text(article.get("certificate") or source_item.get("certificate") or "not specified")
            merged["duration"] = article.get("duration") or source_item.get("duration")
        if content_type == "movie":
            poster = article.get("poster") or source_item.get("poster") or source_item.get("image") or ""
            if not poster:
                continue
            merged["poster"] = poster
        if not merged.get("id"):
            id_seed = f"{title}|{merged.get('url') or ''}"
            merged["id"] = f"{content_type}-{hashlib.sha1(id_seed.encode('utf-8', errors='ignore')).hexdigest()[:16]}"
        selected.append(merged)
        if len(selected) >= target_count:
            break
    return selected


def course_topic_key(item: dict) -> str:
    """Classify course topics just enough to avoid two identical visible cards."""
    text = normalized_text(
        " ".join(str(item.get(key) or "") for key in ("title", "text", "summary", "content"))
    )
    topic_terms = [
        ("prompting", ("prompt", "prompting")),
        ("generative_ai", ("generative", "chatgpt", "llm", "model")),
        ("productivity", ("productivity", "work", "office", "copilot")),
        ("creative", ("creative", "design", "image", "video", "canva", "adobe")),
        ("data", ("data", "analytics", "analysis")),
        ("responsible_ai", ("responsible", "ethics", "safety")),
        ("basics", ("beginner", "basics", "fundamentals", "introduction", "intro")),
    ]
    for topic, terms in topic_terms:
        if any(term in text for term in terms):
            return topic
    words = [word for word in text.split() if len(word) > 3]
    return words[0] if words else "general"


def course_platform_key(item: dict) -> str:
    return normalized_text(item.get("platform") or item.get("provider") or item.get("source") or source_domain(item.get("url") or ""))


def course_item_key(item: dict) -> str:
    return normalized_text(item.get("url") or item.get("source_url") or item.get("title") or str(id(item)))


def prepare_course_prompt_pool(items: list[dict], visible_count: int) -> list[dict]:
    """Put a diverse visible course pair first so GPT sees the intended choice."""
    items = [dict(item) for item in items or []]
    if visible_count < 2 or len(items) < 2:
        return items

    indexed = list(enumerate(items))
    beginners = [(idx, item) for idx, item in indexed if item.get("level") == "Beginner"]
    intermediates = [(idx, item) for idx, item in indexed if item.get("level") == "Intermediate"]

    def pair_rank(first: tuple[int, dict], second: tuple[int, dict]) -> tuple[int, int, int, int]:
        first_idx, first_item = first
        second_idx, second_item = second
        platform_diff = int(bool(course_platform_key(first_item)) and course_platform_key(first_item) != course_platform_key(second_item))
        topic_diff = int(bool(course_topic_key(first_item)) and course_topic_key(first_item) != course_topic_key(second_item))
        original_order = -(first_idx + second_idx)
        return (platform_diff, topic_diff, original_order)

    chosen: list[tuple[int, dict]] = []
    if beginners and intermediates:
        chosen = list(max(
            ((beginner, intermediate) for beginner in beginners for intermediate in intermediates),
            key=lambda pair: pair_rank(pair[0], pair[1]),
        ))

    if not chosen:
        best_pair = None
        best_rank = None
        for first_pos, first_item in indexed:
            for second_pos, second_item in indexed:
                if second_pos == first_pos:
                    continue
                rank = pair_rank((first_pos, first_item), (second_pos, second_item))
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_pair = [(first_pos, first_item), (second_pos, second_item)]
        chosen = best_pair or []

    if not chosen:
        return items

    chosen_ids = {id(item) for _, item in chosen}
    ordered = []
    for priority, (_, item) in enumerate(chosen[:2], start=1):
        copy_item = dict(item)
        copy_item["_visible_pair_priority"] = priority
        ordered.append(copy_item)

    ordered.extend(item for item in items if id(item) not in chosen_ids)
    return ordered


def balance_course_levels(items: list[dict], target_count: int) -> list[dict]:
    """Prefer Beginner + Intermediate, then different platforms and topics."""
    items = list(items or [])
    if target_count < 2:
        return items[:target_count]

    output = []
    seen_keys = set()
    used_platforms = set()
    used_topics = set()

    def add(item: dict | None) -> None:
        key = course_item_key(item or {})
        if item is None or (key and key in seen_keys):
            return
        output.append(item)
        if key:
            seen_keys.add(key)
        platform = course_platform_key(item)
        topic = course_topic_key(item)
        if platform:
            used_platforms.add(platform)
        if topic:
            used_topics.add(topic)

    beginner = next((item for item in items if item.get("level") == "Beginner"), None)
    add(beginner)

    def different_from_visible(item: dict) -> bool:
        platform = course_platform_key(item)
        topic = course_topic_key(item)
        return bool(platform and platform not in used_platforms and topic and topic not in used_topics)

    def different_platform(item: dict) -> bool:
        platform = course_platform_key(item)
        return bool(platform and platform not in used_platforms)

    intermediate = next(
        (item for item in items if item.get("level") == "Intermediate" and course_item_key(item) not in seen_keys and different_from_visible(item)),
        None,
    )
    if intermediate is None:
        intermediate = next(
            (item for item in items if item.get("level") == "Intermediate" and course_item_key(item) not in seen_keys and different_platform(item)),
            None,
        )
    if intermediate is None:
        intermediate = next((item for item in items if item.get("level") == "Intermediate" and course_item_key(item) not in seen_keys), None)
    add(intermediate)

    for item in items:
        if len(output) >= target_count:
            break
        if course_item_key(item) in seen_keys:
            continue
        if different_from_visible(item):
            add(item)

    for item in items:
        if len(output) >= target_count:
            break
        if course_item_key(item) in seen_keys:
            continue
        if different_platform(item):
            add(item)

    for item in items:
        if len(output) >= target_count:
            break
        add(item)

    if output:
        visible = output[:min(2, target_count)]
        diagnostics = {
            "levels": [item.get("level") for item in visible],
            "platforms": [course_platform_key(item) for item in visible],
            "topics": [course_topic_key(item) for item in visible],
        }
        print(f"[AI Updates] course visible diversity {diagnostics}", flush=True)
    return output[:target_count]


def select_supporting_content_cards(
    candidates: list[dict],
    content_type: str,
    target_count: int,
    *,
    visible_count: int | None = None,
) -> list[dict]:
    """Select and rewrite course/movie cards in the modular path only."""
    target_count = max(1, int(target_count or 1))
    visible_count = max(1, min(target_count, int(visible_count or target_count)))
    pool = [item for item in candidates or [] if isinstance(item, dict)]
    if not pool or client is None:
        return []
    selection_limit = target_count
    if content_type == "course" and target_count >= 2:
        selection_limit = min(len(pool), max(target_count + 8, target_count * 4))
        pool = prepare_course_prompt_pool(pool, visible_count)
    compact = [compact_supporting_candidate(item, content_type, index) for index, item in enumerate(pool, start=1)]
    print(
        f"[AI Updates] GPT supporting {content_type} selection started: "
        f"pool={len(compact)} target={target_count} selection_limit={selection_limit}",
        flush=True,
    )
    try:
        completion = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": supporting_prompt(content_type, selection_limit, visible_count=visible_count)},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))},
            ],
            response_format=SupportingReport,
        )
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        parsed_data = parsed.model_dump() if parsed is not None else json.loads(message.content or "{}")
        merged = merge_supporting_cards(
            list(parsed_data.get("articles") or [])[:selection_limit],
            pool,
            content_type,
            selection_limit,
        )
        if content_type == "course":
            merged = balance_course_levels(merged, target_count)
        else:
            merged = merged[:target_count]
        print(f"[AI Updates] GPT supporting {content_type} selected {len(merged)}", flush=True)
        return merged
    except Exception as exc:
        print(f"[AI Updates] GPT supporting {content_type} failed: {exc}", flush=True)
        return []


def save_model_report(report: dict) -> bool:
    try:
        report["timestamp"] = utc_now().isoformat()
        safe_write_json(AI_UPDATES_RUN_REPORT_FILE, report)
        print(f"[AI Updates] Saved run report: {AI_UPDATES_RUN_REPORT_FILE}", flush=True)
        return True
    except Exception as exc:
        print(f"[AI Updates] Save failed: {exc}", flush=True)
        return False
