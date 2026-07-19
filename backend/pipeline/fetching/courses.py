# This file is part of the AI newsletter system.
"""Course candidate fetching and course-platform discovery."""

from __future__ import annotations

from backend.pipeline.fetching.news_discovery import *  # Generic low-level fetch/text helpers (not news logic).
from backend.config.settings import BACKEND_DIR

COURSE_BAD_URL_TERMS = (
    "/blog/", "/blogs/", "/news/", "/article/", "/articles/", "/review/", "/reviews/",
    "/best-", "/top-", "/tag/", "/category/", "/search", "?q=", "/press", "/events/",
    "/rankings/", "/lists/", "/list/", "/collections/", "/topic/", "/topics/",
    "/datasets/", "/commit/", "/commits/", "/community/", "/forum/", "/forums/",
    "/discussion/", "/discussions/", "/support/", "/help/", "/docs/", "/doc/",
    "/resource/", "/resources/", "/survey/", "/surveys/", "/research/", "/report/",
    "/reports/", "/whitepaper/", "/whitepapers/", "/webinar/", "/webinars/",
    "/podcast/", "/case-study/", "/case-studies/", "/customer-stories/",
    "/customers/", "/partners/", "/partner/", "/press-release/", "/about/",
    "/company/", "/careers/", "/jobs/", "/login", "/signin", "/signup",
)

COURSE_PAGE_TEXT_TERMS = (
    "course",
    "courses",
    "class",
    "classes",
    "learn",
    "learning",
    "training",
    "certificate",
    "certification",
    "short course",
    "specialization",
    "professional certificate",
    "nanodegree",
    "microcredential",
    "academy",
)

OPEN_WEB_COURSE_QUERIES = (
    '("AI for employees" OR "AI productivity" OR "generative AI for business") ("course" OR "training" OR "certificate")',
    '("الذكاء الاصطناعي" OR "الذكاء الاصطناعي التوليدي") ("الموظفين" OR "المهنيين" OR "بيئة العمل" OR "تطوير المهارات")',
    '("prompt engineering" OR "ChatGPT") ("employees" OR "professionals" OR "workplace" OR "productivity") ("course" OR "training")',
    '("AI upskilling" OR "AI workforce training" OR "professional AI training") ("course" OR "certificate")',
)

COURSE_RAW_PLATFORM_CAP = 3
COURSE_MAJOR_PLATFORM_CAP = env_int("AI_UPDATES_COURSE_MAJOR_PLATFORM_CAP", "1")
COURSE_MAJOR_PLATFORM_DOMAINS = ("coursera.org", "udemy.com", "edx.org", "linkedin.com")
COURSE_MAJOR_PLATFORM_NAMES = {"Coursera", "Udemy", "edX", "LinkedIn Learning"}
COURSE_DIVERSITY_TARGET_DOMAINS = (
    "kaggle.com",
    "datacamp.com",
    "cognitiveclass.ai",
    "futurelearn.com",
    "deeplearning.ai",
    "udacity.com",
    "pluralsight.com",
    "cloudskillsboost.google",
    "classcentral.com",
    "freecodecamp.org",
    "codecademy.com",
    "microsoft.com",
    "trailhead.salesforce.com",
    "learn.databricks.com",
    "university.mongodb.com",
    "ocw.mit.edu",
    "online.stanford.edu",
    "saudidigitalacademy.sa",
)

DISCOVERED_PLATFORMS_FILE = BACKEND_DIR / "storage" / "discovered_platforms.json"

COURSE_DIRECT_PATHS = {
    "coursera.org": ("/learn/", "/specializations/", "/professional-certificates/", "/projects/"),
    "udemy.com": ("/course/",),
    "edx.org": ("/learn/", "/course/", "/certificates/professional-certificate/", "/certificates/xseries/", "/programs/"),
    "linkedin.com": ("/learning/",),
    "skillshare.com": ("/classes/", "/en/classes/"),
    "masterclass.com": ("/classes/", "/sessions/"),
    "domestika.org": ("/courses/",),
    "pluralsight.com": ("/courses/", "/paths/"),
    "futurelearn.com": ("/courses/", "/microcredentials/"),
    "udacity.com": ("/course/", "/nanodegree/"),
    "deeplearning.ai": ("/courses/", "/short-courses/"),
    "fast.ai": ("/courses/", "/course"),
    "huggingface.co": ("/learn/",),
    "learnprompting.org": ("/docs/",),
    "promptingguide.ai": ("/docs/",),
    "anthropic.com": ("/learn/", "/courses/"),
    "openai.com": ("/academy/", "/learn/", "/chatgpt/", "/research/"),
    "microsoft.com": ("/learn/", "/training/"),
    "google.com": ("/learn/",),
    "nvidia.com": ("/training/", "/courses/", "/dli/"),
    "adobe.com": ("/learn/", "/creativecloud/learn/"),
    "canva.com": ("/learn/", "/designschool/"),
    "figma.com": ("/resources/", "/academy/"),
    "superhi.com": ("/courses/",),
    "awwwards.com": ("/academy/", "/courses/"),
    "edraak.org": ("/course/", "/courses/", "/programs/"),
    "rwaq.org": ("/courses/", "/course/"),
    "doroob.com.sa": ("/individuals/", "/programs/", "/courses/"),
    "ncle.gov.sa": ("/courses/", "/training/", "/programs/"),
    "khamsat.com": ("/learning/",),
"kaggle.com": ("/learn/",),
"freecodecamp.org": ("/learn/",),
"cognitiveclass.ai": ("/courses/", "/learn/"),
"elementsofai.com": ("/en/", "/"),
"datacamp.com": ("/courses/", "/learn/"),
"codecademy.com": ("/learn/", "/courses/"),
"wandb.ai": ("/courses/",),
"grow.google": ("/certificates/", "/programs/"),
"mygreatlearning.com": ("/academy/", "/courses/"),
"scrimba.com": ("/courses/", "/learn/"),
"aws.amazon.com": ("/training/", "/learn/"),
"developers.google.com": ("/machine-learning/", "/learn/"),
"kaggle.com": ("/learn/",),
"freecodecamp.org": ("/learn/",),
"cognitiveclass.ai": ("/courses/", "/learn/"),
"elementsofai.com": ("/en/", "/"),
"datacamp.com": ("/courses/", "/learn/"),
"codecademy.com": ("/learn/", "/courses/"),
"wandb.ai": ("/courses/",),
"grow.google": ("/certificates/", "/programs/"),
"mygreatlearning.com": ("/academy/", "/courses/"),
"scrimba.com": ("/courses/", "/learn/"),
"aws.amazon.com": ("/training/", "/learn/"),
"developers.google.com": ("/machine-learning/", "/learn/"),
"cloudskillsboost.google": ("/course_templates/", "/paths/", "/quests/"),
"trailhead.salesforce.com": ("/content/learn/", "/trails/", "/modules/"),
"learn.databricks.com": ("/courses/", "/learning-paths/"),
"education.github.com": ("/courses/",),
"university.mongodb.com": ("/courses/",),
"talentsprint.com": ("/programs/",),
"intellipaat.com": ("/course/", "/blog/tutorial/"),
"simplilearn.com": ("/learn/", "/free-online-courses/"),
"coursesity.com": ("/course/",),
"classcentral.com": ("/course/",),
"open.edu": ("/courses/",),
"ocw.mit.edu": ("/courses/",),
"online.stanford.edu": ("/courses/",),
"extension.harvard.edu": ("/course/",),
"mooc.org": ("/courses/",),
"iversity.org": ("/courses/",),
"openclassrooms.com": ("/en/courses/",),
"minnaert.ai": ("/courses/",),
"aiforeveryone.org": ("/",),
"digitaldefynd.com": ("/learn/free-ai-courses/",),
"upgrad.com": ("/free-courses/",),
"swayam.gov.in": ("/courses/",),
"spoken-tutorial.org": ("/tutorial/",),
"nptel.ac.in": ("/courses/",),
"iabac.org": ("/courses/",),
"digiskills.pk": ("/course/",),
"saudidigitalacademy.sa": ("/courses/", "/programs/"),
"thiqah.sa": ("/training/",),
"sdaia.gov.sa": ("/ar/", "/en/"),
"mcit.gov.sa": ("/ar/programs/",),
}

COURSE_PLATFORM_NAMES = {
    "coursera.org": "Coursera",
    "udemy.com": "Udemy",
    "edx.org": "edX",
    "linkedin.com": "LinkedIn Learning",
    "skillshare.com": "Skillshare",
    "masterclass.com": "MasterClass",
    "domestika.org": "Domestika",
    "pluralsight.com": "Pluralsight",
    "futurelearn.com": "FutureLearn",
    "udacity.com": "Udacity",
    "deeplearning.ai": "DeepLearning.AI",
    "fast.ai": "fast.ai",
    "huggingface.co": "Hugging Face",
    "learnprompting.org": "Learn Prompting",
    "promptingguide.ai": "Prompting Guide",
    "anthropic.com": "Anthropic Learn",
    "openai.com": "OpenAI",
    "microsoft.com": "Microsoft Learn",
    "google.com": "Google Learn",
    "nvidia.com": "NVIDIA Deep Learning Institute",
    "adobe.com": "Adobe Learn",
    "canva.com": "Canva Learn",
    "figma.com": "Figma Resources",
    "superhi.com": "SuperHi",
    "awwwards.com": "Awwwards Academy",
    "edraak.org": "Edraak",
    "rwaq.org": "Rwaq",
    "doroob.com.sa": "Doroob",
    "ncle.gov.sa": "National Center for e-Learning",
    "khamsat.com": "Khamsat Learning",
    "kaggle.com": "Kaggle Learn",
    "freecodecamp.org": "freeCodeCamp",
    "cognitiveclass.ai": "IBM Cognitive Class",
    "elementsofai.com": "Elements of AI",
    "datacamp.com": "DataCamp",
    "codecademy.com": "Codecademy",
    "wandb.ai": "Weights & Biases Courses",
    "grow.google": "Google Career Certificates",
    "mygreatlearning.com": "Great Learning Academy",
    "scrimba.com": "Scrimba",
    "aws.amazon.com": "AWS Training",
    "developers.google.com": "Google Developers",
    "kaggle.com": "Kaggle Learn",
    "freecodecamp.org": "freeCodeCamp",
    "cognitiveclass.ai": "IBM Cognitive Class",
    "elementsofai.com": "Elements of AI",
    "datacamp.com": "DataCamp",
    "codecademy.com": "Codecademy",
    "wandb.ai": "Weights & Biases Courses",
    "grow.google": "Google Career Certificates",
    "mygreatlearning.com": "Great Learning Academy",
    "scrimba.com": "Scrimba",
    "aws.amazon.com": "AWS Training",
    "developers.google.com": "Google Developers",
    "cloudskillsboost.google": "Google Cloud Skills Boost",
    "trailhead.salesforce.com": "Salesforce Trailhead",
    "learn.databricks.com": "Databricks Academy",
    "education.github.com": "GitHub Education",
    "university.mongodb.com": "MongoDB University",
    "talentsprint.com": "TalentSprint",
    "intellipaat.com": "Intellipaat",
    "simplilearn.com": "Simplilearn",
    "coursesity.com": "Coursesity",
    "classcentral.com": "Class Central",
    "open.edu": "The Open University",
    "ocw.mit.edu": "MIT OpenCourseWare",
    "online.stanford.edu": "Stanford Online",
    "extension.harvard.edu": "Harvard Extension",
    "mooc.org": "MOOC.org",
    "iversity.org": "Iversity",
    "openclassrooms.com": "OpenClassrooms",
    "aiforeveryone.org": "AI For Everyone",
    "upgrad.com": "UpGrad",
    "swayam.gov.in": "SWAYAM",
    "nptel.ac.in": "NPTEL",
    "saudidigitalacademy.sa": "Saudi Digital Academy",
    "sdaia.gov.sa": "SDAIA",
    "mcit.gov.sa": "وزارة الاتصالات",

    
}

