# DocuBot Model Card

This model card is a short reflection on your DocuBot system. Fill it out after you have implemented retrieval and experimented with all three modes:

1. Naive LLM over full docs  
2. Retrieval only  
3. RAG (retrieval plus LLM)

Use clear, honest descriptions. It is fine if your system is imperfect.

---

## 1. System Overview

**What is DocuBot trying to do?**  
Describe the overall goal in 2 to 3 sentences.

> DocuBot answers developer questions about a codebase using its project documentation (the Markdown files in `docs/`). It has three modes so the same question can be compared with and without grounding:
> 1. **Naive LLM:** Gemini answers on its own. The menu says "over full docs," but the current code never sends the docs.
> 2. **Retrieval only:** shows the most relevant doc sections, with no LLM.
> 3. **RAG:** Gemini answers using only the retrieved sections.
>
> The goal is to see how retrieval affects whether answers are grounded, accurate and honest about what the docs don't say.

**What inputs does DocuBot take?**  
For example: user question, docs in folder, environment variables.

> - **A question:** either one custom query typed at the prompt, or the built-in `SAMPLE_QUERIES` from `dataset.py` (press Enter).
> - **Documentation:** every `.md` and `.txt` file in `docs/`. Currently that's API_REFERENCE.md, AUTH.md, DATABASE.md and SETUP.md.
> - **Environment:** `GEMINI_API_KEY`, loaded from `.env`. It's required for Modes 1 and 3. Without it, only Mode 2 runs. The model name is set in `llm_client.py` (`GEMINI_MODEL_NAME`).
> - **A mode choice:** 1, 2 or 3 from the menu in `main.py`.

**What outputs does DocuBot produce?**

> - **Mode 1:** a Gemini answer written without any project docs in the prompt.
> - **Mode 2:** up to 3 raw doc sections, each labeled with its filename. If retrieval finds nothing, it prints "I do not know based on these docs."
> - **Mode 3:** a Gemini answer based on up to 3 retrieved sections, which should cite the files it used. It replies "I do not know based on the docs I have." when retrieval is empty or the sections don't support an answer.

---

## 2. Retrieval Design

**How does your retrieval system work?**  
Describe your choices for indexing and scoring.

- How do you turn documents into an index?
- How do you score relevance for a query?
- How do you choose top snippets?

> **1. Markdown heading-based sections.** Each loaded document is split into sections at Markdown heading lines (`#` through `######`). Each heading stays at the top of its section, so a snippet like `### GET /api/users` keeps the endpoint name together with its description. Text before the first heading becomes its own section. A file with no headings stays as one section. Lines inside ``` code fences are never treated as headings. The four docs produce 40 sections. The full documents stay in `self.documents` for any code that needs them, such as `full_corpus_text()`.
>
> **2. Section IDs.** Each section gets a unique ID made from its filename and position, such as `API_REFERENCE.md#7`. These are stored in `self.sections` (ID → filename and section text), so several sections from the same file are indexed and scored separately.
>
> **3. Tokenizing and the index.** Text is lowercased and split into runs of letters and digits. Punctuation and underscores act as separators, so `auth_utils.py` gives `auth`, `utils` and `py`. `build_index` maps each word to the list of section IDs containing it.
>
> **4. Stop words.** A small list of common question and filler words (such as *what, which, where, how, is, the, do, a, to, of*) is removed from the **query only**. The index still holds every word. The list is kept short on purpose, so a one-word query like `SQLite` still counts.
>
> **5. Word-overlap scoring.** `score_document` counts how many **distinct** meaningful query words appear in a section. A word that appears 10 times still counts once.
>
> **6. Choosing top snippets.** `retrieve` uses the index to find only the sections that share at least one meaningful query word. It scores those sections and drops any with a score of 0. Results are sorted by score (highest first), then by filename, then by position in the file. The top 3 come back as `(filename, section_text)` pairs.
>
> **7. Empty retrieval.** If no meaningful query word appears in any section (for example, `xyzzy`), or the query is all stop words, `retrieve` returns `[]`. Mode 2 then prints "I do not know based on these docs." Mode 3 returns "I do not know based on the docs I have." without calling Gemini.

**What tradeoffs did you make?**  
For example: speed vs precision, simplicity vs accuracy.

