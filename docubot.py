"""
Core DocuBot class responsible for:
- Loading documents from the docs/ folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import glob
import re

# Common question/filler words ignored when scoring a query.
# Kept deliberately small so topic words (e.g. "sqlite", "token") always count.
QUERY_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "do", "does", "did", "can",
    "i", "me", "my", "it", "this", "that", "these", "there", "any",
    "what", "which", "where", "when", "who", "whom", "whose", "why", "how",
}

HEADING_PATTERN = re.compile(r"^#{1,6}\s")

class DocuBot:
    def __init__(self, docs_folder="docs", llm_client=None):
        """
        docs_folder: directory containing project documentation files
        llm_client: optional Gemini client for LLM based answers
        """
        self.docs_folder = docs_folder
        self.llm_client = llm_client

        # Load documents into memory (full files, unchanged for existing callers)
        self.documents = self.load_documents()  # List of (filename, text)

        # Split documents into heading-based sections for retrieval.
        # Maps unique section_id -> (filename, section_text)
        self.sections = self.build_sections(self.documents)

        # Build a retrieval index over sections: word -> [section_id, ...]
        self.index = self.build_index(
            [(section_id, text) for section_id, (_, text) in self.sections.items()]
        )

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_documents(self):
        """
        Loads all .md and .txt files inside docs_folder.
        Returns a list of tuples: (filename, text)
        """
        docs = []
        pattern = os.path.join(self.docs_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                docs.append((filename, text))
        return docs

    # -----------------------------------------------------------
    # Tokenization Helper
    # -----------------------------------------------------------

    def _tokenize(self, text):
        """
        Lowercases text and extracts words, dropping punctuation.
        Underscores are treated as separators, so identifiers like
        auth_utils or AUTH_SECRET_KEY also match "auth", "utils", etc.
        Returns a list of tokens (duplicates preserved).
        """
        return re.findall(r"[a-z0-9]+", text.lower())

    def _query_terms(self, query):
        """
        Returns the set of meaningful query words: tokens minus common
        question/filler words. A one-word query like "SQLite" is kept.
        """
        return set(self._tokenize(query)) - QUERY_STOP_WORDS

    # -----------------------------------------------------------
    # Section Splitting (Phase 1, Part 3)
    # -----------------------------------------------------------

    def _split_by_headings(self, text):
        """
        Splits Markdown text into sections. Each section starts at a heading
        line (#, ##, ...) and keeps that heading with its body text.
        Text before the first heading becomes its own section, and a file
        with no headings stays as one section. Lines inside ``` code fences
        are never treated as headings.
        Returns a list of non-empty section strings.
        """
        sections = []
        current = []
        in_fence = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if not in_fence and HEADING_PATTERN.match(line) and current:
                sections.append("\n".join(current).strip())
                current = []
            current.append(line)
        if current:
            sections.append("\n".join(current).strip())
        return [s for s in sections if s]

    def build_sections(self, documents):
        """
        Splits each (filename, text) document into heading-based sections.
        Returns a dict mapping a unique section_id (e.g. "API_REFERENCE.md#7")
        to a (filename, section_text) tuple, so sections from the same file
        can be indexed and scored independently.
        """
        sections = {}
        for filename, text in documents:
            for i, section_text in enumerate(self._split_by_headings(text)):
                sections[f"{filename}#{i}"] = (filename, section_text)
        return sections

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def build_index(self, documents):
        """
        TODO (Phase 1):
        Build a tiny inverted index mapping lowercase words to the documents
        they appear in.

        Example structure:
        {
            "token": ["AUTH.md", "API_REFERENCE.md"],
            "database": ["DATABASE.md"]
        }

        Keep this simple: split on whitespace, lowercase tokens,
        ignore punctuation if needed.

        documents: list of (key, text) pairs. The key can be a filename or,
        as used in __init__, a unique section_id.
        """
        index = {}
        for key, text in documents:
            # set() so each key is recorded at most once per word
            for word in set(self._tokenize(text)):
                index.setdefault(word, []).append(key)
        return index

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def score_document(self, query, text):
        """
        TODO (Phase 1):
        Return a simple relevance score for how well the text matches the query.

        Suggested baseline:
        - Convert query into lowercase words
        - Count how many appear in the text
        - Return the count as the score
        """
        query_words = self._query_terms(query)
        text_words = set(self._tokenize(text))
        return len(query_words & text_words)

    def retrieve(self, query, top_k=3):
        """
        TODO (Phase 1):
        Use the index and scoring function to select top_k relevant document snippets.

        Return a list of (filename, text) sorted by score descending.
        """
        # Use the index to find candidate sections sharing a meaningful query word.
        # If no meaningful word matches, candidates stays empty and we return [].
        candidates = set()
        for word in self._query_terms(query):
            candidates.update(self.index.get(word, []))

        # Score each candidate section independently, skipping zero scores
        scored = []
        for section_id in candidates:
            filename, text = self.sections[section_id]
            score = self.score_document(query, text)
            if score > 0:
                scored.append((score, filename, section_id, text))

        # Sort by score descending; break ties by filename, then section order
        scored.sort(
            key=lambda item: (-item[0], item[1], int(item[2].rsplit("#", 1)[1]))
        )

        results = [(filename, text) for _, filename, _, text in scored]
        return results[:top_k]

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=3):
        """
        Phase 1 retrieval only mode.
        Returns raw snippets and filenames with no LLM involved.
        """
        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        formatted = []
        for filename, text in snippets:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=3):
        """
        Phase 2 RAG mode.
        Uses student retrieval to select snippets, then asks Gemini
        to generate an answer using only those snippets.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.documents)