SAUDI_ARABIC_COURSE_PLATFORM_URLS = {
    "satr.tuwaiq.edu.sa": "https://satr.tuwaiq.edu.sa/",
    "tuwaiq.edu.sa": "https://tuwaiq.edu.sa/bootcamps",
    "sda.mcit.gov.sa": "https://sda.mcit.gov.sa/ar/programs",
    "futureskills.mcit.gov.sa": "https://futureskills.mcit.gov.sa/",
    "sdaia.gov.sa": "https://sdaia.gov.sa/ar/Sectors/BuildingCapacity/academy/Pages/default.aspx",
    "ethrai.sa": "https://ethrai.sa/",
    "hub.misk.org.sa": "https://hub.misk.org.sa/ar/misk-skills/",
    "academy.kaust.edu.sa": "https://academy.kaust.edu.sa/",
    "ithra.com": "https://www.ithra.com/ar/visit-ithra/attractions/ithra-academy/academy-courses",
    "edraak.org": "https://www.edraak.org/en/explore/",
    "rwaq.org": "https://www.rwaq.org/courses",
    "maharatech.gov.eg": "https://maharatech.gov.eg/?lang=ar",
}

SAUDI_ARABIC_COURSE_PLATFORM_NAMES = {
    "satr.tuwaiq.edu.sa": "Satr",
    "tuwaiq.edu.sa": "Tuwaiq Academy",
    "sda.mcit.gov.sa": "Saudi Digital Academy",
    "futureskills.mcit.gov.sa": "Future Skills",
    "sdaia.gov.sa": "SDAIA Academy",
    "ethrai.sa": "Ethrai",
    "hub.misk.org.sa": "Misk Skills",
    "academy.kaust.edu.sa": "KAUST Academy",
    "ithra.com": "Ithra Academy",
    "edraak.org": "Edraak",
    "rwaq.org": "Rwaq",
    "maharatech.gov.eg": "Mahara-Tech",
}

PRIMARY_ADULT_FREE_AI_COURSE_SOURCES = (
    "satr.tuwaiq.edu.sa",
    "futureskills.mcit.gov.sa",
    "edraak.org",
)

EMPLOYEE_AI_FREE_PLATFORM_URLS_EXTRA = {
    "academy.openai.com": "https://academy.openai.com/pages/courses",
    "anthropic.com": "https://www.anthropic.com/learn/claude-for-work",
    "skills.google": "https://www.skills.google/paths/2336",
    "learn.microsoft.com": "https://learn.microsoft.com/en-us/ai/",
    "skillsbuild.org": "https://skillsbuild.org/adult-learners/explore-learning/artificial-intelligence",
    "academy.asana.com": "https://academy.asana.com/ai-for-work-skill-badge",
    "academy.notion.com": "https://academy.notion.com/getting-started-with-notion-ai",
    "university.atlassian.com": "https://university.atlassian.com/student/page/2922771-get-started-with-rovo-ai-free-public-class",
    "academy.airtable.com": "https://academy.airtable.com/page/ai-learning-hub",
    "academy.miro.com": "https://academy.miro.com/fundamentals-of-ai",
    "learn.zapier.com": "https://learn.zapier.com/",
    "academy.make.com": "https://academy.make.com/courses/ai-agents-foundationC05",
    "academy.hubspot.com": "https://academy.hubspot.com/courses/AI-for-Marketers",
    "semrush.com": "https://www.semrush.com/academy/courses/ai-search/",
    "academy.synthesia.io": "https://academy.synthesia.io/",
}

EMPLOYEE_AI_FREE_PLATFORM_NAMES_EXTRA = {
    "academy.openai.com": "OpenAI Academy",
    "anthropic.com": "Anthropic Learn",
    "skills.google": "Google AI Essentials",
    "learn.microsoft.com": "Microsoft Learn AI",
    "skillsbuild.org": "IBM SkillsBuild",
    "academy.asana.com": "Asana Academy",
    "academy.notion.com": "Notion Academy",
    "university.atlassian.com": "Atlassian University",
    "academy.airtable.com": "Airtable Academy",
    "academy.miro.com": "Miro Academy",
    "learn.zapier.com": "Zapier Academy",
    "academy.make.com": "Make Academy",
    "academy.hubspot.com": "HubSpot Academy",
    "semrush.com": "Semrush Academy",
    "academy.synthesia.io": "Synthesia Academy",
}

EMPLOYEE_AI_PLATFORM_PRIORITY = {
    "academy.openai.com": 5,
    "anthropic.com": 5,
    "skills.google": 5,
    "learn.microsoft.com": 5,
    "skillsbuild.org": 5,
    "academy.hubspot.com": 4,
    "academy.asana.com": 4,
    "academy.notion.com": 4,
    "university.atlassian.com": 4,
    "academy.airtable.com": 4,
    "academy.miro.com": 4,
    "learn.zapier.com": 4,
    "academy.make.com": 4,
    "semrush.com": 3,
    "academy.synthesia.io": 3,
}

EMPLOYEE_AI_EXTRA_QUERIES = (
    'site:academy.openai.com ("AI" OR "ChatGPT" OR "agents") ("work" OR "productivity" OR "workflow" OR "courses")',
    'site:anthropic.com/learn ("Claude" OR "AI") ("work" OR "professional" OR "productivity")',
    'site:skills.google ("AI Essentials" OR "generative AI") ("productivity" OR "work" OR "business")',
    'site:learn.microsoft.com/en-us/ai ("business" OR "productivity" OR "Copilot" OR "AI")',
    'site:skillsbuild.org/adult-learners ("artificial intelligence" OR "generative AI")',
    'site:academy.hubspot.com/courses ("AI" OR "artificial intelligence") ("marketing" OR "sales" OR "business")',
    'site:academy.asana.com ("AI for work" OR "AI Studio" OR "productivity")',
    'site:academy.notion.com ("Notion AI" OR "AI") ("docs" OR "projects" OR "work")',
    'site:university.atlassian.com ("Rovo" OR "Atlassian Intelligence" OR "AI")',
    'site:academy.airtable.com ("AI" OR "agentic" OR "automation")',
    'site:academy.miro.com ("AI" OR "Miro AI")',
    'site:learn.zapier.com ("AI" OR "automation" OR "workflow")',
    'site:academy.make.com ("AI" OR "AI Agents" OR "automation")',
    'site:semrush.com/academy ("AI" OR "AI Search") ("marketing" OR "content")',
    'site:academy.synthesia.io ("AI video" OR "video creation" OR "training videos")',
)

COURSE_PLATFORM_BASE_URLS = {
    "Anthropic Learn": "https://www.anthropic.com/learn",
    "Google Skills": "https://www.skills.google/",
    "IBM SkillsBuild": "https://skillsbuild.org/adult-learners",
    "Microsoft Learn": "https://learn.microsoft.com/en-us/training/",
    "OpenAI Academy": "https://academy.openai.com/",
    "Airtable Academy": "https://academy.airtable.com/",
    "Asana Academy": "https://academy.asana.com/",
    "Atlassian University": "https://university.atlassian.com/",
    "HubSpot Academy": "https://academy.hubspot.com/courses",
    "Make Academy": "https://academy.make.com/",
    "Miro Academy": "https://academy.miro.com/",
    "Notion Academy": "https://academy.notion.com/",
    "Zapier Academy": "https://learn.zapier.com/courses/zapier-academy-published-preview",
    "Semrush Academy": "https://www.semrush.com/academy/",
}

ADDITIONAL_CORE_20_COURSE_BANK_PLATFORMS = {
    "coursera.org": "https://www.coursera.org/courses",
    "edx.org": "https://www.edx.org/courses",
    "futurelearn.com": "https://www.futurelearn.com/courses",
    "datacamp.com": "https://www.datacamp.com/courses-all",
    "cognitiveclass.ai": "https://cognitiveclass.ai/courses",
    "deeplearning.ai": "https://www.deeplearning.ai/courses/",
    "cloudskillsboost.google": "https://www.cloudskillsboost.google/catalog",
    "adobe.com": "https://www.adobe.com/learn",
    "canva.com": "https://www.canva.com/design-school/courses/",
    "academy.synthesia.io": "https://academy.synthesia.io/",
    "mygreatlearning.com": "https://www.mygreatlearning.com/academy",
    "satr.tuwaiq.edu.sa": "https://satr.tuwaiq.edu.sa/",
    "futureskills.mcit.gov.sa": "https://futureskills.mcit.gov.sa/",
}

COURSE_BANK_EXTRA_PLATFORMS_CLEAN = {
    "aws.amazon.com": "https://aws.amazon.com/training/",
    "huggingface.co": "https://huggingface.co/learn",
    "kaggle.com": "https://www.kaggle.com/learn",
    "nvidia.com": "https://www.nvidia.com/en-us/training/",
    "trailhead.salesforce.com": "https://trailhead.salesforce.com/content/learn/trails",
    "wandb.ai": "https://wandb.ai/site/courses",
    "elementsofai.com": "https://www.elementsofai.com/",
    "grow.google": "https://grow.google/certificates/",
    "linkedin.com": "https://www.linkedin.com/learning/courses",
    "edraak.org": "https://www.edraak.org/en/explore/",
    "awwwards.com": "https://www.awwwards.com/academy/",
    "domestika.org": "https://www.domestika.org/en/courses",
    "figma.com": "https://www.figma.com/academy/",
    "udacity.com": "https://www.udacity.com/catalog/all",
    "udemy.com": "https://www.udemy.com/courses/",
}

