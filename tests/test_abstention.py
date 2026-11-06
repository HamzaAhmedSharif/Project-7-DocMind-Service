"""The S2 abstention rule (Master Script 10.2) reuses Project 6's scorer:
an absent question counts as abstained when the API refused it OR the answer
matches scoring.is_abstention. These tests pin the text half in both directions
(10 positive, 10 negative examples) before any provider run relies on it."""

import pytest

from evaluation.scoring import is_abstention

ABSTAINING = [
    "The paper does not contain this information.",
    "No information about ImageNet accuracy is provided in the paper.",
    "The document does not mention Chinese translation results.",
    "This is not mentioned in the paper.",
    "The paper doesn't say how many kilowatt-hours were used.",
    "I cannot find any reference to LibriSpeech in the text.",
    "The provided context does not include word error rates.",
    "There is no mention of speech recognition in the paper.",
    "The paper does not report ImageNet results.",
    "Unable to determine the energy consumption from the document.",
]

ANSWERING = [
    "The Transformer reached 28.4 BLEU on English-to-German.",
    "Self-attention relates different positions of a single sequence.",
    "The paper does not use recurrent layers; it relies entirely on attention.",
    "No fewer than six layers are used in the encoder.",
    "The model cannot attend to subsequent positions because of masking.",
    "It is not possible to parallelize recurrent computation as effectively.",
    "Scaled dot-product attention is computed with a softmax over the scaled dot products.",
    "Positional encodings are added to the input embeddings.",
    "The authors use the Adam optimizer with warmup over 4000 steps.",
    "The big Transformer reached 41.8 BLEU on English-to-French.",
]


@pytest.mark.parametrize("text", ABSTAINING)
def test_abstaining_answers(text):
    assert is_abstention(text) is True


@pytest.mark.parametrize("text", ANSWERING)
def test_answering_answers(text):
    assert is_abstention(text) is False
