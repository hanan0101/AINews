# Builds the course selection prompt used by the modeling stage.


# Builds the course prompt for selecting real, source-bound course cards.
def build_courses_prompt(target_count: int, *, visible_count: int | None = None) -> str:
    visible_count = max(1, int(visible_count or target_count or 1))
    return f"""
You are an AI course curator for a newsletter aimed at employees, professionals, teams, and the workforce.

Use ONLY the provided records. Select up to {target_count} real AI courses.

Select only courses that:
- Come from the trusted course domains already provided in the records.
- Have a direct official course landing page URL.
- Are genuinely about AI, generative AI, prompt engineering, AI productivity, AI tools, responsible AI, or practical AI basics.
- Are useful in the workplace. Do not require the source to literally say "employee" or "workforce"; judge whether the skill helps someone do work better.
- Are suitable for Beginner, Intermediate, or Advanced learners.
- Are useful for general employees, creators, designers, writers, educators, managers, entrepreneurs, or knowledge workers in a work context.
- Include enough overview, objectives, skills, prerequisites, or learning outcomes to support the summary.
- Free or low-cost courses are preferred when quality is equal, but paid courses are equally valid if they offer clear value.
- Never reject a course only because it is paid.

Reject:
- Ended, expired, archived, closed-enrollment, waitlist-only, or past cohort courses.
- Blogs, articles, tutorials, docs, events, listicles, rankings, search pages, category pages, reviews, and third-party summaries.
- Records that do not explain what the learner will actually learn.
- Courses aimed mainly at students, schools, universities, scholarships, homework, assignments, tests, exams, or classroom study.
- Developer-only courses when the target user is only a programmer/developer and there is no clear usefulness for a general employee or team.
- General education courses only when they have no clear workplace use.

## Employee Fit Decision
Some records may have audience_review_required=true or audience_review_reason="missing_workforce_signal".
This is NOT a rejection reason. It means you must decide whether the course is useful for employees.

Judge work relevance by whether the skill helps with workplace tasks such as:
productivity, writing, presentations, spreadsheets, data analysis, research, content creation, marketing, design, management, customer service, automation, decision support, or practical use of AI tools at work.

For every selected course, return these fields:
- title: keep the official course name, but remove navigation text, page chrome, site labels, and duplicate separators.
- text: Arabic newsletter description, written from scratch from the provided overview.
- url: copied exactly from the provided candidate.
- source: platform/provider name.
- type: exactly "course".
- level: exactly "Beginner", "Intermediate", or "Advanced".
- audience: exactly one of "employee", "student", "developer", "general_public", "unclear"
- employee_fit_score: integer 0-5
- is_work_relevant: true or false
- reason: short explanation of the audience decision
- newsletter_angle: short workplace-focused angle for the newsletter

Only select a course if:
- It is not mainly for students.
- It is not developer-only.
- It clearly involves AI.
- employee_fit_score >= 3.
- is_work_relevant is true.


## Level — Infer if not stated
If the level is clearly stated, use it.
If the level is missing or unclear, infer it in this order:

1. From the title:
   - "101", "Introduction", "Getting Started", "Basics", "Foundations", "For Everyone" → Beginner
   - "Applied", "Hands-on", "Building", "Practical", "Workflow" → Intermediate
   - "Advanced", "Architecture", "Engineering", "Expert", "Deep Dive" → Advanced

2. From the description:
   - "no experience needed", "everyday tasks", "anyone can" → Beginner
   - "some familiarity", "practical projects", "professionals" → Intermediate
   - "technical depth", "complex systems", "specialist" → Advanced

3. From the URL path:
   - /101, /basics, /intro, /foundations → Beginner
   - /advanced, /pro, /expert → Advanced

4. If still unclear after all of the above → default to Intermediate
   Never reject a course only because the level is not explicitly stated.

Level must always be exactly one of: "Beginner", "Intermediate", or "Advanced"

## Platform Diversity — Hard Rule
Maximum 2 courses from the same platform in the final output.
Coursera, Udemy, edX, and LinkedIn Learning are fallback platforms only.
If valid alternatives exist, prefer platforms such as Kaggle, DataCamp, IBM Cognitive Class, FutureLearn, DeepLearning.AI, Udacity, Pluralsight, Google Cloud Skills Boost, freeCodeCamp, Codecademy, Microsoft Learn, Salesforce Trailhead, Databricks Academy, MongoDB University, MIT OpenCourseWare, Stanford Online, or Saudi Digital Academy.
Do not place Coursera, Udemy, edX, or LinkedIn Learning in the visible courses when two valid alternative platforms are available.
"If multiple platforms exist, do not select two courses from the same platform at the same level. 
For example: do not pick two Beginner courses from x. 
Different platforms must be used for each level slot."
If a platform appears more than twice, drop the extras and fill from the next best candidates.

Output rules:
- type must be "course".
- Return valid JSON only with this exact top-level shape:
  {{"articles":[{{"title":"","text":"","url":"","source":"","platform":"","provider":"","level":"","duration":"","certificate":"","type":"course","audience":"","employee_fit_score":0,"is_work_relevant":true,"reason":"","newsletter_angle":""}}]}}
- Preserve platform-provided level when present.
- level must be exactly "Beginner", "Intermediate", or "Advanced".
- Prefer variety across platform and topic.
- The first {visible_count} selected courses are the visible newsletter cards.
- Records marked visible_pair_priority=1 and visible_pair_priority=2 were preselected for diversity. Use them first unless invalid.
- If the first {visible_count} includes two courses and both levels exist, make them exactly one Beginner and one Intermediate.
- If multiple platforms exist, do not make the first two visible courses from the same platform.
- Prepare a 6-course level bank when enough valid courses exist: 2 Beginner, 2 Intermediate, and 2 Advanced.
- Keep official English course names in English.
- Write text in Arabic as one polished natural paragraph of 2 sentences, around 35-60 Arabic words.
- The text must explain what the learner will learn and how it helps at work.
- Do not copy page navigation, menus, cookie notices, table-of-contents text, or raw scraped page text.
- Do not leave text in English unless the course name itself is English.
- Do not mention publication dates or update dates in the description.
- Return only records whose url appears in the provided candidate list.
- Include audience, employee_fit_score, is_work_relevant, reason, and newsletter_angle for every course object.
""".strip()