COURSE_OFFICIAL_PLATFORM_URLS = {
    "coursera.org": "https://www.coursera.org/courses",
    "udemy.com": "https://www.udemy.com/courses/",
    "edx.org": "https://www.edx.org/courses",
    "linkedin.com": "https://www.linkedin.com/learning/courses",
    "skillshare.com": "https://www.skillshare.com/en/browse",
    "masterclass.com": "https://www.masterclass.com/classes",
    "domestika.org": "https://www.domestika.org/en/courses",
    "futurelearn.com": "https://www.futurelearn.com/courses",
    "udacity.com": "https://www.udacity.com/catalog/all",
    "pluralsight.com": "https://www.pluralsight.com/courses",
    "codecademy.com": "https://www.codecademy.com/catalog",
    "openclassrooms.com": "https://openclassrooms.com/en/courses",
    "iversity.org": "https://iversity.org/en/courses",
    "kaggle.com": "https://www.kaggle.com/learn",
    "datacamp.com": "https://www.datacamp.com/courses-all",
    "cognitiveclass.ai": "https://cognitiveclass.ai/courses",
    "deeplearning.ai": "https://www.deeplearning.ai/courses/",
    "fast.ai": "https://course.fast.ai/",
    "huggingface.co": "https://huggingface.co/learn",
    "freecodecamp.org": "https://www.freecodecamp.org/learn/",
    "elementsofai.com": "https://www.elementsofai.com/",
    "learnprompting.org": "https://learnprompting.org/docs/intro",
    "promptingguide.ai": "https://www.promptingguide.ai/",
    "wandb.ai": "https://wandb.ai/site/courses",
    "scrimba.com": "https://scrimba.com/courses",
    "mygreatlearning.com": "https://www.mygreatlearning.com/academy",
    "simplilearn.com": "https://www.simplilearn.com/free-online-courses",
    "intellipaat.com": "https://intellipaat.com/courses/",
    "upgrad.com": "https://www.upgrad.com/free-courses/",
    "microsoft.com": "https://learn.microsoft.com/en-us/training/",
    "learn.microsoft.com": "https://learn.microsoft.com/en-us/training/",
    "google.com": "https://www.skills.google/",
    "skills.google": "https://www.skills.google/",
    "cloudskillsboost.google": "https://www.cloudskillsboost.google/catalog",
    "developers.google.com": "https://developers.google.com/learn",
    "grow.google": "https://grow.google/certificates/",
    "aws.amazon.com": "https://aws.amazon.com/training/",
    "nvidia.com": "https://www.nvidia.com/en-us/training/",
    "trailhead.salesforce.com": "https://trailhead.salesforce.com/content/learn/trails",
    "learn.databricks.com": "https://www.databricks.com/learn/training/catalog",
    "university.mongodb.com": "https://learn.mongodb.com/catalog",
    "education.github.com": "https://skills.github.com/",
    "adobe.com": "https://www.adobe.com/learn",
    "canva.com": "https://www.canva.com/designschool/",
    "figma.com": "https://www.figma.com/academy/",
    "superhi.com": "https://www.superhi.com/courses",
    "awwwards.com": "https://www.awwwards.com/academy/",
    "edraak.org": "https://www.edraak.org/en/explore/",
    "rwaq.org": "https://www.rwaq.org/courses",
    "doroob.sa": "https://doroob.sa/",
    "doroob.com.sa": "https://doroob.sa/",
    "saudidigitalacademy.sa": "https://sda.edu.sa/",
    "sdaia.gov.sa": "https://sdaia.gov.sa/en/Sectors/academy/Pages/default.aspx",
    "mcit.gov.sa": "https://future-skills.mcit.gov.sa/",
    "open.edu": "https://www.open.edu/openlearn/free-courses/full-catalogue",
    "ocw.mit.edu": "https://ocw.mit.edu/search/?type=course",
    "online.stanford.edu": "https://online.stanford.edu/explore",
    "extension.harvard.edu": "https://extension.harvard.edu/academics/programs/",
    "mooc.org": "https://www.mooc.org/courses",
    "swayam.gov.in": "https://swayam.gov.in/explorer",
    "nptel.ac.in": "https://onlinecourses.nptel.ac.in/",
    "spoken-tutorial.org": "https://spoken-tutorial.org/tutorial-search/",
    "digiskills.pk": "https://digiskills.pk/CourseDetails.aspx",
    "iabac.org": "https://iabac.org/courses/",
}


def course_path_patterns_from_url(url: str) -> tuple[str, ...]:
    parsed = urlparse(str(url or ""))
    path = re.sub(r"/+$", "", parsed.path or "")
    if not path:
        return ("/",)
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"ar", "en", "en-us"}:
        return ("/" + "/".join(parts[:2]) + "/",)
    return ("/" + parts[0] + "/",)


def platform_name_from_domain(domain: str) -> str:
    root = str(domain or "").lower().replace("www.", "").split(".")[0]
    return root.replace("-", " ").replace("_", " ").title() or "Course Platform"


COURSE_PLATFORM_URLS = {
    source_domain(url): url
    for url in COURSE_PLATFORM_BASE_URLS.values()
    if source_domain(url)
}
COURSE_PLATFORM_URLS.update(ADDITIONAL_CORE_20_COURSE_BANK_PLATFORMS)
COURSE_PLATFORM_URLS.update(COURSE_BANK_EXTRA_PLATFORMS_CLEAN)
COURSE_DIRECT_PATHS = {
    domain: course_path_patterns_from_url(url)
    for domain, url in COURSE_PLATFORM_URLS.items()
}
COURSE_DIRECT_PATH_SUPPLEMENTS = {
    "coursera.org": ("/learn/", "/specializations/", "/professional-certificates/", "/projects/"),
    "udemy.com": ("/course/",),
    "edx.org": ("/learn/", "/course/", "/certificates/", "/programs/"),
    "linkedin.com": ("/learning/",),
    "skillshare.com": ("/classes/", "/en/classes/"),
    "masterclass.com": ("/classes/",),
    "domestika.org": ("/courses/",),
    "futurelearn.com": ("/courses/", "/microcredentials/"),
    "udacity.com": ("/course/", "/nanodegree/"),
    "pluralsight.com": ("/courses/", "/paths/"),
    "codecademy.com": ("/learn/", "/courses/"),
    "openclassrooms.com": ("/en/courses/",),
    "deeplearning.ai": ("/courses/", "/short-courses/"),
    "fast.ai": ("/courses/", "/course"),
    "huggingface.co": ("/learn/",),
    "freecodecamp.org": ("/learn/",),
    "datacamp.com": ("/courses/", "/learn/"),
    "cognitiveclass.ai": ("/courses/", "/learn/"),
    "microsoft.com": ("/learn/", "/training/"),
    "learn.microsoft.com": ("/en-us/training/", "/training/"),
    "cloudskillsboost.google": ("/catalog/", "/course_templates/", "/paths/", "/quests/"),
    "trailhead.salesforce.com": ("/content/learn/", "/trails/", "/modules/"),
    "learn.databricks.com": ("/courses/", "/learning-paths/"),
    "university.mongodb.com": ("/courses/", "/catalog/"),
    "adobe.com": ("/learn/",),
    "canva.com": ("/designschool/", "/learn/"),
    "figma.com": ("/academy/",),
    "superhi.com": ("/courses/",),
    "awwwards.com": ("/academy/", "/courses/"),
    "satr.tuwaiq.edu.sa": ("/",),
    "tuwaiq.edu.sa": ("/bootcamps/", "/programs/"),
    "sda.mcit.gov.sa": ("/ar/programs/", "/programs/"),
    "futureskills.mcit.gov.sa": ("/",),
    "sdaia.gov.sa": ("/ar/Sectors/BuildingCapacity/academy/", "/en/Sectors/academy/"),
    "ethrai.sa": ("/",),
    "hub.misk.org.sa": ("/ar/misk-skills/", "/misk-skills/"),
    "academy.kaust.edu.sa": ("/",),
    "ithra.com": ("/ar/visit-ithra/attractions/ithra-academy/",),
    "edraak.org": ("/course/", "/courses/", "/programs/", "/en/explore/"),
    "rwaq.org": ("/courses/", "/course/"),
    "maharatech.gov.eg": ("/course/", "/mod/", "/"),
    "academy.openai.com": ("/pages/courses/", "/courses/", "/"),
    "anthropic.com": ("/learn/",),
    "skills.google": ("/paths/", "/"),
    "skillsbuild.org": ("/adult-learners/", "/"),
    "academy.asana.com": ("/ai-for-work-skill-badge/", "/courses/", "/"),
    "academy.notion.com": ("/getting-started-with-notion-ai/", "/"),
    "university.atlassian.com": ("/student/page/", "/"),
    "academy.airtable.com": ("/page/ai-learning-hub/", "/"),
    "academy.miro.com": ("/fundamentals-of-ai/", "/"),
    "learn.zapier.com": ("/",),
    "academy.make.com": ("/courses/",),
    "academy.hubspot.com": ("/courses/",),
    "semrush.com": ("/academy/courses/", "/academy/"),
    "academy.synthesia.io": ("/",),
}
for domain, patterns in COURSE_DIRECT_PATH_SUPPLEMENTS.items():
    if domain not in COURSE_DIRECT_PATHS:
        continue
    existing = COURSE_DIRECT_PATHS.get(domain, ())
    COURSE_DIRECT_PATHS[domain] = tuple(dict.fromkeys(tuple(existing) + tuple(patterns)))