> - **Simplicity and transparency over accuracy:** exact word overlap is easy to inspect (you can see exactly which words matched), but it treats different forms of a word as unrelated. For example, "generated" and "generation" don't match. In Q1, Token Generation ranked 2nd behind Environment Variables because only the latter contains "generated."
> - **No minimum score:** this keeps one-word queries working, but any single shared word is enough to return a section. In Q3, retrieval returned weak matches on `use` and `app`.
> - **Heading sections over paragraphs:** sections keep headings and their details together. In Q2, the `GET /api/users` snippet included the admin-only note. Splitting on blank lines would have separated the endpoint name from its description. The cost is that long sections can match scattered words.
> - **Counting distinct words:** this stops long, repetitive sections from winning just because they're long, but it produces many ties. Ties are broken by filename, which is predictable but says nothing about relevance.
> - **Speed:** the index means only sections that share a word with the query get scored. That isn't needed for 40 sections, but it would matter for a larger doc set.

---

## 3. Use of the LLM (Gemini)

**When does DocuBot call the LLM and when does it not?**  
Briefly describe how each mode behaves.

- Naive LLM mode: Calls Gemini once per question. `main.py` builds the full corpus with `bot.full_corpus_text()` and passes it to `naive_answer_over_full_docs`, but that method ignores `all_text`. The prompt is only "You are a documentation assistant. Answer this developer question: {query}". **No documentation reaches the model**, despite the menu label "Naive LLM over full docs."
- Retrieval only mode: Never calls Gemini. `DocuBot.retrieve` returns the top 3 Markdown sections by word-overlap score, and `answer_retrieval_only` prints them with their filenames. If nothing matches, it prints "I do not know based on these docs."
- RAG mode: Runs the same `retrieve` step, then calls Gemini with only those 3 sections as context. If retrieval returns nothing, it refuses before calling Gemini.

> Only Modes 1 and 3 call the LLM. Mode 1 is effectively ungrounded generation, because the docs are loaded but dropped before the prompt is built. Mode 3 is the only mode where Gemini sees project evidence.

**What instructions do you give the LLM to keep it grounded?**  
Summarize the rules from your prompt. For example: only use snippets, say "I do not know" when needed, cite files.

> The RAG prompt in `answer_from_snippets`:
> - shows each snippet labeled `File: <filename>`
> - says to answer using only the snippets and not to invent functions, endpoints or configuration values
> - says to reply exactly "I do not know based on the docs I have." if the snippets are not enough to answer confidently
> - says to briefly mention which files the answer relied on
>
> The Mode 1 prompt has no grounding rules at all.

---

## 4. Experiments and Comparisons

Run the **same set of queries** in all three modes. Fill in the table with short notes.

You can reuse or adapt the queries from `dataset.py`.

> The three questions below are **custom queries**, not the `dataset.py` samples. Each one was typed with **identical wording** in Mode 1, Mode 2 and Mode 3.

| Query | Naive LLM: helpful or harmful? | Retrieval only: helpful or harmful? | RAG: helpful or harmful? | Notes |
|------|---------------------------------|--------------------------------------|---------------------------|-------|
| Where is the auth token generated? (custom query) | Not helpful. Gave generic advice on where to look and asked which codebase was meant. | Helpful but noisy. Returned 3 AUTH.md sections: **Environment Variables ranked 1st** and **Token Generation 2nd**. Token Generation is the section that names `generate_access_token` in `auth_utils.py`. | Helpful. Named `generate_access_token` in `auth_utils.py` and cited AUTH.md. This answer is **supported by the Token Generation section**, not by the 1st-ranked Environment Variables section. | Mode 1 could not answer because it never saw the docs. RAG found the answer in the 2nd-ranked snippet. |
| Which endpoint returns all users? (custom query) | Not helpful. Gave `GET /users` as a **generic suggestion that differs from the documented route** `GET /api/users`. | Helpful. Ranked `GET /api/users` first. The snippet says "Only accessible to admins." | Correct route, but incomplete. Answered `GET /api/users` and cited API_REFERENCE.md, but **left out the admin-only access condition** (see Section 5). | The route was correct for the question asked. The RAG answer left out a condition that Mode 2's raw snippet showed. |
| What payment provider does the app use? (custom query) | Not helpful. Suggested ways to search but named no provider. | **Retrieval returned weak matches:** unrelated DATABASE.md and SETUP.md sections that each matched only one generic word (`use` or `app`). | **Gemini refused after receiving those weak matches:** "I do not know based on the docs I have." | The docs never mention payments. Mode 2 has no minimum score, so weak matches still come back. In Mode 3, Gemini received the same weak matches and refused instead of guessing. |

**What patterns did you notice?**  

