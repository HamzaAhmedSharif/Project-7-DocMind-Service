"""Provenance: copied from Project 6 DocMind Agent `evaluation/questions.py`
at commit 2a91d77f46dd2bab46c5784b28b9e97b5d584f87. Do not improve the question set here.

Evaluation set for DocMind Agent. Source paper: 'Attention Is All You Need'.
doc    - answerable from the paper. Each key fact has an answer_regex (what a correct answer contains)
         and a paper_regex (proof that the fact is in the paper text).
web    - needs current web information; scored on routing and web citations only.
absent - the paper does not contain the answer; the correct behaviour is to say so.
         absent_regex patterns must NOT match the paper text.
"""


def _fact(fact, answer_regex, paper_regex):
    return {"fact": fact, "answer_regex": answer_regex, "paper_regex": paper_regex}


QUESTIONS = [
    # ---- 12 questions answerable from the paper ----
    {
        "id": "d01",
        "type": "doc",
        "question": "What is self-attention, as defined in the Transformer paper?",
        "key_facts": [
            _fact(
                "relates different positions of a single sequence",
                r"different\s*positions",
                r"different\s*positions\s*of\s*a\s*single\s*sequence",
            ),
            _fact(
                "to compute a representation of the sequence",
                r"represent",
                r"compute\s*a\s*representation\s*of\s*the\s*sequence",
            ),
        ],
    },
    {
        "id": "d02",
        "type": "doc",
        "question": "Which attention function does the Transformer use, and how is it computed?",
        "key_facts": [
            _fact(
                "scaled dot-product attention",
                r"scaled\s*dot[-\s]*product",
                r"scaled\s*dot-?\s*product\s*attention",
            ),
            _fact("softmax over the scaled dot products", r"softmax", r"softmax"),
            _fact(
                "scaling by the square root of the key dimension",
                r"square\s*root|sqrt|√",
                r"divide\s*each\s*by",
            ),
        ],
    },
    {
        "id": "d03",
        "type": "doc",
        "question": "Why are the dot products scaled by the square root of the key dimension d_k?",
        "key_facts": [
            _fact(
                "dot products grow large when d_k is large",
                r"(grow|become|get)\s*large|large\s*(in\s*)?magnitude|large\s*values",
                r"grow\s*large\s*in\s*magnitude",
            ),
            _fact(
                "which pushes softmax into regions with extremely small gradients",
                r"small\s*gradients?|vanishing|saturat",
                r"extremely\s*small\s*gradients",
            ),
        ],
    },
    {
        "id": "d04",
        "type": "doc",
        "question": "How many identical layers do the encoder and the decoder each have in the base Transformer, and what are the two sub-layers of an encoder layer?",
        "key_facts": [
            _fact("N = 6 identical layers", r"\b(6|six)\b", r"n\s*=\s*6\s*identical\s*layers"),
            _fact(
                "a position-wise fully connected feed-forward sub-layer",
                r"feed[-\s]*forward",
                r"position-?\s*wise\s*fully\s*connected\s*feed-?\s*forward",
            ),
        ],
    },
    {
        "id": "d05",
        "type": "doc",
        "question": "What are the model dimension and the number of attention heads used in the base Transformer?",
        "key_facts": [
            _fact("d_model = 512", r"512", r"d\s*_?\s*model\s*=\s*512"),
            _fact(
                "h = 8 parallel attention heads",
                r"\b(8|eight)\b",
                r"h\s*=\s*8\s*parallel\s*attention",
            ),
        ],
    },
    {
        "id": "d06",
        "type": "doc",
        "question": "What is multi-head attention and why does the paper use it?",
        "key_facts": [
            _fact(
                "attends to different representation subspaces",
                r"(different|multiple)\s*(representation\s*)?subspaces?",
                r"different\s*representation\s*subspaces",
            ),
            _fact("linearly projects queries, keys and values", r"project", r"linearly\s*project"),
        ],
    },
    {
        "id": "d07",
        "type": "doc",
        "question": "How does the Transformer give the model information about the order of tokens?",
        "key_facts": [
            _fact("positional encodings", r"positional\s*encoding", r"positional\s*encodings"),
            _fact(
                "sine and cosine functions of different frequencies",
                r"\bsine?\b|sinusoid",
                r"sine\s*and\s*cosine\s*functions\s*of\s*different\s*frequencies",
            ),
            _fact(
                "added to the input embeddings",
                r"\badd(ed|s)?\b|\bsum(med)?\b",
                r"to\s*the\s*input\s*embeddings",
            ),
        ],
    },
    {
        "id": "d08",
        "type": "doc",
        "question": "Which optimizer and learning-rate warmup did the authors use to train the Transformer?",
        "key_facts": [
            _fact("Adam optimizer", r"adam", r"adam\s*optimizer"),
            _fact("warmup_steps = 4000", r"4000|4,000", r"warmup[_\s]*steps\s*=\s*4000"),
        ],
    },
    {
        "id": "d09",
        "type": "doc",
        "question": "Which regularization techniques were used during training?",
        "key_facts": [
            _fact("residual dropout", r"dropout", r"residual\s*dropout"),
            _fact("label smoothing", r"label\s*smoothing", r"label\s*smoothing\s*of\s*value"),
        ],
    },
    {
        "id": "d10",
        "type": "doc",
        "question": "What BLEU scores did the big Transformer reach on WMT 2014 English-to-German and English-to-French?",
        "key_facts": [
            _fact("28.4 BLEU on English-to-German", r"28\.4", r"28\.4"),
            _fact("41.8 (or 41.0) BLEU on English-to-French", r"41\.[08]", r"41\.[08]"),
        ],
    },
    {
        "id": "d11",
        "type": "doc",
        "question": "Why does the paper argue that self-attention is preferable to recurrent and convolutional layers?",
        "key_facts": [
            _fact(
                "shorter path length between long-range dependencies",
                r"path|long-?\s*range|dependenc",
                r"path\s*length\s*between\s*long-?\s*range\s*dependencies",
            ),
            _fact(
                "more computation can be parallelized",
                r"parallel",
                r"computation\s*that\s*can\s*be\s*parallelized",
            ),
        ],
    },
    {
        "id": "d12",
        "type": "doc",
        "question": "What is the purpose of masking in the decoder's self-attention?",
        "key_facts": [
            _fact(
                "positions cannot attend to subsequent positions",
                r"(subsequent|future|later|following)\s*positions",
                r"subsequent\s*positions",
            ),
            _fact(
                "predictions depend only on known outputs at earlier positions",
                r"less\s*than|earlier|previous|preceding|known\s*outputs",
                r"positions\s*less\s*than\s*i",
            ),
        ],
    },
    # ---- 4 questions that need current web information ----
    {
        "id": "w01",
        "type": "web",
        "expected_route": "WEB",
        "question": "What are the latest developments in transformer architectures in 2026?",
    },
    {
        "id": "w02",
        "type": "web",
        "expected_route": "WEB",
        "question": "What is the current state of the art on the WMT 2014 English-to-German translation benchmark?",
    },
    {
        "id": "w03",
        "type": "web",
        "expected_route": "WEB",
        "question": "How many citations does the paper 'Attention Is All You Need' have today?",
    },
    {
        "id": "w04",
        "type": "web",
        "expected_route": "WEB",
        "question": "Which large language models released in 2026 are based on the transformer architecture?",
    },
    # ---- 4 questions the paper cannot answer (correct behaviour: say so) ----
    {
        "id": "a01",
        "type": "absent",
        "absent_regex": [r"imagenet", r"image\s*classification"],
        "question": "According to the paper, what accuracy did the Transformer reach on the ImageNet image classification task?",
    },
    {
        "id": "a02",
        "type": "absent",
        "absent_regex": [r"chinese", r"mandarin"],
        "question": "According to the paper, what BLEU score did the Transformer reach on English-to-Chinese translation?",
    },
    {
        "id": "a03",
        "type": "absent",
        "absent_regex": [r"word\s*error\s*rate", r"librispeech"],
        "question": "According to the paper, what word error rate did the model reach on a speech recognition benchmark?",
    },
    {
        "id": "a04",
        "type": "absent",
        "absent_regex": [r"kwh", r"kilowatt"],
        "question": "According to the paper, how many kilowatt-hours of energy did training the big model consume?",
    },
]