COURSE_PLATFORM_NAMES = {
    source_domain(url): name
    for name, url in COURSE_PLATFORM_BASE_URLS.items()
    if source_domain(url)
}
COURSE_PLATFORM_NAMES.update({
    domain: SAUDI_ARABIC_COURSE_PLATFORM_NAMES[domain]
    for domain in PRIMARY_ADULT_FREE_AI_COURSE_SOURCES
    if domain in SAUDI_ARABIC_COURSE_PLATFORM_NAMES
})
COURSE_PLATFORM_NAMES.update({
    "coursera.org": "Coursera",
    "udemy.com": "Udemy",
    "edx.org": "edX",
    "linkedin.com": "LinkedIn Learning",
    "skillshare.com": "Skillshare",
    "masterclass.com": "MasterClass",
    "domestika.org": "Domestika",
    "futurelearn.com": "FutureLearn",
    "udacity.com": "Udacity",
    "pluralsight.com": "Pluralsight",
    "codecademy.com": "Codecademy",
    "openclassrooms.com": "OpenClassrooms",
    "iversity.org": "Iversity",
    "kaggle.com": "Kaggle Learn",
    "datacamp.com": "DataCamp",
    "cognitiveclass.ai": "IBM Cognitive Class",
    "deeplearning.ai": "DeepLearning.AI",
    "fast.ai": "fast.ai",
    "huggingface.co": "Hugging Face",
    "freecodecamp.org": "freeCodeCamp",
    "elementsofai.com": "Elements of AI",
    "learnprompting.org": "Learn Prompting",
    "promptingguide.ai": "Prompting Guide",
    "wandb.ai": "Weights & Biases Courses",
    "scrimba.com": "Scrimba",
    "mygreatlearning.com": "Great Learning Academy",
    "simplilearn.com": "Simplilearn",
    "intellipaat.com": "Intellipaat",
    "upgrad.com": "UpGrad",
    "microsoft.com": "Microsoft Learn",
    "learn.microsoft.com": "Microsoft Learn",
    "google.com": "Google Skills",
    "skills.google": "Google Skills",
    "cloudskillsboost.google": "Google Cloud Skills Boost",
    "developers.google.com": "Google Developers",
    "grow.google": "Google Career Certificates",
    "aws.amazon.com": "AWS Training",
    "nvidia.com": "NVIDIA Deep Learning Institute",
    "trailhead.salesforce.com": "Salesforce Trailhead",
    "learn.databricks.com": "Databricks Academy",
    "university.mongodb.com": "MongoDB University",
    "education.github.com": "GitHub Skills",
    "adobe.com": "Adobe Learn",
    "canva.com": "Canva Design School",
    "figma.com": "Figma Academy",
    "superhi.com": "SuperHi",
    "awwwards.com": "Awwwards Academy",
    "doroob.sa": "Doroob",
    "doroob.com.sa": "Doroob",
    "saudidigitalacademy.sa": "Saudi Digital Academy",
    "mcit.gov.sa": "Future Skills",
    "open.edu": "The Open University",
    "ocw.mit.edu": "MIT OpenCourseWare",
    "online.stanford.edu": "Stanford Online",
    "extension.harvard.edu": "Harvard Extension",
    "mooc.org": "MOOC.org",
    "swayam.gov.in": "SWAYAM",
    "nptel.ac.in": "NPTEL",
    "spoken-tutorial.org": "Spoken Tutorial",
    "digiskills.pk": "DigiSkills",
    "iabac.org": "IABAC",
})
COURSE_DIVERSITY_TARGET_DOMAINS = PRIMARY_ADULT_FREE_AI_COURSE_SOURCES + (
    "academy.openai.com",
    "anthropic.com",
    "skills.google",
    "learn.microsoft.com",
    "skillsbuild.org",
    "academy.hubspot.com",
    "academy.asana.com",
    "academy.notion.com",
    "university.atlassian.com",
    "academy.airtable.com",
    "academy.miro.com",
    "learn.zapier.com",
    "academy.make.com",
    "semrush.com",
    "academy.synthesia.io",
    "linkedin.com",
    "microsoft.com",
    "learn.microsoft.com",
    "coursera.org",
    "deeplearning.ai",
    "datacamp.com",
    "cloudskillsboost.google",
    "trailhead.salesforce.com",
)

COURSE_PLATFORM_DISCOVERY_RE = re.compile(
    r"\b(course|courses|class|learning path|training|certificate|certification|academy|learn|microcredential)\b",
    re.IGNORECASE,
)
COURSE_AI_DISCOVERY_RE = re.compile(
    r"\b(ai|artificial intelligence|generative ai|chatgpt|gemini|claude|copilot|prompt engineering|llm|machine learning)\b",
    re.IGNORECASE,
)
COURSE_INTENT_QUERY = '("AI course" OR "generative AI course" OR "prompt engineering course" OR "AI training" OR "AI certificate")'
WORKFORCE_INTENT_QUERY = '("employee" OR "employees" OR "professional" OR "professionals" OR "workplace" OR "productivity" OR "business" OR "upskilling" OR "workforce" OR "موظفين" OR "مهنيين" OR "بيئة العمل" OR "الإنتاجية" OR "تطوير المهارات" OR "الأعمال")'
COURSE_NON_FATAL_PAGE_STATUSES = ("page_http_401", "page_http_403", "page_http_429")
COURSE_PLATFORM_DOMAIN_ALIASES = {
    "learn.zapier.com": {"zapier.com"},
}
COURSE_DIRECT_SEED_TEXT_OVERRIDES = {
    "learn.zapier.com": (
        "Zapier Academy course training. Build AI Skills that transform your work. "
        "AI Builder Path and AI Orchestrator Path teach automation and workflow skills for work."
    ),
}

ADVANCED_COURSE_TERMS = (
    "advanced",
    "advanced-level",
    "advanced level",
    "graduate-level",
    "graduate level",
    "postgraduate",
    "intermediate to advanced",
)

ENDED_COURSE_TERMS = (
    "course ended",
    "enrollment closed",
    "registration closed",
    "closed for enrollment",
    "no longer available",
    "expired",
    "archived course",
)

WORKFORCE_COURSE_TERMS = (
    "employee", "employees", "workforce", "professional", "professionals",
    "workplace", "productivity", "upskill", "upskilling", "reskill",
    "reskilling", "skills development", "develop your skills", "business",
    "enterprise", "organization", "organisations", "organizations", "sme",
    "small business", "career", "career development", "job-ready", "job ready",
    "vocational", "industry", "manager", "managers", "leader", "leaders",
    "teams", "for work", "at work", "موظف", "موظفين", "الموظفين", "الموظفات",
    "مهني", "مهنيين", "المهنيين", "مهنية", "احترافي", "احترافية",
    "بيئة العمل", "مكان العمل", "الإنتاجية", "انتاجية", "تطوير المهارات",
    "رفع المهارات", "صقل المهارات", "المهارات", "الأعمال", "اعمال",
    "منشآت", "المنشآت", "رواد الأعمال", "رائد أعمال", "التدريب المهني",
    "سوق العمل", "القوى العاملة", "المسار المهني", "وظيفي", "وظيفية",
)

STUDENT_COURSE_REJECT_TERMS = (
    "student", "students", "school", "schools", "university", "universities",
    "college", "campus", "academic", "academics", "scholarship", "scholarships",
    "homework", "assignment", "assignments", "exam", "exams", "test prep",
    "classroom", "teacher", "teachers", "undergraduate", "graduate student",
    "طلاب", "الطلاب", "طالب", "طالبة", "مدرسة", "مدارس", "المدارس",
    "جامعة", "جامعات", "الجامعة", "الجامعات", "أكاديمي", "اكاديمي",
    "منحة", "منح", "المنح", "واجب", "واجبات", "اختبار", "اختبارات",
    "امتحان", "امتحانات", "فصل دراسي", "معلم", "معلمين", "معلمات",
)

STRONG_STUDENT_COURSE_REJECT_TERMS = (
    "k-12", "kids", "children", "university students",
    "homework", "scholarship", "scholarships", "assignment", "assignments",
    "test prep", "classroom", "undergraduate", "graduate student",
    "مدارس", "مدرسة", "طلاب", "طالبات", "جامعي", "جامعية", "منح", "منحة",
    "واجبات", "واجب",
)

PROFESSIONAL_PLATFORM_ALLOWLIST = {
    "skillsbuild.org",
    "academy.hubspot.com",
    "academy.asana.com",
    "academy.airtable.com",
    "academy.make.com",
    "academy.miro.com",
    "academy.notion.com",
    "semrush.com",
}


def is_workforce_course_text(text: str = "") -> bool:
    normalized = str(text or "").lower()
    return any(term in normalized for term in WORKFORCE_COURSE_TERMS)


DEVELOPER_ONLY_COURSE_TERMS = (
    "api", "sdk", "cli", "github", "git", "repository", "repo", "framework",
    "library", "libraries", "developer", "developers", "coding", "code",
    "programming", "python", "javascript", "typescript", "java", "rust",
    "kubernetes", "docker", "deployment", "deploy", "inference", "fine-tuning",
    "finetuning", "model training", "mlops", "agent framework", "agents sdk",
)


def has_student_course_reject_signal(text: str = "", domain: str = "") -> bool:
    normalized = str(text or "").lower()
    normalized_domain = source_domain(domain) or str(domain or "").lower().replace("www.", "")
    if domain_matches(normalized_domain, PROFESSIONAL_PLATFORM_ALLOWLIST):
        return any(term in normalized for term in STRONG_STUDENT_COURSE_REJECT_TERMS)
    return any(term in normalized for term in STUDENT_COURSE_REJECT_TERMS)


def has_developer_only_course_signal(text: str = "") -> bool:
    normalized = str(text or "").lower()
    if not any(term in normalized for term in DEVELOPER_ONLY_COURSE_TERMS):
        return False
    return not is_workforce_course_text(normalized)


# Hit in production 2026-07-12: an Accenture "AI Bridge" course page passed
# every other check (direct URL, course + AI signals) but its actual page
# body said registration had closed - the listing was real, just no longer
# enrollable. Title/snippet rarely carry this ("AI Bridge | Future Skills
# Portal" gives no hint), so this checks the full evidence string (which
# includes page_text) rather than title+snippet like has_ai above.
EXPIRED_COURSE_TERMS = (
    "registration has closed", "registration is closed", "registration closed",
    "enrollment has closed", "enrollment is closed", "enrollment closed",
    "applications closed", "applications are closed", "no longer accepting",
    "no longer available", "course has ended", "this course has ended",
    "registration period has ended", "sign-ups closed", "signups closed",
    "تم انتهاء فترة التسجيل", "انتهت فترة التسجيل", "انتهاء فترة التسجيل",
    "انتهى التسجيل", "التسجيل مغلق", "أغلق التسجيل", "تم إغلاق التسجيل",
    "التسجيل غير متاح", "لم يعد التسجيل متاحًا", "انتهت المدة المحددة للتسجيل",
)


def has_expired_course_signal(text: str = "") -> bool:
    normalized = str(text or "").lower()
    return any(term in normalized for term in EXPIRED_COURSE_TERMS)


# Returns whether domain matches is true for the current input.
def domain_matches(domain: str, allowed: tuple[str, ...] | list[str] | set[str]) -> bool:
    domain = (domain or "").lower().replace("www.", "")
    return any(domain == root or domain.endswith(f".{root}") for root in allowed)


