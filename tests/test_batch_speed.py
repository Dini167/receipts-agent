"""Many name pairs are asked in small groups at the same time, not in one huge request."""

import time

from src import ai as ai_module
from src.ai import BATCH_SIZE, ModelAI, PairAnswer, PairAnswers


class SlowModel:
    calls = 0

    def invoke(self, prompt):
        SlowModel.calls += 1
        time.sleep(0.3)                        # every request takes a while
        n = sum(1 for line in prompt.splitlines() if line[:1].isdigit() and ". " in line)
        return PairAnswers(answers=[PairAnswer(number=i + 1, same=True) for i in range(n)])


def test_200_pairs_are_split_and_sent_together(monkeypatch):
    import src.llm
    monkeypatch.setattr(src.llm, "get_structured_llm", lambda schema, vision=False: SlowModel())
    model = ModelAI()
    pairs = [(f"store {i}", f"shop {i}") for i in range(200)]
    started = time.time()
    model.prefetch_same(pairs)
    assert SlowModel.calls == -(-200 // BATCH_SIZE)       # 7 groups, not 200 single requests
    assert time.time() - started < 1.5                     # groups run at the same time
    assert all(model._same_cache[p] for p in pairs)