- When does naive LLM look impressive but untrustworthy?  
- When is retrieval only clearly better?  
- When is RAG clearly better than both?

> - **Mode 1 has weak grounding. In practice it has none.** Because the docs are never sent, it falls back on general knowledge. Sometimes it is upfront about that (Q1 and Q3 asked for context or suggested searching). Sometimes it gives a generic suggestion that differs from the documented route (Q2: `GET /users`, where the docs define `GET /api/users`). That case deserves the most caution, because a generic route can look like a real answer.
> - **Mode 2 is useful but noisy.** It never makes anything up, and it shows details an LLM summary might drop (Q2: the admin-only note). But the user has to read raw sections to find the answer (Q1: Environment Variables ranked 1st, and the answer was in Token Generation, ranked 2nd). It also returns unrelated snippets when nothing truly matches (Q3), because any single shared word is enough to qualify.
> - **Mode 3 gives the clearest grounded answers.** It turned noisy snippets into a direct, cited answer (Q1, supported by Token Generation; Q2). Gemini also refused correctly after retrieval gave it only weak matches (Q3). The tradeoff is that summarizing can leave out important conditions (Q2: the route was correct, but the admin-only condition was left out).

---

## 5. Failure Cases and Guardrails

**Describe at least two concrete failure cases you observed.**  
For each one, say:

- What was the question?  
- What did the system do?  
- What should have happened instead?

> **Case 1 (observed RAG limitation): an access condition left out.**
> - Question: "Which endpoint returns all users?"
> - Observed RAG answer (exact terminal output):
>
>   ```text
>   The endpoint that returns all users is `GET /api/users`.
>
>   I relied on `API_REFERENCE.md` to answer this question.
>   ```
> - Retrieved snippet (`### GET /api/users`, ranked 1st), quoted from API_REFERENCE.md: "Returns a list of all users. Only accessible to admins." and later "Returns 403 for non admin accounts."
> - Comparison: the route was correct for the question asked, and retrieval supplied the right evidence. But the answer left out an important access condition. The snippet says the endpoint is "Only accessible to admins," and the answer says nothing about who can call it.
> - What should have happened: the answer should say the route is admin-only. Without that, a developer could build a feature for regular users and then hit 403 errors. The prompt forbids inventing details, but nothing asks the model to keep conditions like permissions or required headers.

> **Case 2 (observed in Mode 1): a generic suggestion that differs from the documented route.**
> - Question: "Which endpoint returns all users?"
> - What the system did: Mode 1 offered `GET /users` as a generic suggestion. The documented route is `GET /api/users`.
> - What should have happened: answer `GET /api/users` from the docs. Since Mode 1 receives no docs, it should say it cannot see them. Root cause: `naive_answer_over_full_docs` ignores its `all_text` argument.

> **Case 3 (observed in Modes 2 and 3): weak matches for an uncovered topic.**
> - Question: "What payment provider does the app use?"
> - What the system did: retrieval returned weak matches, 3 unrelated sections that each matched a single generic word (`use` in DATABASE.md Overview; `app` in DATABASE.md Connection Configuration and SETUP.md Required Variables). Mode 2 showed them as-is. In Mode 3, Gemini received those weak matches and refused: "I do not know based on the docs I have."
> - What should have happened: Mode 3's refusal was correct. Mode 2 should also have said "I do not know based on these docs." Retrieval only refuses when zero meaningful words match. It has no minimum score.

> **Pending: needs testing.**
> - *Untested hypothesis: RAG when retrieval misses the evidence.* For the question "Which fields are stored in the users table?", retrieval **may** miss the DATABASE.md `### users` section, because that section's wording ("Stores user account information") doesn't match "fields," "stored" or "table." **Pending a terminal test** in Mode 2 and Mode 3. If the hypothesis holds, possible Mode 3 outcomes are a correct refusal, or an answer built from API_REFERENCE.md response examples instead of the real table schema. The second outcome would be a grounding failure.
> - *Mode 1 with the docs actually included.* Not tested. The current Mode 1 results show behavior without the docs, not "naive LLM over full docs." Re-test after `all_text` is added to the prompt.
> - *RAG with a misleading but on-topic snippet.* For example, a question whose top snippet is close but not right. Not tested yet.

**When should DocuBot say “I do not know based on the docs I have”?**  
Give at least two specific situations.

> - When the docs don't cover the topic at all, such as payment providers (Q3).
> - When the retrieved snippets share words with the question but don't contain the answer. For example, a section that matches only `app` or `use`.
> - When the question asks about something that exists in the docs only by assumption. For example, Mode 1's generic `GET /users` suggestion, which differs from the documented `GET /api/users`.

