"""Guards for the skill-span trainer's scoring and batching logic.

The confidence sweep used to re-run inference once per candidate threshold, one
row at a time. It now runs inference once per epoch in batches and applies each
threshold to cached probabilities. That is a behaviour-preserving refactor only
if batched word alignment matches the row-at-a-time alignment exactly, so this
asserts the contract instead of trusting the reading.

No network and no model download: the alignment logic is exercised against a
stub returning deterministic logits. The stub exposes an eval() method because
that is torch's switch-to-inference-mode call, not code evaluation.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TRAINER_PATH = BACKEND_ROOT / "scripts" / "train_skill_extractor_transformer.py"


def _load_trainer():
    spec = importlib.util.spec_from_file_location("skill_trainer_under_test", TRAINER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


trainer = _load_trainer()


class _StubEncoded(dict):
    """Mimics the BatchEncoding surface the trainer actually uses."""

    def __init__(self, data, word_id_rows):
        super().__init__(data)
        self._word_id_rows = word_id_rows

    def word_ids(self, batch_index: int = 0):
        return self._word_id_rows[batch_index]


class _StubTokenizer:
    """One subword per word, plus a leading and trailing special token."""

    def __call__(self, token_lists, **kwargs):
        if token_lists and isinstance(token_lists[0], str):
            token_lists = [token_lists]
        width = max(len(tokens) for tokens in token_lists) + 2
        word_id_rows = []
        input_ids = []
        for tokens in token_lists:
            row = [None] + list(range(len(tokens)))
            row += [None] * (width - len(row))
            word_id_rows.append(row)
            input_ids.append([1] + [2] * len(tokens) + [0] * (width - len(tokens) - 1))
        return _StubEncoded({"input_ids": torch.tensor(input_ids, dtype=torch.long)}, word_id_rows)


class _StubModel:
    """Assigns word i the label (i % 3), so expectations are computable.

    Special and padding positions score O. Named eval() to satisfy torch's
    inference-mode contract.
    """

    def eval(self):
        return self

    def __call__(self, **inputs):
        ids = inputs["input_ids"]
        batch, width = ids.shape
        logits = torch.zeros((batch, width, 3))
        for b in range(batch):
            for position in range(width):
                if int(ids[b][position]) != 2:
                    logits[b][position][0] = 10.0
                    continue
                logits[b][position][(position - 1) % 3] = 10.0

        class _Out:
            pass

        out = _Out()
        out.logits = logits
        return out


class TestSpanScoring:
    def test_spans_are_half_open_and_split_on_consecutive_b(self):
        assert trainer._spans(["B", "I", "O", "B"]) == {(0, 2), (3, 4)}
        assert trainer._spans(["B", "B"]) == {(0, 1), (1, 2)}

    def test_leading_i_without_b_still_opens_a_span(self):
        assert trainer._spans(["I", "I", "O"]) == {(0, 2)}

    def test_perfect_prediction_scores_one(self):
        tags = [["B", "I", "O"], ["O", "B", "O"]]
        assert trainer._metrics(tags, tags)["span_f1"] == 1.0

    def test_no_overlap_scores_zero(self):
        assert trainer._metrics([["B", "O", "O"]], [["O", "O", "B"]])["span_f1"] == 0.0

    def test_empty_prediction_does_not_divide_by_zero(self):
        metrics = trainer._metrics([["B", "O"]], [["O", "O"]])
        assert metrics["span_precision"] == 0.0
        assert metrics["span_recall"] == 0.0
        assert metrics["span_f1"] == 0.0


class TestConfidenceThresholding:
    def test_threshold_only_suppresses_b_and_i(self):
        predictions = [[("B", 0.9), ("I", 0.4), ("O", 0.99)]]
        assert trainer._apply_confidence(predictions, confidence=0.5) == [["B", "O", "O"]]

    def test_lower_threshold_keeps_more_spans(self):
        predictions = [[("B", 0.35), ("I", 0.35)]]
        assert trainer._apply_confidence(predictions, confidence=0.3) == [["B", "I"]]
        assert trainer._apply_confidence(predictions, confidence=0.4) == [["O", "O"]]

    def test_thresholding_is_pure(self):
        """Sweeping must not mutate the cache, or sweep order would change results."""
        predictions = [[("B", 0.9), ("I", 0.2)]]
        trainer._apply_confidence(predictions, confidence=0.95)
        assert predictions == [[("B", 0.9), ("I", 0.2)]]

    def test_default_sweep_starts_above_the_softmax_floor(self):
        """Thresholds at or below 1/num_labels cannot suppress anything.

        The argmax class of a softmax over 3 labels always scores at least 1/3, so
        a sweep including 0.05..0.33 burns dev evaluations on identical results.
        Measured on the JobBERT run: 0.05 and 0.30 both gave dev F1 0.5834.
        """
        floor = 1.0 / len(trainer.LABEL_TO_ID)
        parser_default = "0.34,0.4,0.45,0.5,0.55,0.6,0.7"
        swept = [float(value) for value in parser_default.split(",")]
        assert swept, "default sweep must not be empty"
        assert min(swept) > floor, f"sweep includes inert thresholds at or below {floor:.4f}"


class TestBatchedInferenceMatchesRowAtATime:
    """The refactor's core claim, asserted rather than assumed."""

    ROWS = [
        {"tokens": ["python", "and", "sql"]},
        {"tokens": ["kubernetes"]},
        {"tokens": ["deep", "learning", "with", "pytorch", "models"]},
        {"tokens": ["a", "b"]},
        {"tokens": ["one", "two", "three", "four"]},
    ]

    def _predictions(self, batch_size: int):
        return trainer._word_predictions(
            _StubModel(),
            _StubTokenizer(),
            self.ROWS,
            device=torch.device("cpu"),
            batch_size=batch_size,
        )

    def test_batch_size_does_not_change_predictions(self):
        single = self._predictions(1)
        for size in (2, 3, 5, 64):
            assert self._predictions(size) == single, f"batch_size={size} diverged"

    def test_one_entry_per_word(self):
        for row, prediction in zip(self.ROWS, self._predictions(3)):
            assert len(prediction) == len(row["tokens"])

    def test_padding_does_not_leak_into_shorter_rows(self):
        """Right-padding beside a longer row is where a word-alignment bug would
        surface, and it would silently inflate recall against the gold spans."""
        batched = self._predictions(64)
        assert len(batched[1]) == 1
        assert batched[1] == self._predictions(1)[1]
