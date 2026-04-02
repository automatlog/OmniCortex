import numpy as np

from core.voice.relay import (
    DEFAULT_GREETING_WORDS,
    DEFAULT_INCOMPLETE_ENDINGS,
    DEFAULT_STOP_PHRASES,
    detect_vad_state,
    extract_complete_sentences,
    is_greeting_only,
    looks_incomplete_partial,
    match_stop_phrase,
)


def test_match_stop_phrase_detects_whole_phrase():
    assert match_stop_phrase("please stop talking now", DEFAULT_STOP_PHRASES) == "stop talking"
    assert match_stop_phrase("can you stop", DEFAULT_STOP_PHRASES) == "stop"


def test_looks_incomplete_partial_checks_last_word():
    assert looks_incomplete_partial("tell me about", DEFAULT_INCOMPLETE_ENDINGS) is True
    assert looks_incomplete_partial("tell me about loans.", DEFAULT_INCOMPLETE_ENDINGS) is False


def test_is_greeting_only_allows_simple_salutations():
    assert is_greeting_only("hello hey", DEFAULT_GREETING_WORDS) is True
    assert is_greeting_only("hello I need help", DEFAULT_GREETING_WORDS) is False


def test_detect_vad_state_uses_hysteresis_thresholds():
    speaking = np.ones(16000, dtype=np.float32) * 0.2
    brief_pause = np.concatenate([
        np.ones(14000, dtype=np.float32) * 0.2,
        np.zeros(2000, dtype=np.float32),
    ])
    utterance_end = np.concatenate([
        np.ones(8000, dtype=np.float32) * 0.2,
        np.zeros(8000, dtype=np.float32),
    ])

    assert detect_vad_state(speaking, rate=16000, base_threshold=0.01, brief_pause_ms=250, utterance_end_ms=500, brief_factor=0.9, end_factor=0.75) == "speaking"
    assert detect_vad_state(brief_pause, rate=16000, base_threshold=0.01, brief_pause_ms=100, utterance_end_ms=500, brief_factor=0.9, end_factor=0.75) == "brief_pause"
    assert detect_vad_state(utterance_end, rate=16000, base_threshold=0.01, brief_pause_ms=250, utterance_end_ms=400, brief_factor=0.9, end_factor=0.75) == "utterance_end"


def test_extract_complete_sentences_ignores_decimal_points():
    sentences, remainder = extract_complete_sentences("Rate is 10.5 percent. Next sentence")
    assert sentences == ["Rate is 10.5 percent."]
    assert remainder == " Next sentence"