**What guardrails did you implement?**  
Examples: refusal rules, thresholds, limits on snippets, safe defaults.

> - **Empty-retrieval refusal:** `retrieve` ignores common question words (what, which, where, how, the, is, …). If no remaining word matches any section, it returns `[]`. Modes 2 and 3 then refuse without guessing, and Mode 3 never calls Gemini.
> - **Snippet limit:** only the top 3 sections are returned. Sections are split at Markdown headings, so each snippet stays focused, and each heading travels with its text.
> - **Prompt-level refusal:** the RAG prompt requires the exact "I do not know based on the docs I have." reply when the evidence is insufficient, forbids inventing functions, endpoints or config values, and asks for file citations. Q3 shows this working: Gemini refused after retrieval gave it only weak matches.
> - **Not implemented yet:** a minimum score for retrieval, so weak single-word matches still pass through (Case 3).

---

## 6. Limitations and Future Improvements

**Current limitations**  
List at least three limitations of your DocuBot system.

1. **Mode 1 never sees the docs.** `naive_answer_over_full_docs` drops `all_text`, so Mode 1 results show ungrounded generation, not "naive LLM over full docs."
2. **Retrieval uses exact word overlap.** "generated" doesn't match "generation," and "stored" doesn't match "stores." The right section can rank lower than a less relevant one (observed: Token Generation ranked 2nd for Q1, behind Environment Variables) or be missed entirely (untested hypothesis: the users-table question may miss DATABASE.md).
3. **No minimum relevance score.** One shared generic word is enough to return a section, so Mode 2 shows irrelevant results for questions the docs don't cover (Q3).
4. **RAG answers can leave out access conditions.** In Q2, the route was correct for the question asked, but the answer left out the admin-only condition that the retrieved snippet stated.

**Future improvements**  
List two or three changes that would most improve reliability or usefulness.

1. Include `all_text` in the Mode 1 prompt, so the baseline is a real "full docs" comparison. Then re-run Part 4.
2. Add a minimum match threshold to retrieval, and handle simple word forms (plurals, -ed/-ion), so retrieval returns fewer noisy sections and misses fewer relevant ones.
3. Add a RAG prompt rule to keep any access restrictions, required headers or failure conditions mentioned in the snippets.

---

## 7. Responsible Use

**Where could this system cause real world harm if used carelessly?**  
Think about wrong answers, missing information, or over trusting the LLM.

> - **A cited answer can still be incomplete.** A citation shows where the answer came from. It doesn't show that the answer kept everything important from that source. In Q2, Mode 3 gave the correct route and cited API_REFERENCE.md, but left out that the endpoint is admin-only, even though the retrieved snippet said "Only accessible to admins." This can happen because the model summarizes to answer the exact question asked. Nothing in the current prompt requires it to carry over permissions, required headers or error conditions. A developer who trusts the citation could ship a feature that fails with 403 errors for non-admin users, or misjudge who can see user data.
> - **Ungrounded answers can look like real ones.** Mode 1 doesn't see the docs, yet it offered `GET /users`, a generic suggestion that differs from the documented `GET /api/users`. Code built on that would call a route that doesn't exist.
> - **Retrieval can surface the wrong evidence.** Weak word matches can put unrelated sections in front of the model (Q3), or rank a less relevant section first (Q1). If the right section is missed entirely, a grounded-looking answer could be built from the wrong material. This last risk is an untested hypothesis, pending a terminal test of the users-table question.
> - **Missing information is easy to mistake for absence.** "I do not know based on the docs I have" means the retrieved sections didn't support an answer. It doesn't prove the feature doesn't exist. The docs may be incomplete, or retrieval may have missed the right section.

**What instructions would you give real developers who want to use DocuBot safely?**  
Write 2 to 4 short bullet points.

- **Check the source docs before acting on an answer**, especially for anything involving security, permissions, authentication, data access or configuration. Open the cited file and read the full section, not just the summary.
- **Treat a citation as a pointer, not proof of completeness.** A cited answer can leave out conditions such as admin-only access, required headers or failure cases.
- **Use Mode 2 to see the raw evidence** when an answer matters, and don't rely on Mode 1 for project-specific facts. It doesn't see the docs.
- **Treat "I do not know" as a reason to look further**, not as confirmation that something doesn't exist. Try rewording the question, or search the docs directly.

---