# Prepares clean course url so downstream stages receive consistent data.
def clean_course_url(url: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = re.sub(r"/+$", "", parsed.path or "")
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


# Performs the course platform from url helper step.
def course_platform_from_url(url: str = "") -> str:
    domain = source_domain(url)
    for host, name in COURSE_PLATFORM_NAMES.items():
        if domain == host or domain.endswith(f".{host}"):
            return name
    if not domain:
        return "Course"
    labels = [part for part in domain.split(".") if part and part not in {"www"}]
    if not labels:
        return "Course"
    cleaned_labels = []
    for part in labels:
        if part in {"com", "org", "net", "edu", "co", "io", "ai", "dev"}:
            if cleaned_labels:
                cleaned_labels.append(part.upper() if part in {"io", "ai"} else part.title())
            continue
        cleaned_labels.append(part.replace("-", " ").title())
    if not cleaned_labels:
        return domain.split(".")[0].replace("-", " ").title()
    return " ".join(cleaned_labels)


# Performs the course url is direct helper step.
# Loads discovered course platforms from the storage file.
def load_discovered_platforms() -> dict:
    data = load_json(DISCOVERED_PLATFORMS_FILE, {})
    return data if isinstance(data, dict) else {}


# Turns a domain into a readable platform name for promoted discoveries.
def readable_platform_name(domain: str = "") -> str:
    root = str(domain or "").lower().replace("www.", "").split(".")[0]
    return root.replace("-", " ").replace("_", " ").title() or "Course Platform"


# Returns the most common recorded URL path for a discovered platform.
def most_common_discovered_path(record: dict) -> str:
    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    if paths:
        return Counter(paths).most_common(1)[0][0] or "/"
    return str(record.get("url_path") or "/") or "/"


# Applies trusted-platform promotions from discovery memory for this run.
def apply_discovered_platform_promotions() -> None:
    discovered = load_discovered_platforms()
    changed = False
    for domain, record in discovered.items():
        if not isinstance(record, dict) or int(record.get("times_selected") or 0) < 3:
            continue
        path = most_common_discovered_path(record)
        if domain not in COURSE_DIRECT_PATHS:
            COURSE_DIRECT_PATHS[domain] = (path,)
            changed = True
        if domain not in COURSE_PLATFORM_NAMES:
            COURSE_PLATFORM_NAMES[domain] = readable_platform_name(domain)
            changed = True
        if not record.get("promoted"):
            record["promoted"] = True
            record["promoted_at"] = utc_now().date().isoformat()
            safe_print(f"[AI Updates] Auto-promoted platform: {domain} -> added to trusted list")
            log_event("courses.platform_auto_promoted", domain=domain, path=path)
            changed = True
    if changed:
        safe_write_json(DISCOVERED_PLATFORMS_FILE, discovered)


# Records unknown course platforms only after they reach the final output.
def record_discovered_course_platforms(courses: list[dict]) -> None:
    discovered = load_discovered_platforms()
    changed = False
    today = utc_now().date().isoformat()
    for item in courses or []:
        url = str(item.get("url") or item.get("source_url") or "").strip()
        domain = source_domain(url)
        if not domain or domain_matches(domain, COURSE_PLATFORM_NAMES.keys()):
            continue
        parsed = urlparse(url)
        path = parsed.path or "/"
        record = discovered.setdefault(domain, {
            "domain": domain,
            "first_seen": today,
            "url_path": path,
            "paths": {},
            "times_selected": 0,
        })
        record.setdefault("first_seen", today)
        record["url_path"] = path
        paths = record.setdefault("paths", {})
        paths[path] = int(paths.get(path) or 0) + 1
        record["times_selected"] = int(record.get("times_selected") or 0) + 1
        safe_print(f"[AI Updates] New platform discovered: {domain}")
        log_event("courses.platform_discovered", domain=domain, path=path, times_selected=record["times_selected"])
        changed = True
    if changed:
        safe_write_json(DISCOVERED_PLATFORMS_FILE, discovered)
        apply_discovered_platform_promotions()


def course_url_is_direct(url: str = "", title: str = "", content: str = "") -> bool:
    clean = str(url or "").lower()
    if not clean or any(term in clean for term in COURSE_BAD_URL_TERMS):
        return False
    domain = source_domain(clean)
    path = urlparse(clean).path.lower()
    evidence = f"{path} {title} {content}".lower()
    strong_course_path_terms = ("/course", "/courses", "/learn", "/training", "/academy", "/certificate", "/certification")
    strong_course_text_terms = (
        "course", "courses", "class", "classes", "learn", "learning", "training",
        "certificate", "certification", "short course", "specialization",
        "professional certificate", "nanodegree", "microcredential", "academy",
    )
    if any(path_term in path for path_term in strong_course_path_terms):
        return any(term in evidence for term in strong_course_text_terms)
    for host, patterns in COURSE_DIRECT_PATHS.items():
        if domain == host or domain.endswith(f".{host}"):
            if any(str(pattern or "").lower() in path for pattern in patterns):
                return True
            return False
    return False



# Performs the infer course level helper step.
def infer_course_level(text: str = "") -> str:
    """Classify the platform/course level used by the balanced course bank."""
    normalized = normalized_text(text)
    advanced_terms = (
        "advanced", "expert", "graduate", "professional certificate", "specialization",
        "mlops", "model deployment", "cloud engineering", "machine learning engineering",
        "deep learning", "architecture", "security", "developer", "developers", "api",
    )
    beginner_terms = (
        "beginner", "beginners", "fundamental", "fundamentals", "foundation", "foundations",
        "intro", "introduction", "basics", "basic", "essentials", "getting started",
        "for everyone", "non technical", "non-technical", "no code", "no-code",
        "first course", "starter", "start learning",
    )
    intermediate_terms = (
        "intermediate", "applied", "hands-on", "hands on", "practical", "project",
        "projects", "workflow", "workflows", "automation", "productivity", "build",
        "building", "create", "creating", "professional", "workplace", "business users",
        "prompt engineering", "advanced prompt", "use cases",
    )
    if any(term in normalized for term in advanced_terms):
        return "Advanced"
    if any(term in normalized for term in beginner_terms):
        return "Beginner"
    if any(term in normalized for term in intermediate_terms):
        return "Intermediate"
    return ""


# Performs the course candidate topic key helper step.
def course_candidate_topic_key(item: dict) -> str:
    text = normalized_text(
        " ".join(str(item.get(key) or "") for key in ("title", "text", "summary", "content", "source_query"))
    )
    topics = [
        ("prompting", ("prompt", "prompting")),
        ("generative_ai", ("generative", "chatgpt", "llm", "model")),
        ("productivity", ("productivity", "work", "office", "copilot")),
        ("creative", ("creative", "design", "image", "video", "canva", "adobe")),
        ("responsible_ai", ("responsible", "ethics", "safety")),
        ("basics", ("beginner", "basics", "fundamentals", "introduction", "intro")),
    ]
    for topic, terms in topics:
        if any(term in text for term in terms):
            return topic
    words = [word for word in text.split() if len(word) > 3]
    return words[0] if words else "general"


FREE_COURSE_URL_PATH_HINTS = ("/free-", "-free-", "/free/")


# Preferred at selection time (see level_balancing.build_level_bank
# sort_key_fn) rather than filtered here, so a strong paid course still beats
# a weak free one - this only breaks ties toward free sources.
def is_free_course(url: str, domain: str, *, text: str = "") -> bool:
    if domain in PRIMARY_ADULT_FREE_AI_COURSE_SOURCES or domain in EMPLOYEE_AI_FREE_PLATFORM_URLS_EXTRA:
        return True
    lowered_url = str(url or "").lower()
    if any(hint in lowered_url for hint in FREE_COURSE_URL_PATH_HINTS):
        return True
    return bool(re.search(r"\bfree\b", text or "", flags=re.IGNORECASE))


# Prepares normalize course candidate so downstream stages receive consistent data.
def normalize_course_candidate(raw: dict, *, fetch_source: str, query: str = "") -> dict | None:
    title = clean_text(raw.get("title") or "")
    url = clean_course_url(raw.get("url") or "")
    content = clean_text(raw.get("content") or raw.get("summary") or raw.get("text") or "")
    if not title or not url:
        return None
    if not query_site_domain_matches_url(query, url):
        return None
    domain = source_domain(url)
    direct_course = course_url_is_direct(url, title=title, content=content)
    open_web_discovery = fetch_source in {"exa_course_open_search", "exa_course_targeted_search"}
    known_platform = domain_matches(domain, COURSE_PLATFORM_NAMES.keys())
    if not domain_matches(domain, COURSE_INCLUDE_DOMAINS) and not (
        direct_course and (open_web_discovery or AI_UPDATES_COURSE_EXA_ALLOW_OUTSIDE_INCLUDE_DOMAINS)
    ):
        return None
    if not direct_course:
        return None
    text = f"{title} {content} {query}".lower()
    # Level-balanced newsletter change: keep advanced courses so the final bank
    # can include 2 Advanced cards; expired/low-quality pages are still rejected.
    if any(term in text for term in ENDED_COURSE_TERMS):
        return None
    audience_evidence = f"{title} {content} {query}"
    if has_student_course_reject_signal(audience_evidence, domain=domain):
        return None
    if has_developer_only_course_signal(audience_evidence):
        return None
    workforce_signal = is_workforce_course_text(audience_evidence)
    platform = course_platform_from_url(url)
    key = memory_url_key(url)
    published_date = clean_text(raw.get("published_date") or raw.get("published") or raw.get("date") or "")
    item = {
        "id": f"course-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
        "title": title,
        "text": content or f"Course from {platform} focused on practical AI skills.",
        "summary": content,
        "content": content,
        "url": url,
        "source_url": url,
        "date": published_date,
        "published": published_date,
        "published_date": published_date,
        "source": platform,
        "source_name": platform,
        "provider": platform,
        "platform": platform,
        "company": platform,
        "is_free": is_free_course(url, domain, text=text),
        "level": infer_course_level(f"{text} {url}"), #many platforms encode the level in the URL path (e.g. /advanced-python/).
        # Pass the URL into the caller so path tokens are included in the normalized text
        "certificate": "Certificate available" if "certificate" in text or "certification" in text else "",
        "logo": f"https://www.google.com/s2/favicons?sz=128&domain={domain}",
        "provider_logo": f"https://www.google.com/s2/favicons?sz=128&domain={domain}",
        "source_logo": f"https://www.google.com/s2/favicons?sz=128&domain={domain}",
        "type": "course",
        "fetch_source": fetch_source,
        "fetch_source_label": "API: Exa",
        "source_group": fetch_source,
        "discovery_source": fetch_source,
        "source_query": query,
        "open_web_discovery": open_web_discovery,
        "known_platform": known_platform,
        "workforce_signal": workforce_signal,
        "audience_review_required": not workforce_signal,
        "audience_review_reason": "missing_workforce_signal" if not workforce_signal else "",
    }
    return item


# Performs the diversify course candidates helper step.
def diversify_course_candidates(items: list[dict], limit: int) -> list[dict]:
    ranked = sorted(
        list(items or []),
        key=lambda item: (
            int(is_major_course_platform(item)),
            0 if item.get("fetch_source") == "exa_course_targeted_search" else 1,
            0 if item.get("fetch_source") == "exa_course_open_search" else 1,
        ),
    )
    selected = []
    seen_ids = set()
    seen_platforms = set()
    seen_topics = set()

    # Performs the item key helper step.
    def item_key(item: dict) -> str:
        key = memory_url_key(item.get("url") or "")
        return key or str(id(item))

    # Performs the platform key helper step.
    def platform_key(item: dict) -> str:
        return normalized_text(item.get("platform") or item.get("provider") or source_domain(item.get("url") or ""))

    # Performs the add helper step.
    def add(item: dict | None) -> bool:
        if item is None:
            return False
        key = item_key(item)
        if key in seen_ids:
            return False
        selected.append(item)
        seen_ids.add(key)
        platform = platform_key(item)
        if platform:
            seen_platforms.add(platform)
        topic = course_candidate_topic_key(item)
        if topic:
            seen_topics.add(topic)
        return True

    # Performs the first for level helper step.
    def first_for_level(level: str, *, prefer_new_platform: bool = True, prefer_new_topic: bool = True) -> dict | None:
        for item in ranked:
            if item_key(item) in seen_ids or item.get("level") != level:
                continue
            platform = platform_key(item)
            if prefer_new_platform and platform in seen_platforms:
                continue
            topic = course_candidate_topic_key(item)
            if prefer_new_topic and topic in seen_topics:
                continue
            return item
        return None

    # Put both visible levels into the candidate pool early so GPT can actually pick them.
    add(
        first_for_level("Beginner", prefer_new_platform=True, prefer_new_topic=True)
        or first_for_level("Beginner", prefer_new_platform=True, prefer_new_topic=False)
        or first_for_level("Beginner", prefer_new_platform=False, prefer_new_topic=False)
    )
    add(
        first_for_level("Intermediate", prefer_new_platform=True, prefer_new_topic=True)
        or first_for_level("Intermediate", prefer_new_platform=True, prefer_new_topic=False)
        or first_for_level("Intermediate", prefer_new_platform=False, prefer_new_topic=False)
    )

    for item in ranked:
        if len(selected) >= limit:
            break
        platform = platform_key(item)
        topic = course_candidate_topic_key(item)
        if platform and platform not in seen_platforms and topic and topic not in seen_topics:
            add(item)

    for item in ranked:
        if len(selected) >= limit:
            break
        platform = platform_key(item)
        if platform and platform not in seen_platforms:
            add(item)

    for item in ranked:
        if len(selected) >= limit:
            break
        add(item)

    for index, item in enumerate(selected[:limit], start=1):
        item["position"] = index
    return selected[:limit]


# Fetches fetch exa course query from the configured external source.
def fetch_exa_course_query(
    query: str,
    max_results: int = 10,
    *,
    include_domains: bool = True,
    fetch_source: str = "exa_course_search",
) -> list[dict]:
    if not EXA_API_KEY:
        safe_print("[AI Updates] Exa course skipped: missing EXA_API_KEY")
        return []
    payload = {
        "query": query,
        "numResults": max(1, max_results),
        "type": COURSE_QUERY.get("type") or "neural",
        "contents": {"text": True, "highlights": True},
    }
    if COURSE_QUERY.get("startPublishedDate"):
        payload["startPublishedDate"] = COURSE_QUERY.get("startPublishedDate")
    if include_domains:
        payload["includeDomains"] = list(COURSE_QUERY.get("includeDomains") or COURSE_INCLUDE_DOMAINS)
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    try:
        response = requests.post("https://api.exa.ai/search", headers=headers, json=payload, timeout=AI_UPDATES_EXA_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        safe_print(f"[AI Updates] Exa course failed: {exc}")
        return []

    output = []
    for result in data.get("results") or []:
        highlights = result.get("highlights") or []
        snippet = " ".join(str(part or "") for part in highlights[:3]).strip()
        item = normalize_course_candidate(
            {
                "title": result.get("title") or "",
                "url": result.get("url") or "",
                "content": result.get("text") or snippet,
                "published_date": result.get("publishedDate") or "",
            },
            fetch_source=fetch_source,
            query=query,
        )
        if item:
            output.append(item)
    safe_print(f"[AI Updates] Exa course query collected {len(output)}/{len(data.get('results') or [])}: {query[:72]}")
    return output


# Fetches open-web course candidates without Exa includeDomains restrictions.
def fetch_open_web_course_candidates(max_results: int = 10) -> list[dict]:
    per_query = max(3, min(max_results, AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY))
    output = []
    seen_urls = set()
    with ThreadPoolExecutor(max_workers=min(len(OPEN_WEB_COURSE_QUERIES), 4)) as executor:
        futures = {
            executor.submit(
                fetch_exa_course_query,
                query,
                per_query,
                include_domains=False,
                fetch_source="exa_course_open_search",
            ): query
            for query in OPEN_WEB_COURSE_QUERIES
        }
        for future in as_completed(futures):
            for item in future.result() or []:
                key = memory_url_key(item.get("url") or "")
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                output.append(item)
    log_event(
        "courses.open_web_finished",
        queries=len(OPEN_WEB_COURSE_QUERIES),
        unique_results=len(output),
        sample=summarize_items(output, limit=6),
    )
    return output


# Performs the rotated course queries helper step.
def rotated_course_queries(query_bank: list[str], query_limit: int) -> tuple[list[str], dict]:
    """Return the next slice of course queries and persist the next start index."""
    total = len(query_bank or [])
    query_limit = max(1, min(total, int(query_limit or 1)))
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    rotation = state.get("course_query_rotation") if isinstance(state.get("course_query_rotation"), dict) else {}
    start = int(rotation.get("next_index") or 0) % total
    selected = [query_bank[(start + offset) % total] for offset in range(query_limit)]
    next_index = (start + query_limit) % total
    state["course_query_rotation"] = {
        "updated_at": utc_now().isoformat(),
        "total_queries": total,
        "query_limit": query_limit,
        "start_index": start,
        "next_index": next_index,
        "selected_queries": selected,
    }
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return selected, state["course_query_rotation"]


# Performs the course query batches helper step.
def course_query_batches(query_bank: list[str], query_limit: int) -> tuple[list[list[str]], dict]:
    """Return rotating course query batches so empty batches can fall through."""
    total = len(query_bank or [])
    query_limit = max(1, min(total, int(query_limit or 1)))
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    rotation = state.get("course_query_rotation") if isinstance(state.get("course_query_rotation"), dict) else {}
    start = int(rotation.get("next_index") or 0) % total
    batches = []
    for batch_start in range(start, start + total, query_limit):
        batch = [
            query_bank[(batch_start + offset) % total]
            for offset in range(min(query_limit, total - (batch_start - start)))
        ]
        if batch:
            batches.append(batch)
    return batches, {
        "updated_at": utc_now().isoformat(),
        "total_queries": total,
        "query_limit": query_limit,
        "start_index": start,
        "next_index": start,
        "selected_queries": [],
        "attempted_batches": 0,
        "fallback_used": False,
    }


# Saves save course query rotation to the configured output or state store.
def save_course_query_rotation(rotation: dict, attempted_queries: list[str], attempted_batches: int, found_count: int) -> dict:
    """Persist course rotation after knowing how many fallback batches were needed."""
    total = int(rotation.get("total_queries") or 0)
    start = int(rotation.get("start_index") or 0)
    next_index = (start + max(1, len(attempted_queries))) % total if total else 0
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    state["course_query_rotation"] = {
        **rotation,
        "updated_at": utc_now().isoformat(),
        "next_index": next_index,
        "selected_queries": attempted_queries,
        "attempted_batches": attempted_batches,
        "fallback_used": attempted_batches > 1,
        "found_count": found_count,
    }
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return state["course_query_rotation"]


def course_pool_platform_name(item: dict) -> str:
    return clean_text(item.get("platform") or item.get("provider") or item.get("source") or course_platform_from_url(item.get("url") or ""))


def is_major_course_platform(item: dict) -> bool:
    platform = course_pool_platform_name(item)
    platform_key = normalized_text(platform)
    domain = source_domain(item.get("url") or item.get("source_url") or "")
    return (
        platform in COURSE_MAJOR_PLATFORM_NAMES
        or platform_key in {normalized_text(name) for name in COURSE_MAJOR_PLATFORM_NAMES}
        or domain_matches(domain, COURSE_MAJOR_PLATFORM_DOMAINS)
    )


def load_last_course_platforms() -> list[str]:
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    platforms = state.get("last_course_platforms") if isinstance(state, dict) else []
    return [clean_text(platform) for platform in platforms or [] if clean_text(platform)]


def next_course_fetch_platform_domains(count: int = 6) -> tuple[list[str], dict]:
    state = load_json(NEWS_FETCH_STATE_FILE, {})
    arabic_sources = [domain for domain in PRIMARY_ADULT_FREE_AI_COURSE_SOURCES if domain in COURSE_PLATFORM_URLS]
    arabic_rotation = state.get("course_arabic_source_rotation") if isinstance(state.get("course_arabic_source_rotation"), dict) else {}
    arabic_start = int(arabic_rotation.get("next_index") or 0) % max(1, len(arabic_sources) or 1)
    selected_arabic = arabic_sources[arabic_start:arabic_start + 1] if arabic_sources else []
    if arabic_sources:
        state["course_arabic_source_rotation"] = {
            "updated_at": utc_now().isoformat(),
            "total_sources": len(arabic_sources),
            "start_index": arabic_start,
            "next_index": (arabic_start + 1) % len(arabic_sources),
            "selected_domain": selected_arabic[0],
            "selected_platform": COURSE_PLATFORM_NAMES.get(selected_arabic[0]) or readable_platform_name(selected_arabic[0]),
            "source_pool": arabic_sources,
        }
    prioritized_domains = sorted(
        set(COURSE_DIVERSITY_TARGET_DOMAINS) - set(PRIMARY_ADULT_FREE_AI_COURSE_SOURCES),
        key=lambda domain: (-int(EMPLOYEE_AI_PLATFORM_PRIORITY.get(domain) or 0), domain),
    )
    rotation = state.get("course_platform_fetch_rotation") if isinstance(state.get("course_platform_fetch_rotation"), dict) else {}
    remaining = [domain for domain in rotation.get("remaining_domains") or [] if domain in prioritized_domains]
    cycle = int(rotation.get("cycle") or 0)
    target = max(1, min(max(1, int(count or 6) - len(selected_arabic)), len(prioritized_domains)))
    reshuffled = len(remaining) < target
    if reshuffled:
        cycle += 1
        remaining = list(prioritized_domains)
        random.Random(f"{utc_now().date().isoformat()}-{cycle}-{len(prioritized_domains)}").shuffle(remaining)
    selected = selected_arabic + remaining[:target]
    remaining = remaining[target:]
    record = {
        "updated_at": utc_now().isoformat(),
        "cycle": cycle,
        "target": len(selected),
        "selected_domains": selected,
        "selected_platforms": [COURSE_PLATFORM_NAMES.get(domain) or readable_platform_name(domain) for domain in selected],
        "selected_arabic_domain": selected_arabic[0] if selected_arabic else "",
        "selected_arabic_platform": COURSE_PLATFORM_NAMES.get(selected_arabic[0]) if selected_arabic else "",
        "remaining_domains": remaining,
        "active_domain_count": len(prioritized_domains) + len(arabic_sources),
        "reshuffled": reshuffled,
    }
    state["course_platform_fetch_rotation"] = record
    safe_write_json(NEWS_FETCH_STATE_FILE, state)
    return selected, record


def build_targeted_course_queries(last_platforms: list[str]) -> tuple[list[str], list[str]]:
    target_domains, rotation = next_course_fetch_platform_domains(6)
    target_names = list(rotation.get("selected_platforms") or [])
    queries = []
    for start in range(0, len(target_domains), 3):
        group = target_domains[start:start + 3]
        if group:
            site_tokens = []
            for domain in group:
                patterns = COURSE_DIRECT_PATHS.get(domain) or ("/",)
                for pattern in list(patterns)[:2]:
                    path = str(pattern or "/").strip()
                    if path and path != "/":
                        site_tokens.append(f"site:{domain}{path.rstrip('/')}")
                    else:
                        site_tokens.append(f"site:{domain}")
            sites = " OR ".join(site_tokens)
            queries.append(
                f'("AI course" OR "generative AI course" OR "prompt engineering course") '
                f"({sites}) "
                f'("course" OR "training" OR "certificate" OR "learning path")'
            )
    return queries, target_names


def course_platform_domain_allowed(result_domain: str, platform_domain: str) -> bool:
    result = str(result_domain or "").lower().replace("www.", "")
    platform = str(platform_domain or "").lower().replace("www.", "")
    if domain_matches(result, [platform]):
        return True
    return result in COURSE_PLATFORM_DOMAIN_ALIASES.get(platform, set())


def fetch_course_platform_page_text(url: str, timeout: int | None = None) -> tuple[str, str]:
    try:
        response = requests.get(
            url,
            timeout=timeout or AI_UPDATES_EXA_TIMEOUT,
            headers={"User-Agent": PAGE_FETCH_USER_AGENT},
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return "", f"page_http_{response.status_code}"
        return clean_text(response.text)[:4000], "ok"
    except Exception as exc:
        return "", f"page_fetch_failed:{type(exc).__name__}"


def course_platform_page_title(text: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text or "", flags=re.IGNORECASE | re.DOTALL)
    if match:
        return clean_text(re.sub(r"<[^>]+>", " ", match.group(1)))[:220] or fallback
    return fallback


def course_platform_direct_seed_result(domain: str, platform: str) -> tuple[dict | None, dict]:
    url = COURSE_PLATFORM_URLS.get(domain) or ""
    if not url:
        return None, {"query": "direct_seed", "raw_results": 0, "error": "missing_seed_url"}
    page_text, page_status = fetch_course_platform_page_text(url)
    override_text = COURSE_DIRECT_SEED_TEXT_OVERRIDES.get(domain, "")
    if override_text:
        page_text = f"{override_text} {page_text}"
    return {
        "title": course_platform_page_title(page_text, platform) or platform,
        "url": url,
        "text": page_text,
        "content": page_text,
    }, {"query": "direct_seed", "raw_results": 1, "error": "" if page_status == "ok" else page_status}


def course_platform_discovery_queries(domain: str) -> list[str]:
    queries = []
    if domain == "learn.zapier.com":
        queries.extend([
            'site:learn.zapier.com/courses/zapier-academy-published-preview ("AI Builder Path" OR "AI Orchestrator Path" OR "Build AI Skills" OR "AI automation")',
            'site:learn.zapier.com ("AI" OR "artificial intelligence" OR "automation") ("course" OR "training" OR "lesson")',
            'site:zapier.com/learn ("AI" OR "automation" OR "workflow")',
        ])
    has_specific_path = False
    for pattern in COURSE_DIRECT_PATHS.get(domain) or ("/",):
        path = str(pattern or "/").strip()
        if path and path != "/":
            has_specific_path = True
            base = f"site:{domain}{path.rstrip('/')}"
            queries.append(f'{base} {COURSE_INTENT_QUERY} ("course" OR "training" OR "certificate" OR "learning path")')
            queries.append(f'{base} (AI OR "artificial intelligence" OR "الذكاء الاصطناعي") {WORKFORCE_INTENT_QUERY}')
        else:
            queries.append(f'site:{domain} {COURSE_INTENT_QUERY} ("course" OR "training" OR "certificate" OR "learning path")')
            queries.append(f'site:{domain} (AI OR "artificial intelligence" OR "الذكاء الاصطناعي") {WORKFORCE_INTENT_QUERY}')
    if not has_specific_path:
        queries.append(f'site:{domain} {COURSE_INTENT_QUERY} ("course" OR "training" OR "certificate" OR "learning path")')
    queries.append(f'site:{domain} (AI OR "artificial intelligence" OR "الذكاء الاصطناعي") ("course" OR "training" OR "certificate" OR "برنامج" OR "دورة") {WORKFORCE_INTENT_QUERY}')
    seen = set()
    output = []
    for query in queries:
        key = re.sub(r"\s+", " ", query.lower())
        if key not in seen:
            seen.add(key)
            output.append(query)
    return output


def score_course_platform_result(raw: dict, *, platform: str, domain: str, source: str, query: str) -> dict:
    title = clean_text(raw.get("title") or "")
    url = str(raw.get("url") or "").strip()
    snippet = clean_text(raw.get("text") or raw.get("content") or raw.get("snippet") or " ".join(raw.get("highlights") or []))
    result_domain = source_domain(url)
    if url and not course_platform_domain_allowed(result_domain, domain):
        page_text, page_status = "", "skipped_wrong_domain"
    elif any(term in str(url or "").lower() for term in COURSE_BAD_URL_TERMS):
        page_text, page_status = "", "skipped_bad_course_url"
    else:
        page_text, page_status = fetch_course_platform_page_text(url) if url else ("", "missing_url")
    evidence = f"{title} {snippet} {page_text[:1600]}"
    direct = course_url_is_direct(url, title=title, content=evidence)
    has_course = bool(COURSE_PLATFORM_DISCOVERY_RE.search(evidence))
    # AI-relevance is checked against title+snippet only, not the full
    # page_text slice: page_text is a raw scrape that often includes site
    # navigation/sidebar links to unrelated course categories, and a
    # standalone "AI" mention there was enough to pass a pure digital-
    # marketing course (hit in production 2026-07-11: HubSpot Academy's
    # "Digital Marketing Course" was accepted as an Advanced AI course).
    # The actual course description (title+snippet) is what should decide.
    has_ai = bool(COURSE_AI_DISCOVERY_RE.search(f"{title} {snippet}"))
    workforce_fit = is_workforce_course_text(evidence)
    # bool() wrap is required: `and` returns the last truthy operand rather
    # than a real bool, so when title/url are non-empty strings this could
    # otherwise leak a str into the sum() below and crash the whole scoring
    # call (hit in practice once SearXNG started feeding real results here -
    # some of its results have an empty title, which used to short-circuit
    # this chain to "" instead of False).
    page_blocked_but_exa_enough = bool(
        page_status.startswith(COURSE_NON_FATAL_PAGE_STATUSES) and title and url and direct and has_course and has_ai
    )
    reasons = []
    if not title or not url:
        reasons.append("missing_title_or_url")
    if url and not course_platform_domain_allowed(result_domain, domain):
        reasons.append("wrong_domain")
    if not direct:
        reasons.append("not_direct_course_url")
    if not has_course:
        reasons.append("missing_course_signal")
    if not has_ai:
        reasons.append("missing_ai_signal")
    if has_student_course_reject_signal(evidence, domain=result_domain or domain):
        reasons.append("student_audience")
    if has_developer_only_course_signal(evidence):
        reasons.append("developer_only_audience")
    if has_expired_course_signal(evidence):
        reasons.append("expired_or_closed_registration")
    if page_status != "ok" and not page_blocked_but_exa_enough:
        reasons.append(page_status)
    return {
        "passed": not reasons,
        "platform": platform,
        "source": source,
        "site": result_domain,
        "title": title,
        "url": url,
        "content": evidence,
        "query": query,
        "page_status": page_status,
        "reasons": reasons,
        "score": sum([direct, has_course, has_ai, workforce_fit, page_status == "ok" or page_blocked_but_exa_enough]),
    }


# Course discovery used to fire a single Exa request with no retry at all -
# any transient 429/500/502/503/504 just returned 0 results for that domain
# with no second attempt, unlike the news fetch path (fetch_exa_query_rows's
# exa_request_once) which retries with backoff. Mirrors that same resilience
# here so a single flaky response doesn't silently drop a whole platform.
def fetch_exa_course_platform_raw(query: str, max_results: int) -> tuple[list[dict], str]:
    if not EXA_API_KEY:
        return [], "missing_exa_api_key"
    payload = {
        "query": query,
        "numResults": max(1, max_results),
        "type": "neural",
        "contents": {"text": True, "highlights": True},
    }
    if COURSE_QUERY.get("startPublishedDate"):
        payload["startPublishedDate"] = COURSE_QUERY.get("startPublishedDate")
    headers = {"Accept": "application/json", "Content-Type": "application/json", "x-api-key": EXA_API_KEY}
    last_error = ""
    attempts = max(1, AI_UPDATES_EXA_RETRIES + 1)
    for attempt in range(attempts):
        try:
            response = requests.post(
                "https://api.exa.ai/search",
                headers=headers,
                json=payload,
                timeout=AI_UPDATES_EXA_TIMEOUT,
            )
            if response.status_code < 400:
                return list((response.json() or {}).get("results") or []), ""
            last_error = exa_http_error(response)
            retry_after = response.headers.get("Retry-After", "")
            should_retry = response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        except requests.exceptions.Timeout as exc:
            last_error = f"exa_request_failed:{exc}"
            retry_after = ""
            should_retry = True
        except Exception as exc:
            return [], f"exa_request_failed:{type(exc).__name__}"
        if attempt >= attempts - 1 or not should_retry:
            return [], last_error
        try:
            delay = float(retry_after) if retry_after else AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS * (attempt + 1)
        except Exception:
            delay = AI_UPDATES_EXA_RETRY_BACKOFF_SECONDS * (attempt + 1)
        time.sleep(max(0.5, min(delay, 8)))
    return [], last_error or "exa_request_failed:unknown"


# Course discovery used to be Exa-only even though this module already
# imports every SearXNG helper via `import *` from news_discovery. SearXNG's
# literal `site:` matching is a good complement to Exa's neural search for
# course-catalog pages, which tend to be plain listing pages Exa sometimes
# ranks below marketing content.
def fetch_searxng_course_platform_raw(query: str, max_results: int) -> tuple[list[dict], str]:
    try:
        response = requests.get(
            search_url(),
            params={
                "q": query,
                "format": "json",
                "language": "en",
                "engines": SEARXNG_RELIABLE_ENGINES,
                "categories": "general",
                "pageno": 1,
            },
            timeout=AI_UPDATES_SEARXNG_TIMEOUT,
        )
        response.raise_for_status()
        return list((response.json() or {}).get("results") or [])[: max(1, max_results)], ""
    except Exception as exc:
        return [], f"searxng_request_failed:{type(exc).__name__}"


def fetch_course_platform_discovery(domain: str, max_results: int) -> tuple[list[dict], dict]:
    platform = COURSE_PLATFORM_NAMES.get(domain) or readable_platform_name(domain)
    rows = []
    attempts = []
    seed_raw, seed_attempt = course_platform_direct_seed_result(domain, platform)
    attempts.append(seed_attempt)
    if seed_raw:
        rows.append(score_course_platform_result(seed_raw, platform=platform, domain=domain, source="direct_seed", query="direct_seed"))
    for query in course_platform_discovery_queries(domain):
        exa_raw, exa_error = fetch_exa_course_platform_raw(query, max_results)
        attempts.append({"query": query, "source": "exa", "raw_results": len(exa_raw), "error": exa_error})
        scored = [
            score_course_platform_result(item, platform=platform, domain=domain, source="exa", query=query)
            for item in exa_raw
        ]
        # SearXNG's literal site: matching complements Exa's neural search for
        # plain course-catalog listing pages (see fetch_searxng_course_platform_raw).
        searxng_raw, searxng_error = fetch_searxng_course_platform_raw(query, max_results)
        attempts.append({"query": query, "source": "searxng", "raw_results": len(searxng_raw), "error": searxng_error})
        scored.extend(
            score_course_platform_result(item, platform=platform, domain=domain, source="searxng", query=query)
            for item in searxng_raw
        )
        rows.extend(scored)
        if any(item["passed"] for item in scored):
            break
    passed = sorted((item for item in rows if item["passed"]), key=lambda item: item["score"], reverse=True)
    output = []
    for item in passed:
        source_label = item.get("source") or "exa"
        normalized = normalize_course_candidate(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "content": item.get("content") or "",
            },
            fetch_source=f"{source_label}_course_targeted_search",
            query="",
        )
        if not normalized:
            continue
        normalized["source_query"] = item.get("query") or ""
        normalized["course_platform_discovery_source"] = item.get("source") or ""
        normalized["course_platform_page_status"] = item.get("page_status") or ""
        output.append(normalized)
    failures = Counter(reason for item in rows for reason in item.get("reasons") or [])
    return output, {
        "domain": domain,
        "platform": platform,
        "passed": bool(output),
        "raw_checked": len(rows),
        "query_attempts": attempts,
        "failure_reasons": dict(failures),
        "selected": len(output),
    }


def add_course_pool_candidate(
    item: dict,
    output: list[dict],
    seen_urls: set[str],
    platform_counts: Counter,
    cap_logged: set[str],
) -> bool:
    key = memory_url_key(item.get("url") or "")
    if not key or key in seen_urls:
        return False
    platform = course_pool_platform_name(item)
    platform_key = normalized_text(platform)
    cap = COURSE_MAJOR_PLATFORM_CAP if is_major_course_platform(item) else COURSE_RAW_PLATFORM_CAP
    if platform_key and platform_counts[platform_key] >= cap:
        if platform_key not in cap_logged:
            safe_print(f"[AI Updates] Platform cap reached: {platform} ({cap}/{cap}) - skipping further results")
            log_event("courses.platform_cap_reached", platform=platform, cap=cap, major_platform=is_major_course_platform(item))
            cap_logged.add(platform_key)
        return False
    seen_urls.add(key)
    output.append(item)
    if platform_key:
        platform_counts[platform_key] += 1
    return True


# Fetches fetch course candidates from the configured external source.
def fetch_course_candidates(max_results: int = 10) -> list[dict]:
    """Fetch course cards from trusted domains and direct-course open-web discovery."""
    apply_discovered_platform_promotions()
    last_platforms = load_last_course_platforms()
    target_domains, platform_rotation = next_course_fetch_platform_domains(6)
    targeted_names = list(platform_rotation.get("selected_platforms") or [])
    safe_print(f"[AI Updates] Last run platforms: {', '.join(last_platforms) if last_platforms else 'none'}")
    safe_print(f"[AI Updates] Targeting new platforms: {', '.join(targeted_names) if targeted_names else 'none'}")
    log_event(
        "courses.platform_targeting_started",
        last_platforms=last_platforms,
        targeted_platforms=targeted_names,
        targeted_domains=target_domains,
        selected_arabic_domain=platform_rotation.get("selected_arabic_domain"),
        selected_arabic_platform=platform_rotation.get("selected_arabic_platform"),
    )
    active_course_domains = set(COURSE_PLATFORM_URLS)
    query_bank = [
        query for query in (list(EMPLOYEE_AI_EXTRA_QUERIES) + list(COURSE_QUERY_VARIANTS or ([COURSE_QUERY.get("query")] if COURSE_QUERY.get("query") else [])))
        if not query_site_domains(query) or query_site_domains(query).issubset(active_course_domains)
    ]
    if not query_bank:
        safe_print("[AI Updates] Exa course skipped: no course queries configured")
        return []
    query_limit = max(1, min(len(query_bank), AI_UPDATES_COURSE_EXA_QUERY_LIMIT))
    batches, rotation = course_query_batches(query_bank, query_limit)
    log_event(
        "courses.query_rotation",
        total_queries=len(query_bank),
        query_limit=query_limit,
        start_index=rotation.get("start_index"),
        planned_batches=len(batches),
        selected_queries=batches[0] if batches else [],
    )
    per_query = max(3, min(max_results, AI_UPDATES_COURSE_EXA_RESULTS_PER_QUERY))
    output = []
    seen_urls = set()
    platform_counts = Counter()
    cap_logged = set()
    attempted_queries = []
    attempted_batches = 0
    min_platforms = min(10, max_results)
    targeted_added = 0
    platform_reports = []
    if target_domains:
        with ThreadPoolExecutor(max_workers=min(len(target_domains), 4)) as executor:
            futures = {
                executor.submit(
                    fetch_course_platform_discovery,
                    domain,
                    per_query,
                ): domain
                for domain in target_domains
            }
            for future in as_completed(futures):
                platform_items, platform_report = future.result()
                platform_reports.append(platform_report)
                for item in platform_items or []:
                    if add_course_pool_candidate(item, output, seen_urls, platform_counts, cap_logged):
                        targeted_added += 1
        log_event(
            "courses.platform_targeting_finished",
            targeted_domains=target_domains,
            targeted_added=targeted_added,
            platform_reports=platform_reports,
            platform_counts=dict(platform_counts),
        )
    for selected_queries in batches:
        attempted_batches += 1
        attempted_queries.extend(selected_queries)
        batch_output = []
        with ThreadPoolExecutor(max_workers=min(len(selected_queries), 4)) as executor:
            futures = {
                executor.submit(fetch_exa_course_query, query, per_query): query
                for query in selected_queries
            }
            for future in as_completed(futures):
                for item in future.result() or []:
                    if add_course_pool_candidate(item, output, seen_urls, platform_counts, cap_logged):
                        batch_output.append(item)
        log_event(
            "courses.query_batch_finished",
            batch=attempted_batches,
            queries=len(selected_queries),
            unique_results=len(batch_output),
            fallback_used=attempted_batches > 1,
            selected_queries=selected_queries,
        )
        platform_count = len({
            normalized_text(item.get("platform") or item.get("provider") or course_platform_from_url(item.get("url") or ""))
            for item in output
            if item.get("platform") or item.get("provider") or item.get("url")
        })
        if len(output) >= max_results and platform_count >= min_platforms and attempted_batches >= min(3, max(2, len(batches))):
            break
    rotation = save_course_query_rotation(rotation, attempted_queries, attempted_batches, len(output))
    open_output = fetch_open_web_course_candidates(max_results=max_results)
    open_added = 0
    for item in open_output:
        if add_course_pool_candidate(item, output, seen_urls, platform_counts, cap_logged):
            open_added += 1
    safe_print(
        f"[AI Updates] Exa course collected unique={len(output)} targeted_added={targeted_added} queries={len(attempted_queries)} open_web_added={open_added} batches={attempted_batches}"
    )
    log_event(
        "courses.query_rotation_saved",
        total_queries=len(query_bank),
        query_limit=query_limit,
        start_index=rotation.get("start_index"),
        next_index=rotation.get("next_index"),
        attempted_batches=rotation.get("attempted_batches"),
        fallback_used=rotation.get("fallback_used"),
        found_count=rotation.get("found_count"),
        targeted_results=targeted_added,
        open_web_results=len(open_output),
        open_web_added=open_added,
        platform_counts=dict(platform_counts),
        selected_queries=rotation.get("selected_queries"),
    )
    bank_stats = upsert_course_bank(output)
    safe_print(
        f"[AI Updates] course bank upsert added={bank_stats.get('added')} "
        f"updated={bank_stats.get('updated')} total={bank_stats.get('total')}"
    )
    log_event("courses.bank_upserted", **bank_stats)
    return diversify_course_candidates(output, max_results)

__all__ = sorted(name for name in globals() if not name.startswith("_"))
