# Project context for Claude Code

Student submission project: a LangGraph agent that matches credit card charges to
receipts and handwritten shopping lists, tracks warranties, and answers questions.
The full spec is in docs/prompt.md (Hebrew). Keep code simple and readable: the
student must be able to explain every line.

- Graph: src/graph.py. Matching rules (numbers): src/matching.py. Model calls and prompts: src/ai.py.
- Models: free tiers with fallbacks in src/llm.py, configured in .env.
- Tests use tests/fake_ai.py and need no keys: `python -m pytest tests -q`.
- Evaluation: `python -m eval.run_eval --version baseline|improved` (LangSmith), `--offline` without keys.
- Security rules are in docs/prompt.md section 5ב. Never put real personal data in data/ or LangSmith.
- Remaining work is listed at the end of README.md.
