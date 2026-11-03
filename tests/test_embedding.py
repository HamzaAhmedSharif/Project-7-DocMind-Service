import numpy as np
import pytest

from docmind_service.embedding import HashingEmbedder, OnnxEmbedder


def test_hashing_embedder_shape_and_unit_norm():
    embedder = HashingEmbedder()
    vectors = embedder.embed_passages(["self attention", "banana bread"])
    assert vectors.shape == (2, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)


def test_hashing_embedder_is_deterministic_and_semantic():
    embedder = HashingEmbedder()
    query = embedder.embed_query("self attention mechanism")
    assert np.array_equal(query, embedder.embed_query("self attention mechanism"))
    related = embedder.embed_query("self attention layers")
    unrelated = embedder.embed_query("banana bread recipe")
    assert float(query @ related) > float(query @ unrelated)


def test_hashing_embedder_handles_empty_text():
    vector = HashingEmbedder().embed_query("")
    assert vector.shape == (384,)
    assert np.isfinite(vector).all()
    assert np.isclose(np.linalg.norm(vector), 1.0)


def test_hashing_embedder_returns_empty_matrix_for_no_texts():
    assert HashingEmbedder().embed_passages([]).shape == (0, 384)


@pytest.mark.model
def test_onnx_embedder_dimension_unit_norm_and_determinism():
    embedder = OnnxEmbedder()
    texts = ["The cat sat on the mat.", "A dog chased a ball."]
    first = embedder.embed_passages(texts)
    again = embedder.embed_passages(texts)
    assert first.shape == (2, 384)
    assert first.dtype == np.float32
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-3)
    assert np.allclose(first, again, atol=1e-6)


@pytest.mark.model
def test_onnx_query_matches_passage_and_is_cached():
    embedder = OnnxEmbedder()
    passage = embedder.embed_passages(["What is self-attention?"])[0]
    query = embedder.embed_query("What is self-attention?")
    assert np.allclose(query, passage, atol=1e-6)
    assert embedder.embed_query("What is self-attention?") is query


@pytest.mark.model
def test_onnx_embedder_handles_empty_passage_list():
    assert OnnxEmbedder().embed_passages([]).shape == (0, 384)
